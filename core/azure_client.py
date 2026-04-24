"""
Azure OpenAI client wrapper — תומך ב-gpt-4o-vision (פשוט) וב-gpt-5.4 (reasoning).

מקורות לבחירת המודל הפעיל (לפי סדר עדיפות):
  1. הגדרות runtime — קובץ output/_runtime_settings.json (נכתב מתפריט ההגדרות ב-UI).
  2. משתנה הסביבה ACTIVE_MODEL מתוך .env.

יש גם תמיכה ב-Fallback: אם הקריאה למודל הראשי נכשלה והמשתמש הפעיל
את המתג, הקוד ינסה אוטומטית את המודל השני.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from openai import AzureOpenAI, OpenAI
from dotenv import load_dotenv

from core.exceptions import MissingCredentialsError

load_dotenv()

# מזהי מודלים נתמכים
MODEL_GPT_4O = "gpt-4o-vision"
MODEL_GPT_5_4 = "gpt-5.4"
SUPPORTED_MODELS = (MODEL_GPT_4O, MODEL_GPT_5_4)

_RUNTIME_FILE = Path("output/_runtime_settings.json")


# ─── הגדרות runtime (נכתבות ע"י תפריט ההגדרות ב-UI) ───
def _load_runtime_settings() -> dict:
    if not _RUNTIME_FILE.exists():
        return {}
    try:
        return json.loads(_RUNTIME_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_runtime_settings(active_model: str | None = None,
                           fallback_enabled: bool | None = None,
                           enabled_modes: list[str] | tuple[str, ...] | None = None,
                           masters_xlsx_path: str | None = None) -> None:
    """שומר העדפות מודל בקובץ runtime (לא נוגע ב-.env)."""
    cur = _load_runtime_settings()
    if active_model is not None:
        cur["active_model"] = active_model
    if fallback_enabled is not None:
        cur["fallback_enabled"] = bool(fallback_enabled)
    if enabled_modes is not None:
        valid = {"single", "assembly"}
        normalized = [m for m in dict.fromkeys(enabled_modes) if m in valid]
        if not normalized:
            normalized = ["single", "assembly"]
        cur["enabled_modes"] = normalized
    if masters_xlsx_path is not None:
        cleaned_path = masters_xlsx_path.strip() if isinstance(masters_xlsx_path, str) else ""
        cur["masters_xlsx_path"] = cleaned_path
        # עדכן גם את משתנה הסביבה הנוכחי כדי שהוא יהיה זמין מיד
        if cleaned_path:
            os.environ["MASTERS_XLSX_PATH"] = cleaned_path
        elif "MASTERS_XLSX_PATH" in os.environ:
            del os.environ["MASTERS_XLSX_PATH"]
    _RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_FILE.write_text(
        json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _active_model() -> str:
    rt = _load_runtime_settings()
    if rt.get("active_model"):
        return str(rt["active_model"]).strip()
    return os.getenv("ACTIVE_MODEL", MODEL_GPT_4O).strip()


def is_fallback_enabled() -> bool:
    """האם להפעיל אוטומטית את המודל השני אם הראשי נכשל."""
    rt = _load_runtime_settings()
    if "fallback_enabled" in rt:
        return bool(rt["fallback_enabled"])
    return os.getenv("MODEL_FALLBACK_ENABLED", "true").lower() == "true"


def enabled_modes() -> list[str]:
    """מחזיר רשימת מצבי עבודה מורשים להצגה ב-UI."""
    rt = _load_runtime_settings()
    if rt.get("enabled_modes"):
        valid = {"single", "assembly"}
        modes = [m for m in rt["enabled_modes"] if m in valid]
        if modes:
            return modes

    env_val = os.getenv("ENABLED_MODES", "").strip()
    if env_val:
        modes = [
            m.strip() for m in env_val.split(",")
            if m.strip() in {"single", "assembly"}
        ]
        if modes:
            return modes

    return ["single", "assembly"]


def get_masters_xlsx_path() -> str:
    """מחזיר נתיב ל-Masters.xlsx (מ-runtime או מ-.env)."""
    rt = _load_runtime_settings()
    if rt.get("masters_xlsx_path"):
        return str(rt["masters_xlsx_path"]).strip()
    
    env_val = os.getenv("MASTERS_XLSX_PATH", "").strip()
    if env_val:
        return env_val
    
    # ברירת מחדל
    return ""


# ─── זיהוי סוג המודל ───
def _is_gpt54(model: str) -> bool:
    m = (model or "").lower()
    return "5.4" in m or m == "gpt-5.4"


def is_reasoning_model(model: str | None = None) -> bool:
    """האם המודל הפעיל הוא reasoning (gpt-5.x / o-series)."""
    model = model or _active_model()
    if _is_gpt54(model):
        return os.getenv("MODEL_GPT_5_4_IS_REASONING", "true").lower() == "true"
    m = model.lower()
    return m.startswith("o1") or m.startswith("o3") or m.startswith("o4") or "gpt-5" in m


# ─── יצירת clients ───
def _build_client_gpt54():
    endpoint = os.getenv("MODEL_GPT_5_4_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("MODEL_GPT_5_4_API_KEY")
    api_version = os.getenv("MODEL_GPT_5_4_API_VERSION", "2024-12-11-preview")
    if not endpoint or not api_key:
        raise MissingCredentialsError(
            "GPT-5.4 credentials missing",
            user_message="חסרים פרטי חיבור ל-GPT-5.4.",
            suggestion=(
                "ודאי ש-MODEL_GPT_5_4_ENDPOINT ו-MODEL_GPT_5_4_API_KEY "
                "מוגדרים בקובץ .env."
            ),
        )
    return OpenAI(
        base_url=f"{endpoint}/openai/v1/",
        api_key=api_key,
        default_query={"api-version": api_version},
    )


def _build_client_gpt4o():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    if not endpoint or not api_key:
        raise MissingCredentialsError(
            "GPT-4o credentials missing",
            user_message="חסרים פרטי חיבור ל-Azure OpenAI (GPT-4o).",
            suggestion=(
                "ודאי ש-AZURE_OPENAI_ENDPOINT ו-AZURE_OPENAI_API_KEY "
                "מוגדרים בקובץ .env."
            ),
        )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )


def get_client(model: str | None = None):
    """מחזיר client של המודל הפעיל (או של המודל המבוקש)."""
    model = model or _active_model()
    if _is_gpt54(model):
        return _build_client_gpt54()
    return _build_client_gpt4o()


def get_deployment(model: str | None = None) -> str:
    """מחזיר את שם ה-deployment של המודל הפעיל (או המבוקש)."""
    model = model or _active_model()
    if _is_gpt54(model):
        return os.getenv("MODEL_GPT_5_4_DEPLOYMENT", "gpt-5.4")
    return os.getenv(
        "AZURE_DEPLOYMENT_NAME",
        os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
    )


def get_fallback_model() -> str | None:
    """מחזיר את המודל השני (אם הפעיל gpt-5.4 → gpt-4o-vision ולהפך)."""
    primary = _active_model()
    if _is_gpt54(primary):
        return MODEL_GPT_4O
    return MODEL_GPT_5_4


def get_fallback_client_and_deployment():
    """מחזיר (client, deployment, model_id) של מודל ה-fallback, או (None, None, None)."""
    if not is_fallback_enabled():
        return None, None, None
    fb = get_fallback_model()
    if not fb:
        return None, None, None
    try:
        return get_client(fb), get_deployment(fb), fb
    except Exception:
        return None, None, None
