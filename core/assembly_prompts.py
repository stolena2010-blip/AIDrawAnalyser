"""
Prompts ייעודיים למצב 'מכלולים מרובים' (Assembly Mode).

הפרומפטים מאוחסנים בקבצי טקסט תחת ``prompts/assembly/`` — תיקייה נפרדת
לחלוטין מ-``prompts/single/`` כדי לנהל את שני המצבים בנפרד.
הקובץ הזה רק טוען אותם וחושף את אותם שמות קבועים שהיו קיימים קודם.

שימוש:
    from core.assembly_prompts import (
        ASSEMBLY_STAGE_1_PROMPT,
        ASSEMBLY_STAGE_2_PROMPT,
        ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE,
        ASSEMBLY_OVERVIEW_IMAGE_PROMPT,
    )
"""
from __future__ import annotations

from functools import cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "assembly"


@cache
def _load(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"קובץ פרומפט חסר: {path}. ודא שתיקיית 'prompts/assembly/' קיימת."
        )
    return path.read_text(encoding="utf-8")


ASSEMBLY_STAGE_1_PROMPT = _load("stage_1.txt")
ASSEMBLY_STAGE_2_PROMPT = _load("stage_2.txt")
ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE = _load("relationships_template.txt")
ASSEMBLY_OVERVIEW_IMAGE_PROMPT = _load("overview_image.txt")
