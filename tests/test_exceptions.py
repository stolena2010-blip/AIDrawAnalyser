"""Unit tests for core.exceptions — heirarchy, messages, UI formatting."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script (pytest optional)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.exceptions import (
    AIError,
    AllModelsFailedError,
    ConfigurationError,
    DrawingLightError,
    EmptyResponseError,
    ExtractionError,
    ImageError,
    InputError,
    InvalidResponseError,
    MasterMatchingError,
    MissingCredentialsError,
    ModelCallError,
    OCRError,
    OCRUnavailableError,
    PDFError,
    StageFailedError,
    format_error_for_ui,
    get_streamlit_level,
)


# ─── Hierarchy ──────────────────────────────────────────────────
def test_all_subclass_base():
    """Every exception class inherits from DrawingLightError."""
    classes = [
        ConfigurationError, MissingCredentialsError,
        InputError, PDFError, ImageError,
        AIError, ModelCallError, InvalidResponseError,
        EmptyResponseError, AllModelsFailedError,
        ExtractionError, StageFailedError, MasterMatchingError,
        OCRError, OCRUnavailableError,
    ]
    for cls in classes:
        assert issubclass(cls, DrawingLightError), f"{cls.__name__} must inherit from DrawingLightError"


def test_nested_inheritance():
    """Mid-level classes inherit from the correct parent."""
    assert issubclass(MissingCredentialsError, ConfigurationError)
    assert issubclass(PDFError, InputError)
    assert issubclass(ImageError, InputError)
    assert issubclass(ModelCallError, AIError)
    assert issubclass(InvalidResponseError, AIError)
    assert issubclass(AllModelsFailedError, AIError)
    assert issubclass(StageFailedError, ExtractionError)
    assert issubclass(MasterMatchingError, ExtractionError)
    assert issubclass(OCRUnavailableError, OCRError)


# ─── Default attributes ─────────────────────────────────────────
def test_default_user_message_exists():
    """Every exception class has non-empty default_user_message."""
    for cls in (PDFError, ImageError, ModelCallError, StageFailedError):
        exc = cls("technical")
        assert exc.user_message
        assert isinstance(exc.user_message, str)


def test_default_suggestion_exists():
    for cls in (PDFError, MissingCredentialsError, OCRUnavailableError):
        exc = cls("technical")
        assert exc.suggestion
        assert len(exc.suggestion) > 10  # non-trivial


# ─── Severity ───────────────────────────────────────────────────
def test_severity_levels():
    """Default severities match design."""
    assert MissingCredentialsError("x").severity == "critical"
    assert AllModelsFailedError("x").severity == "critical"
    assert InvalidResponseError("x").severity == "warning"
    assert EmptyResponseError("x").severity == "warning"
    assert MasterMatchingError("x").severity == "warning"
    assert PDFError("x").severity == "error"  # default


def test_custom_severity_override():
    exc = PDFError("x", severity="warning")
    assert exc.severity == "warning"


# ─── Custom messages ────────────────────────────────────────────
def test_custom_user_message():
    exc = PDFError("tech detail", user_message="הודעה מותאמת")
    assert exc.user_message == "הודעה מותאמת"
    assert "tech detail" in str(exc)


def test_custom_suggestion():
    exc = ImageError("tech", suggestion="פתרון מותאם")
    assert exc.suggestion == "פתרון מותאם"


def test_context_is_stored():
    ctx = {"path": "/tmp/x.pdf", "size": 12345}
    exc = PDFError("x", context=ctx)
    assert exc.context == ctx


def test_context_defaults_to_empty_dict():
    exc = PDFError("x")
    assert exc.context == {}


# ─── StageFailedError ──────────────────────────────────────────
def test_stage_failed_includes_stage_name():
    exc = StageFailedError("stage_2_processes", "vision call failed")
    assert "stage_2_processes" in exc.user_message
    assert exc.context["stage"] == "stage_2_processes"


def test_stage_failed_custom_message():
    exc = StageFailedError("stage_1", "x", user_message="override")
    assert exc.user_message == "override"
    # Stage still in context
    assert exc.context["stage"] == "stage_1"


# ─── format_error_for_ui ───────────────────────────────────────
def test_format_includes_emoji_and_suggestion():
    exc = PDFError("test", user_message="X", suggestion="Y")
    out = format_error_for_ui(exc)
    assert "📕" in out
    assert "X" in out
    assert "Y" in out
    assert "💡" in out


def test_format_generic_exception():
    """Non-DrawingLightError falls back to generic template."""
    exc = ValueError("some random")
    out = format_error_for_ui(exc)
    assert "אירעה שגיאה לא צפויה" in out
    assert "ValueError" in out
    assert "some random" in out


def test_format_includes_technical_when_requested():
    exc = InvalidResponseError("broken JSON here")
    out = format_error_for_ui(exc, include_technical=True)
    assert "broken JSON here" in out


def test_format_hides_technical_by_default():
    exc = InvalidResponseError("broken JSON here")
    out = format_error_for_ui(exc)
    assert "broken JSON here" not in out
    # But user_message still shown
    assert "JSON פגום" in out


# ─── get_streamlit_level ───────────────────────────────────────
def test_streamlit_level_for_warning_severity():
    assert get_streamlit_level(InvalidResponseError("x")) == "warning"
    assert get_streamlit_level(MasterMatchingError("x")) == "warning"


def test_streamlit_level_for_error_severity():
    assert get_streamlit_level(PDFError("x")) == "error"
    assert get_streamlit_level(MissingCredentialsError("x")) == "error"  # critical→error in UI


def test_streamlit_level_for_generic_exception():
    assert get_streamlit_level(ValueError("x")) == "error"
    assert get_streamlit_level(RuntimeError("x")) == "error"


# ─── Exception chaining ────────────────────────────────────────
def test_exception_chains_with_from():
    json_err = None
    try:
        try:
            raise ValueError("original problem")
        except ValueError as exc:
            json_err = exc
            raise InvalidResponseError("wrapped") from exc
    except InvalidResponseError as e:
        assert e.__cause__ is json_err
        assert isinstance(e.__cause__, ValueError)


# ─── Run without pytest ────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        (name, fn) for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}: {e}")
    print(f"\n{passed}/{len(tests)} passed" + (f" ({failed} failed)" if failed else ""))
    sys.exit(0 if failed == 0 else 1)
