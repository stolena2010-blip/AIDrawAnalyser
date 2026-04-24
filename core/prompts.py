"""
Prompts עבור שלבי החילוץ (מצב שרטוט בודד).

הפרומפטים מאוחסנים בקבצי טקסט תחת ``prompts/single/`` כדי לאפשר עריכה
ללא נגיעה בקוד. הקובץ הזה רק טוען אותם וחושף את אותם שמות קבועים שהיו
קיימים קודם, כך שאף קוד צרכן לא צריך להשתנות.

שימוש:
    from core.prompts import STAGE_1_PROMPT, STAGE_2_PROMPT, STAGE_3_PROMPT_TEMPLATE
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "single"


@lru_cache(maxsize=None)
def _load(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"קובץ פרומפט חסר: {path}. ודא שתיקיית 'prompts/single/' קיימת."
        )
    return path.read_text(encoding="utf-8")


STAGE_1_PROMPT = _load("stage_1.txt")
STAGE_2_PROMPT = _load("stage_2.txt")
STAGE_3_PROMPT_TEMPLATE = _load("stage_3_template.txt")
