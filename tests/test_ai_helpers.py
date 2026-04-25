"""
Unit tests ל-core.ai_helpers — kwargs builder, retry decorator, safe_call fallback.

כל ה-Azure client מולים — אין קריאות אמיתיות.

הרצה:
    pytest tests/test_ai_helpers.py -v
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.ai_helpers import (
    build_kwargs,
    call_text,
    call_vision,
    retry_on_transient,
    safe_call,
)
from core.exceptions import (
    AllModelsFailedError,
    EmptyResponseError,
    InvalidResponseError,
    ModelCallError,
    StageFailedError,
)


# ─────────────────────────────────────────────────────────────────
# build_kwargs — מתאים למודל reasoning vs רגיל
# ─────────────────────────────────────────────────────────────────
class TestBuildKwargs:
    def test_standard_model_includes_temperature(self):
        with patch("core.ai_helpers.is_reasoning_model", return_value=False):
            kwargs = build_kwargs(max_tokens=2000, temperature=0.2, json_mode=False)
            assert kwargs["max_tokens"] == 2000
            assert kwargs["temperature"] == 0.2
            assert "max_completion_tokens" not in kwargs

    def test_reasoning_model_uses_max_completion_tokens(self):
        with patch("core.ai_helpers.is_reasoning_model", return_value=True):
            kwargs = build_kwargs(max_tokens=4000, temperature=0.5, json_mode=False)
            assert kwargs["max_completion_tokens"] == 4000
            assert "temperature" not in kwargs
            assert "max_tokens" not in kwargs

    def test_json_mode_adds_response_format(self):
        with patch("core.ai_helpers.is_reasoning_model", return_value=False):
            kwargs = build_kwargs(max_tokens=1000, temperature=0.1, json_mode=True)
            assert kwargs["response_format"] == {"type": "json_object"}

    def test_no_json_mode_no_response_format(self):
        with patch("core.ai_helpers.is_reasoning_model", return_value=False):
            kwargs = build_kwargs(max_tokens=1000, temperature=0.1, json_mode=False)
            assert "response_format" not in kwargs


# ─────────────────────────────────────────────────────────────────
# retry_on_transient — exponential backoff
# ─────────────────────────────────────────────────────────────────
class TestRetryOnTransient:
    def test_succeeds_on_first_try(self):
        @retry_on_transient(max_attempts=3, base_delay=0.001)
        def fn():
            return "ok"
        assert fn() == "ok"

    def test_retries_on_transient_exception(self):
        attempts = {"n": 0}

        @retry_on_transient(max_attempts=3, base_delay=0.001)
        def fn():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ConnectionError("transient")
            return "ok"

        assert fn() == "ok"
        assert attempts["n"] == 2

    def test_raises_after_max_attempts(self):
        attempts = {"n": 0}

        @retry_on_transient(max_attempts=3, base_delay=0.001)
        def fn():
            attempts["n"] += 1
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError):
            fn()
        assert attempts["n"] == 3

    def test_does_not_retry_on_application_errors(self):
        attempts = {"n": 0}

        @retry_on_transient(max_attempts=5, base_delay=0.001)
        def fn():
            attempts["n"] += 1
            raise EmptyResponseError("model returned empty")

        with pytest.raises(EmptyResponseError):
            fn()
        # Stopped after 1 attempt — no retry on app-level errors
        assert attempts["n"] == 1

    def test_does_not_retry_on_invalid_response(self):
        attempts = {"n": 0}

        @retry_on_transient(max_attempts=3, base_delay=0.001)
        def fn():
            attempts["n"] += 1
            raise InvalidResponseError("bad json")

        with pytest.raises(InvalidResponseError):
            fn()
        assert attempts["n"] == 1


# ─────────────────────────────────────────────────────────────────
# call_vision — JSON parsing + error handling
# ─────────────────────────────────────────────────────────────────
def _make_vision_client(content: str, finish_reason: str = "stop"):
    """בונה client מולק שמחזיר תוכן נתון."""
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    response = SimpleNamespace(choices=[choice], usage=usage)
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


class TestCallVision:
    def test_returns_parsed_json_and_usage(self):
        client = _make_vision_client('{"part_number": "BP70534A"}')
        result, usage = call_vision(client, "gpt-test", "prompt", ["BASE64"])
        assert result["part_number"] == "BP70534A"
        assert usage.total_tokens == 15

    def test_strips_markdown_code_fences(self):
        client = _make_vision_client('```json\n{"x": 1}\n```')
        result, _ = call_vision(client, "gpt-test", "prompt", ["BASE64"])
        assert result["x"] == 1

    def test_strips_plain_code_fences(self):
        client = _make_vision_client('```\n{"x": 2}\n```')
        result, _ = call_vision(client, "gpt-test", "prompt", ["BASE64"])
        assert result["x"] == 2

    def test_empty_response_raises(self):
        client = _make_vision_client("", finish_reason="length")
        with pytest.raises(EmptyResponseError) as exc:
            call_vision(client, "gpt-test", "prompt", ["BASE64"])
        assert "length" in str(exc.value).lower() or "finish_reason" in str(exc.value)

    def test_malformed_json_raises_invalid_response(self):
        client = _make_vision_client("not valid json at all")
        with pytest.raises(InvalidResponseError):
            call_vision(client, "gpt-test", "prompt", ["BASE64"])

    def test_passes_images_in_content(self):
        client = _make_vision_client('{"x": 1}')
        call_vision(client, "gpt-test", "P", ["IMG1", "IMG2"])
        # בודק שהקריאה כוללת את התמונות בתוך ה-content
        call_args = client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        content = messages[0]["content"]
        # 1 text + 2 images
        assert len(content) == 3
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"


# ─────────────────────────────────────────────────────────────────
# call_text — קריאה טקסטואלית פשוטה
# ─────────────────────────────────────────────────────────────────
class TestCallText:
    def test_returns_text_and_usage(self):
        client = _make_vision_client("Hello world")
        text, usage = call_text(client, "gpt-test", "prompt")
        assert text == "Hello world"
        assert usage.total_tokens == 15

    def test_strips_whitespace(self):
        client = _make_vision_client("   trimmed   \n")
        text, _ = call_text(client, "gpt-test", "prompt")
        assert text == "trimmed"

    def test_empty_returns_empty_string(self):
        client = _make_vision_client("")
        text, _ = call_text(client, "gpt-test", "prompt")
        assert text == ""


# ─────────────────────────────────────────────────────────────────
# safe_call — fallback לוגיקה
# ─────────────────────────────────────────────────────────────────
class TestSafeCall:
    def test_primary_succeeds_no_fallback(self):
        primary = MagicMock(return_value=("result", "usage"))
        with patch("core.ai_helpers.get_fallback_client_and_deployment",
                   return_value=(None, None, None)):
            result = safe_call(primary, "client1", "dep1", "extra")
        assert result == ("result", "usage")
        primary.assert_called_once_with("client1", "dep1", "extra")

    def test_primary_fails_no_fallback_raises_model_call_error(self):
        primary = MagicMock(side_effect=ConnectionError("network"))
        with patch("core.ai_helpers.get_fallback_client_and_deployment",
                   return_value=(None, None, None)):
            with pytest.raises(ModelCallError):
                safe_call(primary, "client1", "dep1")

    def test_primary_fails_fallback_succeeds(self):
        primary_call = {"n": 0}
        def fn(client, deployment, *args, model=None):
            primary_call["n"] += 1
            if client == "client1":
                raise ConnectionError("primary down")
            return ("fallback_result", "fallback_usage")
        with patch("core.ai_helpers.get_fallback_client_and_deployment",
                   return_value=("client2", "dep2", "gpt-fallback")):
            result = safe_call(fn, "client1", "dep1")
        assert result == ("fallback_result", "fallback_usage")
        # נקרא פעמיים: primary + fallback
        assert primary_call["n"] == 2

    def test_both_fail_raises_all_models_failed(self):
        def fn(client, deployment, *args, model=None):
            raise ConnectionError(f"failed {client}")
        with patch("core.ai_helpers.get_fallback_client_and_deployment",
                   return_value=("client2", "dep2", "gpt-fallback")):
            with pytest.raises(AllModelsFailedError) as exc:
                safe_call(fn, "client1", "dep1")
        assert "fallback" in str(exc.value).lower() or "primary" in str(exc.value).lower()

    def test_stage_arg_wraps_in_stage_failed_error(self):
        primary = MagicMock(side_effect=ConnectionError("oops"))
        with patch("core.ai_helpers.get_fallback_client_and_deployment",
                   return_value=(None, None, None)):
            with pytest.raises(StageFailedError) as exc:
                safe_call(primary, "client1", "dep1", stage="stage_1")
        # ה-stage צריך להופיע בהודעה
        assert exc.value.context.get("stage") == "stage_1"
