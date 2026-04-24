"""
ניקוי טקסט — כלי post-processing לתיקון שגיאות OCR נפוצות.

דוגמה: OCR קורא שורה בלולאה וחוזר על אותו ביטוי עשרות פעמים:
    "NOM. SIZE 0.250-0.218 NOM. SIZE 0.250-0.218 NOM. SIZE 0.250-0.218 ..."
הפונקציה מזהה את החזרה ומשאירה את הביטוי רק פעם אחת.
"""
from __future__ import annotations

import re


def deduplicate_repeated_phrase(text: str, min_repeat: int = 3) -> str:
    """
    מזהה רצף של מילים שחוזר ``min_repeat`` פעמים או יותר ברצף, ומשאיר רק
    את הופעתו הראשונה. פועל באופן איטרטיבי — מתמודד עם זיהום מרובה.

    דוגמה (min_repeat=3):
        "SCREW 0.250 NOM. SIZE 0.218 NOM. SIZE 0.218 NOM. SIZE 0.218"
        → "SCREW 0.250 NOM. SIZE 0.218"

    דוגמה (phrase של מילה יחידה):
        "HEAD HEAD HEAD HEAD BOLT" → "HEAD BOLT"

    מחזיר את הטקסט ללא החזרות. אם אין חזרה → מחזיר את הטקסט כפי שהוא.
    """
    if not text or not isinstance(text, str):
        return text or ""

    words = text.split()
    n = len(words)
    if n < min_repeat * 1:
        return text

    # לנסות אורכי phrase מהארוך לקצר (מעדיפים למצוא חזרה של phrase ארוך)
    max_phrase_len = max(1, n // min_repeat)
    changed = False
    for phrase_len in range(max_phrase_len, 0, -1):
        start = 0
        while start <= n - phrase_len * min_repeat:
            phrase = words[start:start + phrase_len]
            repeats = 1
            pos = start + phrase_len
            while pos + phrase_len <= n and words[pos:pos + phrase_len] == phrase:
                repeats += 1
                pos += phrase_len
            if repeats >= min_repeat:
                # השאר את הופעת ה-phrase הראשונה, דלג על החזרות
                words = words[:start + phrase_len] + words[pos:]
                n = len(words)
                changed = True
                # המשך מאותה נקודה אחרי השארית
                start = start + phrase_len
            else:
                start += 1
        if changed:
            break

    if changed:
        # ייתכנו עוד דפוסי זיהום — קרא רקורסיבית עד הקונוורגנציה
        cleaned = " ".join(words)
        return deduplicate_repeated_phrase(cleaned, min_repeat)

    return text


_MULTI_SPACE_RE = re.compile(r"\s+")


def clean_bom_description(text: str) -> str:
    """
    מנקה תיאור פריט BOM:
    - מסיר חזרות של phrase שהוכנסו בטעות ע"י OCR.
    - מנרמל רווחים מרובים.
    - חותך רווחים בקצוות.
    """
    if not text or not isinstance(text, str):
        return text or ""
    cleaned = deduplicate_repeated_phrase(text, min_repeat=3)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


# ───────────────────────────────────────────────────────────────
# נרמול ביטויים ידועים שנקראים בטעות ע"י OCR
# ───────────────────────────────────────────────────────────────
# כל פריט: (regex, replacement, description)
_KNOWN_PHRASE_NORMALIZATIONS: list[tuple[re.Pattern, str, str]] = [
    # Z0 SQUEGLIA — שיטת דגימה סטטיסטית נפוצה ב-RAFAEL
    # Compound OCR misread: "ZQSQLAND NQE" = "Z0 SQUEGLIA INDEX"
    (re.compile(r"\bZQSQLAND\s+NQE\b", re.IGNORECASE),
     "Z0 SQUEGLIA INDEX", "ZQSQLAND NQE→Z0 SQUEGLIA INDEX"),
    (re.compile(r"\bZQSQLAND\b", re.IGNORECASE),
     "Z0 SQUEGLIA", "ZQSQLAND→Z0 SQUEGLIA"),
    # "Z0/ZO/ZQ SQUEGLIA" ווריאציות (Z0 נקרא כ-ZO או ZQ)
    (re.compile(r"\bZ[OQ]\s+SQUEG?L?I?A\b", re.IGNORECASE),
     "Z0 SQUEGLIA", "ZO/ZQ SQUEGLIA→Z0 SQUEGLIA"),
    # SQUEGLIA ללא Z0 — תיקוני OCR על השם עצמו (וריאציות נפוצות)
    (re.compile(
        r"\b(?:SUGELIA|SUQEILA|SUQGLIA|SUGEILA|SUEGLIA|SQUEGLA|SUQELIA)\b",
        re.IGNORECASE,
    ), "SQUEGLIA", "SUGELIA/SUQEILA→SQUEGLIA"),
    # NQE → INDEX (רק בהקשר של "NQE VALUE")
    (re.compile(r"\bNQE\s+VALUE\b", re.IGNORECASE),
     "INDEX VALUE", "NQE VALUE→INDEX VALUE"),

    # SAE-AMS-C-26074 — תקן ציפוי ניקל אלקטרולס נפוץ
    (re.compile(r"\bV?[Z2][S5]\.?4?\s+AMS-?C-?26074\b", re.IGNORECASE),
     "SAE-AMS-C-26074", "V25.4→SAE-AMS-C-26074"),

    # "TO-PS-DOC..." / "TO-SM-..." / "TO-RAFDOCS-..." — OCR שקרא "ACC. TO:"
    # כחלק מהמספר. ה-TO- מוסר; שאר המספר נשאר כפי שהוא (גם אם יש חוסר ספרה,
    # לא נתקן כאן כי זה דורש OCR טוב יותר ברמת התמונה).
    (re.compile(r"\bTO[-\s]+(PS-DOC)", re.IGNORECASE),
     r"\1", "TO-PS-DOC→PS-DOC"),
    (re.compile(r"\bTO[-\s]+(PS-?111)", re.IGNORECASE),
     r"\1", "TO-PS-111→PS-111"),
    (re.compile(r"\bTO[-\s]+(SM-?111)", re.IGNORECASE),
     r"\1", "TO-SM-111→SM-111"),
    (re.compile(r"\bTO[-\s]+(RAFDOCS)", re.IGNORECASE),
     r"\1", "TO-RAFDOCS→RAFDOCS"),
]


def normalize_known_phrases(text: str) -> tuple[str, list[str]]:
    """
    מנרמל ביטויים מוכרים שנקראו בטעות ע"י OCR.
    מחזיר (טקסט-מנורמל, רשימת תיקונים שבוצעו).
    """
    if not text or not isinstance(text, str):
        return text or "", []
    corrections: list[str] = []
    out = text
    for pattern, replacement, desc in _KNOWN_PHRASE_NORMALIZATIONS:
        new_out, count = pattern.subn(replacement, out)
        if count > 0:
            corrections.append(f"{desc} ×{count}")
            out = new_out
    return out, corrections


def _walk_and_normalize(obj, corrections: list[str]) -> object:
    """רוקורסיבי: עובר על dict/list ומנרמל כל מחרוזת."""
    if isinstance(obj, str):
        new, c = normalize_known_phrases(obj)
        corrections.extend(c)
        return new
    if isinstance(obj, dict):
        return {k: _walk_and_normalize(v, corrections) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_normalize(v, corrections) for v in obj]
    return obj


def normalize_known_phrases_in_place(result: dict) -> list[str]:
    """
    עובר רקורסיבית על כל המחרוזות במבנה הניתוח ומנרמל ביטויים ידועים.
    מדלג על מפתחות פנימיים (מתחילים ב-"_"). מחזיר רשימת תיקונים.
    """
    if not isinstance(result, dict):
        return []
    corrections: list[str] = []
    for k, v in list(result.items()):
        if isinstance(k, str) and k.startswith("_"):
            continue
        result[k] = _walk_and_normalize(v, corrections)
    # dedup + limit
    seen: set[str] = set()
    unique: list[str] = []
    for c in corrections:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def clean_bom_items_in_place(bom_items: list) -> int:
    """
    מנקה את כל התיאורים של פריטי BOM ב-list in-place.
    מחזיר את מספר הפריטים שתוקנו (description השתנתה).
    """
    if not bom_items:
        return 0
    fixed = 0
    for it in bom_items:
        if not isinstance(it, dict):
            continue
        raw = it.get("description") or ""
        cleaned = clean_bom_description(raw)
        if cleaned != raw:
            it["description"] = cleaned
            fixed += 1
    return fixed
