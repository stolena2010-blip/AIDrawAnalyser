"""
Custom exceptions for AIDrawAnalyser.

הערה: שם המחלקה `DrawingLightError` נשאר מטעמי תאימות עם import-ים ברחבי
הקוד והטסטים — זה מזהה Python פנימי, לא שם-האפליקציה שמוצג למשתמש.

היררכיית שגיאות מרוכזת עם הודעות משתמש ידידותיות בעברית,
רמות חומרה, והצעות לפתרון. מאפשרת לממשק להציג הודעות ברורות
במקום stack traces.

שימוש:
    from core.exceptions import (
        DrawingLightError, ConfigurationError, AIError, ...
        format_error_for_ui,
    )

    try:
        ...
    except DrawingLightError as exc:
        st.error(format_error_for_ui(exc))
"""
from __future__ import annotations

from typing import Literal

Severity = Literal["info", "warning", "error", "critical"]


class DrawingLightError(Exception):
    """בסיס לכל השגיאות היישומיות של AIDrawAnalyser."""

    default_user_message = "אירעה שגיאה לא צפויה."
    default_suggestion = "נסי שוב. אם הבעיה ממשיכה — פני למפתח."
    default_severity: Severity = "error"
    default_emoji = "❌"

    def __init__(
        self,
        message: str | None = None,
        *,
        user_message: str | None = None,
        suggestion: str | None = None,
        severity: Severity | None = None,
        context: dict | None = None,
    ):
        self.user_message = user_message or self.default_user_message
        self.suggestion = suggestion or self.default_suggestion
        self.severity = severity or self.default_severity
        self.context = context or {}
        super().__init__(message or self.user_message)

    @property
    def emoji(self) -> str:
        return self.default_emoji


# ─── Configuration ──────────────────────────────────────────────
class ConfigurationError(DrawingLightError):
    default_user_message = "בעיה בהגדרות המערכת."
    default_suggestion = "בדקי את קובץ .env ואת ההגדרות ב-settings.json."
    default_severity: Severity = "critical"
    default_emoji = "⚙️"


class MissingCredentialsError(ConfigurationError):
    default_user_message = "חסרים פרטי חיבור ל-Azure OpenAI."
    default_suggestion = (
        "ודאי ש-AZURE_OPENAI_ENDPOINT ו-AZURE_OPENAI_API_KEY "
        "מוגדרים בקובץ .env."
    )
    default_emoji = "🔑"


# ─── Input / Files ──────────────────────────────────────────────
class InputError(DrawingLightError):
    default_user_message = "בעיה בקובץ הקלט."
    default_suggestion = "ודאי שהקובץ קיים ותקין."
    default_emoji = "📄"


class PDFError(InputError):
    default_user_message = "לא ניתן לפתוח את קובץ ה-PDF."
    default_suggestion = (
        "ודאי שהקובץ אינו פגום, אינו מוגן בסיסמה, ושזה אכן קובץ PDF."
    )
    default_emoji = "📕"


class ImageError(InputError):
    default_user_message = "לא ניתן לפתוח את קובץ התמונה."
    default_suggestion = "ודאי שהקובץ בפורמט PNG/JPG/WEBP ואינו פגום."
    default_emoji = "🖼️"


# ─── AI / Model calls ───────────────────────────────────────────
class AIError(DrawingLightError):
    default_user_message = "שגיאה בקריאה למודל ה-AI."
    default_suggestion = "נסי שוב בעוד רגע. אם חוזר — בדקי חיבור ל-Azure."
    default_emoji = "🤖"


class ModelCallError(AIError):
    default_user_message = "הקריאה למודל נכשלה."
    default_suggestion = (
        "ייתכן שהשרת עמוס או שיש בעיית רשת. אפשר לנסות שוב "
        "או להחליף מודל בהגדרות."
    )
    default_emoji = "📡"


class InvalidResponseError(AIError):
    default_user_message = "המודל החזיר תשובה בפורמט לא תקין (JSON פגום)."
    default_suggestion = "נסי שוב — לרוב הריצה השנייה מחזירה תשובה תקינה."
    default_severity: Severity = "warning"
    default_emoji = "📝"


class EmptyResponseError(AIError):
    default_user_message = "המודל החזיר תשובה ריקה."
    default_suggestion = (
        "לרוב זה אומר שהגענו למגבלת tokens. נסי מודל אחר "
        "או שרטוט עם פחות עמודים."
    )
    default_severity: Severity = "warning"
    default_emoji = "🫙"


class AllModelsFailedError(AIError):
    default_user_message = "גם המודל הראשי וגם ה-fallback נכשלו."
    default_suggestion = (
        "בעיה בצד Azure. בדקי סטטוס שירות, "
        "ואת תקפות המפתחות ב-.env."
    )
    default_severity: Severity = "critical"
    default_emoji = "💥"


# ─── Processing pipeline ────────────────────────────────────────
class ExtractionError(DrawingLightError):
    default_user_message = "החילוץ מהשרטוט נכשל."
    default_suggestion = "נסי שוב. אם נמשך — בדקי שהשרטוט קריא."
    default_emoji = "🔧"


class StageFailedError(ExtractionError):
    default_user_message = "אחד משלבי החילוץ נכשל."
    default_suggestion = "לרוב retry פותר. בדקי את הלוג לפרטים."
    default_emoji = "⚠️"

    def __init__(self, stage: str, *args, **kwargs):
        self.stage = stage
        user_msg = kwargs.pop("user_message", None) or (
            f"שלב '{stage}' נכשל בחילוץ מהשרטוט."
        )
        ctx = kwargs.pop("context", {}) or {}
        ctx.setdefault("stage", stage)
        super().__init__(*args, user_message=user_msg, context=ctx, **kwargs)


class MasterMatchingError(ExtractionError):
    default_user_message = "התאמת המאסטרים נכשלה."
    default_suggestion = (
        "החילוץ הושלם אבל לא הצלחנו להתאים מאסטרים לציפויים. "
        "בדקי את Masters.xlsx."
    )
    default_severity: Severity = "warning"
    default_emoji = "🎯"


# ─── OCR ────────────────────────────────────────────────────────
class OCRError(DrawingLightError):
    default_user_message = "שגיאה ב-OCR."
    default_suggestion = "ניתן להמשיך בלי OCR — זה רק אופציונלי."
    default_severity: Severity = "warning"
    default_emoji = "🔍"


class OCRUnavailableError(OCRError):
    default_user_message = "Tesseract OCR אינו מותקן במערכת."
    default_suggestion = (
        "התקיני Tesseract מ-https://github.com/tesseract-ocr/tesseract "
        "או המשיכי בלי OCR."
    )


# ─── UI formatting helper ───────────────────────────────────────
_SEVERITY_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "❌",
    "critical": "🚨",
}


def format_error_for_ui(exc: Exception, *, include_technical: bool = False) -> str:
    """
    מעצב הודעת שגיאה להצגה בממשק Streamlit.

    עבור DrawingLightError - משתמש ב-user_message ו-suggestion.
    עבור שגיאה רגילה - מציג הודעה גנרית + הטקסט הטכני.

    Args:
        exc: השגיאה שנתפסה
        include_technical: האם להציג גם את הטקסט הטכני בסוף

    Returns:
        מחרוזת Markdown מעוצבת לתצוגה ב-st.error / st.warning
    """
    if isinstance(exc, DrawingLightError):
        severity_icon = _SEVERITY_EMOJI.get(exc.severity, "❌")
        lines = [
            f"{exc.emoji} **{exc.user_message}**",
            "",
            f"💡 {exc.suggestion}",
        ]
        if include_technical and str(exc) != exc.user_message:
            lines.extend(["", f"*פרטים טכניים:* `{exc}`"])
        return "\n".join(lines)

    # Fallback לשגיאה רגילה (לא מהמערכת שלנו)
    return (
        f"❌ **אירעה שגיאה לא צפויה**\n\n"
        f"💡 נסי שוב. אם חוזר — בדקי את הלוג.\n\n"
        f"*פרטים טכניים:* `{type(exc).__name__}: {exc}`"
    )


def get_streamlit_level(exc: Exception) -> str:
    """
    מחזיר את פונקציית Streamlit המתאימה: 'error' / 'warning' / 'info'.
    לשימוש:
        level = get_streamlit_level(exc)
        getattr(st, level)(format_error_for_ui(exc))
    """
    if isinstance(exc, DrawingLightError):
        if exc.severity == "info":
            return "info"
        if exc.severity == "warning":
            return "warning"
    return "error"
