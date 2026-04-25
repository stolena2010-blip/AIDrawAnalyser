"""
קוד משותף לקריאות AI — מרכז לוגיקה שהייתה מפוזרת בין
core/extractor.py ו-core/assembly.py.

כולל:
- _build_kwargs(): kwargs לקריאה ל-OpenAI חכמה למודל (reasoning/standard)
- _call_vision(): קריאת Vision עם הפיכת JSON + טיפול בתגובה ריקה/פגומה
- _call_text(): קריאת טקסט חופשי
- _safe_call(): wrapping עם fallback למודל השני + שגיאות מפורשות
- retry_on_transient(): decorator ל-retry עם exponential backoff

שינוי במקום אחד = משפיע על שני מצבי העבודה (שרטוט בודד + מכלולים).
"""
from __future__ import annotations

import functools
import json
import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from core.azure_client import get_fallback_client_and_deployment, is_reasoning_model
from core.exceptions import (
    AllModelsFailedError,
    EmptyResponseError,
    InvalidResponseError,
    ModelCallError,
    StageFailedError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ─── Retry decorator ────────────────────────────────────────────
def retry_on_transient(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    retryable: tuple[type[Exception], ...] | None = None,
) -> Callable:
    """
    Decorator — retry עם exponential backoff + jitter לשגיאות זמניות.

    מתאים לקריאות AI שלעיתים נכשלות מרייט-לימיט / timeout.
    לא עושה retry על שגיאות AIDrawAnalyser ספציפיות (מחלקת DrawingLightError
    וצאצאיה — MissingCredentials וכו'). שם המחלקה נשאר Legacy לתאימות imports.

    Args:
        max_attempts: מספר ניסיונות מירבי (כולל הראשון)
        base_delay: שהייה ראשונה בשניות
        max_delay: שהייה מקסימלית בין ניסיונות
        retryable: tuple של exceptions שעליהם לבצע retry.
                   ברירת מחדל — שגיאות רשת/API כלליות, לא שגיאות יישום.
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            allowed = retryable or (Exception,)
            non_retryable = (
                # שגיאות יישום — לא שווה לנסות שוב
                StageFailedError, AllModelsFailedError,
                EmptyResponseError, InvalidResponseError,
            )
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except non_retryable:
                    raise  # לא retry על שגיאות יישום
                except allowed as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = min(
                        base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                        max_delay,
                    )
                    logger.warning(
                        "Attempt %d/%d failed (%s: %s) — retry in %.1fs",
                        attempt, max_attempts, type(exc).__name__, exc, delay,
                    )
                    time.sleep(delay)
            assert last_exc is not None  # for type checker
            raise last_exc
        return wrapper
    return decorator


# ─── קריאה למודל ────────────────────────────────────────────────
def build_kwargs(max_tokens: int, temperature: float, json_mode: bool,
                 model: str | None = None) -> dict:
    """בונה kwargs מתאימים למודל הפעיל (reasoning vs רגיל)."""
    kwargs: dict = {}
    if is_reasoning_model(model):
        # reasoning models (gpt-5.x / o-series): אין temperature, אין max_tokens
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


@retry_on_transient(max_attempts=3, base_delay=2.0)
def call_vision(client, deployment: str, prompt: str, images: list[str],
                model: str | None = None, *, max_tokens: int = 4000,
                temperature: float = 0.1) -> tuple[dict, object]:
    """
    קריאת Vision לתמונות base64.
    מחזיר (result_dict, usage). זורק InvalidResponseError/EmptyResponseError
    אם התגובה פגומה — כדי ש-safe_call יוכל לנסות fallback.
    """
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img_b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
        })

    budget = 32_000 if is_reasoning_model(model) else max_tokens
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        **build_kwargs(max_tokens=budget, temperature=temperature,
                       json_mode=True, model=model),
    )

    raw = (response.choices[0].message.content or "").strip()
    # reasoning models לפעמים עוטפים את ה-JSON
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    if not raw:
        finish_reason = getattr(response.choices[0], "finish_reason", "?")
        logger.warning(
            "Vision call returned empty content (finish_reason=%s, usage=%s)",
            finish_reason, getattr(response, "usage", None),
        )
        raise EmptyResponseError(
            f"Empty response from model (finish_reason={finish_reason})",
            context={"finish_reason": str(finish_reason)},
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed: %s — raw head: %s", exc, raw[:200])
        raise InvalidResponseError(
            f"Model returned malformed JSON: {exc}",
            context={"raw_head": raw[:200]},
        ) from exc

    return result, response.usage


@retry_on_transient(max_attempts=3, base_delay=2.0)
def call_text(client, deployment: str, prompt: str,
              model: str | None = None, *, max_tokens: int = 400,
              temperature: float = 0.3) -> tuple[str, object]:
    """קריאה טקסטואלית רגילה. מחזיר (text, usage)."""
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        **build_kwargs(max_tokens=max_tokens, temperature=temperature,
                       json_mode=False, model=model),
    )
    return (response.choices[0].message.content or "").strip(), response.usage


def safe_call(call_fn, client, deployment, *extra_args, stage: str | None = None):
    """
    מריץ קריאה מול המודל הראשי. אם נכשל ויש fallback — מנסה מולו.

    אם ``stage`` מסופק — שגיאה סופית תיעטף ב-StageFailedError לצורך
    הודעת משתמש עם הקשר של השלב שנכשל.
    """
    def _wrap(exc: Exception) -> Exception:
        if stage:
            return StageFailedError(
                stage, str(exc),
                context={"stage": stage, "original_error": str(exc)},
            )
        return exc

    try:
        return call_fn(client, deployment, *extra_args)
    except Exception as primary_exc:
        fb_client, fb_deployment, fb_model = get_fallback_client_and_deployment()
        if fb_client is None:
            primary_err: Exception = ModelCallError(
                f"Primary model call failed: {primary_exc}",
                context={"original_error": str(primary_exc)},
            )
            raise _wrap(primary_err) from primary_exc
        logger.warning(
            "⚠️ קריאה למודל הראשי נכשלה (%s) — עובר ל-fallback: %s",
            primary_exc, fb_model,
        )
        try:
            return call_fn(fb_client, fb_deployment, *extra_args, model=fb_model)
        except Exception as fb_exc:
            both_err: Exception = AllModelsFailedError(
                f"Primary: {primary_exc} | Fallback: {fb_exc}",
                context={
                    "primary_error": str(primary_exc),
                    "fallback_error": str(fb_exc),
                    "fallback_model": fb_model,
                },
            )
            raise _wrap(both_err) from fb_exc
