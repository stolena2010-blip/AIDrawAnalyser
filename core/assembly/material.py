"""
חילוץ MATERIAL מטקסט OCR — fallback לחילוץ ויז'ואלי שנכשל.

שתי שיטות:
    _extract_material_from_text — מחפש שדה 'MATERIAL' מסומן ב-title block
    _extract_material_direct    — חיפוש ישיר של ביטויי חומר בכל הטקסט (חזק יותר)

שתיהן מחזירות "" אם לא נמצא, אחרת מחרוזת חתוכה ל-200 תווים.
"""
from __future__ import annotations

import re

_MATERIAL_NOISE_PHRASES = (
    "OTHER SIZE",
    "SIMILAR MATERIAL",
    "RAW MATERIAL IDENTIFICATION",
    "SAME MATERIAL",
    "MATERIAL AND THERMAL",
    "MATERIAL ACC",
    "MATERIAL IS OPTIONAL",
)


def _extract_material_from_text(text: str) -> str:
    """חיפוש שדה MATERIAL בטקסט OCR. מחזיר ערך נקי או "" אם לא נמצא ברור.

    מחפש את התבנית "MATERIAL <ערך>" או שדה ייעודי, ומסנן הערות/disclaimers.
    """
    if not text:
        return ""

    # פיצול לשורות
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # נסה לחפש בלוק MATERIAL <ערך בשורה הבאה>
    for i, line in enumerate(lines):
        upper = line.upper()
        # התעלם משורות שהן הערות/disclaimers
        if any(noise in upper for noise in _MATERIAL_NOISE_PHRASES):
            continue
        # שורה שמורכבת מהמילה MATERIAL בלבד (label של title block)
        if upper in ("MATERIAL", "MATERIAL:", "MATL", "MATL:", "MAT'L", "MAT'L:"):
            # נסה לקחת את 1-3 השורות הבאות
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                cu = candidate.upper()
                if any(noise in cu for noise in _MATERIAL_NOISE_PHRASES):
                    continue
                # פסיכת תוויות לא רלוונטיות
                if cu in ("MATERIAL", "MATL", "QTY", "DATE", "REV", "SIZE",
                          "SCALE", "SHEET", "TITLE", "DRAWING", "DWG"):
                    continue
                # חייב להכיל לפחות אות אחת ומעל 4 תווים
                if len(candidate) < 4 or not any(c.isalpha() for c in candidate):
                    continue
                # סינון: צריך להראות כמו חומר (אלומיניום/פלדה/וכו')
                if _looks_like_material(candidate):
                    return candidate[:200]
            continue

        # תבנית בשורה אחת: "MATERIAL: <ערך>" או "MATL <ערך>"
        m = re.match(r"^\s*(?:MATERIAL|MATL|MAT'L)\s*[:\-]?\s*(.+)$", line, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            cu = candidate.upper()
            if any(noise in cu for noise in _MATERIAL_NOISE_PHRASES):
                continue
            if _looks_like_material(candidate):
                return candidate[:200]

    return ""


_MATERIAL_KEYWORDS = (
    "ALUMIN", "ALLOY", "STEEL", "STAINLESS", "BRASS", "BRONZE",
    "TITANIUM", "COPPER", "PLATE", "BAR", "ROD", "TUBE", "SHEET",
    "AL ", "SS ", "CRES", "INCONEL", "MONEL", "PLASTIC", "NYLON",
    "DELRIN", "PEEK", "ABS ", "POLYCARBONATE", "POM", "PTFE",
    "6061", "7075", "2024", "5052", "303", "304", "316", "321",
    "17-4", "17-7", "15-5", "C36", "Ti-6", "PEEK",
)


def _looks_like_material(text: str) -> bool:
    """heuristic: האם המחרוזת נראית כמו חומר גלם תקין."""
    if not text:
        return False
    upper = text.upper()
    return any(kw in upper for kw in _MATERIAL_KEYWORDS)


# ביטויי הוראה שאינם חומר אמיתי — תופס מקרים כמו
# "USE EXTRUSION MCM-MC-08028-01." שהמודל מחזיר כשאין שדה material נפרד.
_MATERIAL_INSTRUCTION_PREFIXES = (
    "USE ", "PER ", "ACC ", "ACC. ", "ACCORDING ", "AS PER ",
    "SEE ", "REFER TO ", "REFERENCE ", "AS REQUIRED",
)


def is_material_instruction_only(text: str) -> bool:
    """
    מזהה האם הטקסט הוא הוראה (USE X / PER X / SEE X) ולא שם חומר אמיתי.
    דורש (1) להתחיל באחת הקידומות ו-(2) שלא להכיל מילת חומר ידועה.
    משמש לסינון תוכן שגוי שהמודל מחזיר בשדה material.
    """
    if not text:
        return False
    stripped = text.strip()
    upper = stripped.upper()
    if not any(upper.startswith(prefix) for prefix in _MATERIAL_INSTRUCTION_PREFIXES):
        return False
    # יש קידומת — אבל אם יש מילת חומר אמיתית במחרוזת ("USE STAINLESS STEEL 304"),
    # זו הוראה לגיטימית עם חומר.
    return not _looks_like_material(stripped)


# Regex patterns לחיפוש **ישיר** של ביטויי חומר בטקסט (fallback אחרון).
# משמש כאשר אין שדה "MATERIAL" מסומן בבירור — מחפש את החומר בכל הטקסט.
_MATERIAL_DIRECT_PATTERNS = [
    # אלומיניום: "ALUMINUM ALLOY 6061-T651", "AL. AL. 5052-H32", "AL 7075-T6"
    re.compile(
        r"\b(?:ALUMIN[IU]M(?:\s+ALLOY)?|AL\.?\s*AL\.?|AL)\s+"
        r"[0-9]{4}(?:[-\s][A-Z0-9]+)?(?:[-\s][A-Z][0-9]*)?"
        r"(?:[\s,\w\-\.]{0,120}?(?:PER|ACC\.?\s*TO|IAW|SPEC)\s+[A-Z0-9\-\./]+)?",
        re.IGNORECASE,
    ),
    # פלדה: "STAINLESS STEEL 303", "LOW CARBON STEEL SAE 1020", "STEEL 4140"
    re.compile(
        r"\b(?:STAINLESS\s+STEEL|LOW\s+CARBON\s+STEEL|STEEL)\s+"
        r"(?:SAE\s+)?[0-9]{2,4}[A-Z0-9\-/]*"
        r"(?:[\s,\w\-\.]{0,120}?(?:PER|ACC\.?\s*TO|IAW|SPEC)\s+[A-Z0-9\-\./]+)?",
        re.IGNORECASE,
    ),
    # PH steel: "STAINLESS STEEL 15-5PH" / "17-4PH"
    re.compile(
        r"\bSTAINLESS\s+STEEL\s+\d{2}-\dPH\b(?:[\s,\w\-\.]{0,100})?",
        re.IGNORECASE,
    ),
    # טיטניום: "TITANIUM Ti-6AL-4V"
    re.compile(
        r"\bTITANIUM\s+Ti-\d[A-Z]+-\d[A-Z]+(?:[\s,\w\-\.]{0,80})?",
        re.IGNORECASE,
    ),
    # פלסטיקים: "PVC PLATE THICK", "DELRIN", "PEEK"
    re.compile(
        r"\b(?:PVC|DELRIN|PEEK|NYLON|ABS|POLYCARBONATE|PTFE|POM)"
        r"(?:\s+(?:PLATE|ROD|BAR|SHEET|TUBE))?"
        r"(?:\s+THICK\.?\s*[\d\.]+\s*(?:MM|IN)?)?"
        r"(?:[\s,\w\-\.]{0,100}?(?:PER|ACC\.?\s*TO|IAW)\s+[A-Z0-9\-\./!]+)?",
        re.IGNORECASE,
    ),
]


def _extract_material_direct(text: str) -> str:
    """
    fallback חזק יותר — חיפוש ישיר של ביטויי חומר בטקסט **בלי** שדה 'MATERIAL'
    מסומן. משמש כשהשיטה הראשית (_extract_material_from_text) מחזירה "".
    """
    if not text:
        return ""
    for pat in _MATERIAL_DIRECT_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(0).strip()
            # ניקוי: הסר רווחים כפולים, חתוך ב-200 תווים
            candidate = re.sub(r"\s+", " ", candidate)
            if 6 < len(candidate) < 250 and _looks_like_material(candidate):
                return candidate[:200]
    return ""
