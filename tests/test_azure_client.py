"""
Unit tests ל-core.azure_client — קונפיגורציה, runtime settings, model selection.

לא מבצע קריאות אמיתיות ל-Azure (כל credential mocked).

הרצה:
    pytest tests/test_azure_client.py -v
"""
import json

import pytest

from core import azure_client
from core.azure_client import (
    MODEL_GPT_4O,
    MODEL_GPT_5_4,
    SUPPORTED_MODELS,
    _active_model,
    _is_gpt54,
    enabled_modes,
    get_deployment,
    get_fallback_client_and_deployment,
    get_fallback_model,
    get_masters_xlsx_path,
    is_fallback_enabled,
    is_reasoning_model,
    save_runtime_settings,
)
from core.exceptions import MissingCredentialsError


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    """כל בדיקה — קובץ runtime נקי בתיקיה זמנית."""
    rt_file = tmp_path / "_runtime_settings.json"
    monkeypatch.setattr(azure_client, "_RUNTIME_FILE", rt_file)
    return rt_file


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """מנקה משתני סביבה רלוונטיים — כל בדיקה מקבלת state נקי."""
    for var in (
        "ACTIVE_MODEL", "MODEL_FALLBACK_ENABLED", "ENABLED_MODES",
        "MASTERS_XLSX_PATH",
        "MODEL_GPT_5_4_ENDPOINT", "MODEL_GPT_5_4_API_KEY",
        "MODEL_GPT_5_4_DEPLOYMENT", "MODEL_GPT_5_4_API_VERSION",
        "MODEL_GPT_5_4_IS_REASONING",
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION", "AZURE_DEPLOYMENT_NAME",
        "AZURE_OPENAI_DEPLOYMENT",
    ):
        monkeypatch.delenv(var, raising=False)


# ─────────────────────────────────────────────────────────────────
# _is_gpt54 + is_reasoning_model
# ─────────────────────────────────────────────────────────────────
class TestModelDetection:
    @pytest.mark.parametrize("model,expected", [
        ("gpt-5.4", True),
        ("GPT-5.4", True),
        ("gpt-5.4-turbo", True),
        ("gpt-4o-vision", False),
        ("gpt-4o", False),
        ("o1-preview", False),  # o-series, not 5.4
        ("", False),
    ])
    def test_is_gpt54(self, model, expected):
        assert _is_gpt54(model) is expected

    def test_reasoning_for_gpt54_default_true(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.4")
        assert is_reasoning_model() is True

    def test_reasoning_for_gpt54_can_be_disabled(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.4")
        monkeypatch.setenv("MODEL_GPT_5_4_IS_REASONING", "false")
        assert is_reasoning_model() is False

    @pytest.mark.parametrize("model,expected", [
        ("o1-mini", True),
        ("o3-preview", True),
        ("o4-base", True),
        ("gpt-5-turbo", True),
        ("gpt-4o-vision", False),
        ("gpt-4o", False),
    ])
    def test_reasoning_for_other_models(self, model, expected):
        assert is_reasoning_model(model) is expected


# ─────────────────────────────────────────────────────────────────
# _active_model — runtime > env > default
# ─────────────────────────────────────────────────────────────────
class TestActiveModel:
    def test_default_is_gpt4o(self, isolated_runtime):
        assert _active_model() == MODEL_GPT_4O

    def test_env_var_overrides_default(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.4")
        assert _active_model() == "gpt-5.4"

    def test_runtime_overrides_env(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-4o-vision")
        save_runtime_settings(active_model="gpt-5.4")
        assert _active_model() == "gpt-5.4"

    def test_strips_whitespace(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "  gpt-5.4  ")
        assert _active_model() == "gpt-5.4"


# ─────────────────────────────────────────────────────────────────
# is_fallback_enabled
# ─────────────────────────────────────────────────────────────────
class TestFallbackEnabled:
    def test_default_true(self, isolated_runtime):
        assert is_fallback_enabled() is True

    def test_env_false(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("MODEL_FALLBACK_ENABLED", "false")
        assert is_fallback_enabled() is False

    def test_runtime_overrides_env(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("MODEL_FALLBACK_ENABLED", "false")
        save_runtime_settings(fallback_enabled=True)
        assert is_fallback_enabled() is True


# ─────────────────────────────────────────────────────────────────
# enabled_modes
# ─────────────────────────────────────────────────────────────────
class TestEnabledModes:
    def test_default_both(self, isolated_runtime):
        assert sorted(enabled_modes()) == ["assembly", "single"]

    def test_env_var(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ENABLED_MODES", "single")
        assert enabled_modes() == ["single"]

    def test_env_invalid_falls_back_to_default(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ENABLED_MODES", "garbage,nonsense")
        assert sorted(enabled_modes()) == ["assembly", "single"]

    def test_runtime_overrides_env(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ENABLED_MODES", "single,assembly")
        save_runtime_settings(enabled_modes=["assembly"])
        assert enabled_modes() == ["assembly"]

    def test_empty_runtime_falls_back_to_default(self, isolated_runtime):
        # נשמר ריק — היגיון defensive: לפחות אחד תמיד צריך להיות
        save_runtime_settings(enabled_modes=[])
        # save_runtime_settings ינרמל ל-default אם ה-list ריק
        modes = enabled_modes()
        assert "single" in modes or "assembly" in modes


# ─────────────────────────────────────────────────────────────────
# get_masters_xlsx_path
# ─────────────────────────────────────────────────────────────────
class TestGetMastersXlsxPath:
    def test_default_empty(self, isolated_runtime):
        assert get_masters_xlsx_path() == ""

    def test_env_var(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("MASTERS_XLSX_PATH", "/data/Masters.xlsx")
        assert get_masters_xlsx_path() == "/data/Masters.xlsx"

    def test_runtime_overrides_env(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("MASTERS_XLSX_PATH", "/from/env")
        save_runtime_settings(masters_xlsx_path="/from/runtime")
        assert get_masters_xlsx_path() == "/from/runtime"


# ─────────────────────────────────────────────────────────────────
# save_runtime_settings — persistence
# ─────────────────────────────────────────────────────────────────
class TestSaveRuntimeSettings:
    def test_writes_to_file(self, isolated_runtime):
        save_runtime_settings(active_model="gpt-5.4", fallback_enabled=False)
        assert isolated_runtime.exists()
        data = json.loads(isolated_runtime.read_text(encoding="utf-8"))
        assert data["active_model"] == "gpt-5.4"
        assert data["fallback_enabled"] is False

    def test_partial_update_preserves_others(self, isolated_runtime):
        save_runtime_settings(active_model="gpt-5.4", fallback_enabled=True)
        save_runtime_settings(active_model="gpt-4o-vision")  # רק active_model
        data = json.loads(isolated_runtime.read_text(encoding="utf-8"))
        assert data["active_model"] == "gpt-4o-vision"
        assert data["fallback_enabled"] is True  # לא נמחק

    def test_invalid_modes_normalized(self, isolated_runtime):
        save_runtime_settings(enabled_modes=["garbage", "single"])
        data = json.loads(isolated_runtime.read_text(encoding="utf-8"))
        assert data["enabled_modes"] == ["single"]

    def test_empty_modes_falls_back_to_default(self, isolated_runtime):
        save_runtime_settings(enabled_modes=[])
        data = json.loads(isolated_runtime.read_text(encoding="utf-8"))
        assert sorted(data["enabled_modes"]) == ["assembly", "single"]


# ─────────────────────────────────────────────────────────────────
# get_deployment — שם deployment לפי המודל
# ─────────────────────────────────────────────────────────────────
class TestGetDeployment:
    def test_default_gpt4o_deployment(self, isolated_runtime):
        # ברירת מחדל אם אין env
        assert get_deployment("gpt-4o-vision") == "gpt-4o"

    def test_gpt54_deployment(self, isolated_runtime):
        assert get_deployment("gpt-5.4") == "gpt-5.4"

    def test_env_overrides_default(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("AZURE_DEPLOYMENT_NAME", "my-custom-gpt4o")
        assert get_deployment("gpt-4o-vision") == "my-custom-gpt4o"

    def test_uses_active_model_when_none(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.4")
        monkeypatch.setenv("MODEL_GPT_5_4_DEPLOYMENT", "my-gpt54")
        assert get_deployment() == "my-gpt54"


# ─────────────────────────────────────────────────────────────────
# get_fallback_model — opposite of active
# ─────────────────────────────────────────────────────────────────
class TestGetFallbackModel:
    def test_when_active_is_4o_fallback_is_54(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-4o-vision")
        assert get_fallback_model() == MODEL_GPT_5_4

    def test_when_active_is_54_fallback_is_4o(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-5.4")
        assert get_fallback_model() == MODEL_GPT_4O


# ─────────────────────────────────────────────────────────────────
# get_fallback_client_and_deployment — graceful failure
# ─────────────────────────────────────────────────────────────────
class TestFallbackClient:
    def test_disabled_returns_none(self, isolated_runtime):
        save_runtime_settings(fallback_enabled=False)
        client, dep, model = get_fallback_client_and_deployment()
        assert (client, dep, model) == (None, None, None)

    def test_enabled_but_no_credentials_returns_none(self, isolated_runtime, monkeypatch):
        monkeypatch.setenv("ACTIVE_MODEL", "gpt-4o-vision")
        save_runtime_settings(fallback_enabled=True)
        # אין credentials ל-gpt-5.4 (clean_env מנקה הכל) → fallback לא יעבוד
        client, dep, model = get_fallback_client_and_deployment()
        assert client is None  # מבטיח graceful, לא קריסה


# ─────────────────────────────────────────────────────────────────
# Client building — credential checks
# ─────────────────────────────────────────────────────────────────
class TestClientBuildingCredentials:
    def test_gpt4o_missing_credentials_raises(self, isolated_runtime):
        from core.azure_client import _build_client_gpt4o
        with pytest.raises(MissingCredentialsError) as exc:
            _build_client_gpt4o()
        assert "AZURE_OPENAI" in exc.value.suggestion

    def test_gpt54_missing_credentials_raises(self, isolated_runtime):
        from core.azure_client import _build_client_gpt54
        with pytest.raises(MissingCredentialsError) as exc:
            _build_client_gpt54()
        assert "GPT_5_4" in exc.value.suggestion or "GPT-5.4" in exc.value.user_message


# ─────────────────────────────────────────────────────────────────
# Constants sanity
# ─────────────────────────────────────────────────────────────────
def test_supported_models_includes_both():
    assert MODEL_GPT_4O in SUPPORTED_MODELS
    assert MODEL_GPT_5_4 in SUPPORTED_MODELS
    assert len(SUPPORTED_MODELS) == 2
