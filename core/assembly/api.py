"""
עזרי קריאה ל-Azure OpenAI עבור pipeline המכלולים.

עצמאי משאר ה-pipeline — לא נשען על הפרטיים של core/extractor.py.
שלוש נקודות ה-entry:
    _call_vision  — קריאה למודל ויז'ואלי (Stage 1/2 + Overview Image)
    _call_text_json — קריאה טקסטואלית שמחזירה JSON (analyze_relationships)
    _build_kwargs / _strip_json_fences — עזרים פנימיים
"""
from __future__ import annotations

import json
import logging

from core.azure_client import is_reasoning_model

logger = logging.getLogger(__name__)


def _build_kwargs(max_tokens: int, temperature: float, json_mode: bool) -> dict:
    kwargs: dict = {}
    if is_reasoning_model():
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def _strip_json_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return raw


def _call_vision(client, deployment: str, prompt: str, images_b64: list[str]):
    from typing import Any
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for img_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high",
            },
        })
    budget = 16000 if is_reasoning_model() else 6000
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        **_build_kwargs(max_tokens=budget, temperature=0.1, json_mode=True),
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    if not raw:
        return {}, response.usage
    try:
        return json.loads(raw), response.usage
    except json.JSONDecodeError as exc:
        logger.warning("Assembly JSON parse failed: %s — head: %s", exc, raw[:200])
        return {}, response.usage


def _call_text_json(client, deployment: str, prompt: str):
    """קריאה טקסטואלית שמחזירה JSON (לשלב ניתוח הקשרים)."""
    budget = 8000 if is_reasoning_model() else 3000
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        **_build_kwargs(max_tokens=budget, temperature=0.2, json_mode=True),
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    if not raw:
        return {}, response.usage
    try:
        return json.loads(raw), response.usage
    except json.JSONDecodeError as exc:
        logger.warning("Relationships JSON parse failed: %s — head: %s", exc, raw[:200])
        return {"summary_he": raw, "assemblies": [], "orphans": [],
                "missing_children": [], "warnings_he": []}, response.usage
