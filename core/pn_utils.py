"""
Helpers לחילוץ ותיקון Part Number (P.N.) משרטוטי רפאל וספקים אחרים.

שני המסלולים (single + assembly) משתפים את אותם עזרי התאמה/תיקון
כדי למנוע כפילות קוד ולוגיקה סותרת.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────
# חילוץ P/N משם הקובץ
# ───────────────────────────────────────────────────────────────
_KNOWN_PN_PREFIXES = (
    "PWRL", "BBLE", "HLTA", "FTLS", "FTL", "MMA",  # RAFAEL
    "BG", "BN", "BO", "BP", "BB", "RF",            # RAFAEL קצרים / B2B
    "IAI",                                           # Israel Aerospace
    "EL",                                            # Elbit
)

_PN_BLACKLIST = {
    "CAGE", "DWG", "DRAW", "DATE", "NOTES", "QTY", "SIZE",
    "REV", "SHEET", "SCALE", "TOLERANCE", "FINISH",
}

_PN_PATTERN = re.compile(r"\b([A-Z]{2,4}[A-Z0-9]{0,3}\d{2,}[A-Z0-9]*)\b")


def extract_pn_from_filename(filename: str) -> str:
    """מנסה למצוא מספר פריט בשם הקובץ (זהיר — מסנן blacklist + עדיפות whitelist)."""
    if not filename:
        return ""
    stem = Path(filename).stem.upper()
    for prefix in ("B2BDRAW_", "DRAW_", "TEMP_", "_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    segments = re.split(r"[-_()\s]+", stem)
    candidates: list[str] = []
    for seg in segments:
        for m in _PN_PATTERN.findall(seg):
            if not (5 <= len(m) <= 15):
                continue
            if m.isdigit() or not any(c.isalpha() for c in m):
                continue
            if any(bl in m for bl in _PN_BLACKLIST):
                continue
            candidates.append(m)
    if not candidates:
        return ""
    for c in candidates:
        if c.startswith(_KNOWN_PN_PREFIXES):
            return c
    longest = max(candidates, key=len)
    return longest if len(longest) >= 6 else ""


# ───────────────────────────────────────────────────────────────
# זיהוי ותיקון OCR confusion באותיות/ספרות דומות
# ───────────────────────────────────────────────────────────────
# זוגות שנקראים בטעות (amt אחד דו-כיוונית).
_OCR_CONFUSION_PAIRS = {
    ("B", "8"), ("8", "B"),
    ("O", "0"), ("0", "O"),
    ("I", "1"), ("1", "I"),
    ("S", "5"), ("5", "S"),
    ("Z", "2"), ("2", "Z"),
    ("G", "6"), ("6", "G"),
    ("T", "7"), ("7", "T"),
    ("D", "0"), ("0", "D"),
    ("Q", "0"), ("0", "Q"),
    ("L", "1"), ("1", "L"),
}


def ocr_confusion_distance(a: str, b: str) -> int:
    """
    מחזיר כמה תווים שונים בין ``a`` ל-``b``, אך רק אם כל ההבדלים הם מזוגות
    OCR-confusion ידועים. אחרת 99 (לא ניתן לתקן).
    אורכים שונים → 99.
    """
    if not a or not b or len(a) != len(b):
        return 99
    diffs = 0
    for ca, cb in zip(a.upper(), b.upper()):
        if ca == cb:
            continue
        if (ca, cb) in _OCR_CONFUSION_PAIRS:
            diffs += 1
        else:
            return 99
    return diffs


def transposition_distance(a: str, b: str) -> int:
    """
    מחזיר 1 אם ``a`` ו-``b`` נבדלים בהחלפת שני תווים **סמוכים** בודדת
    (למשל "BBJ1" ↔ "BB1J"). אחרת 99.
    """
    if not a or not b or len(a) != len(b):
        return 99
    au, bu = a.upper(), b.upper()
    if au == bu:
        return 0
    diffs = [i for i, (ca, cb) in enumerate(zip(au, bu)) if ca != cb]
    if len(diffs) != 2:
        return 99
    i, j = diffs
    if j != i + 1:
        return 99
    if au[i] == bu[j] and au[j] == bu[i]:
        return 1
    return 99


def insertion_deletion_distance(a: str, b: str) -> int:
    """
    מחזיר 1 אם ``a`` ו-``b`` נבדלים בתו יחיד שנמחק/נוסף (שגיאת OCR של
    "ספרה נעלמה" או "ספרה מיותרת"). דורש הפרש אורך של 1 בדיוק.
    אחרת 99.

    דוגמה: "BP7053A" ↔ "BP70534A" (חסר ספרה 4) → 1.
    """
    if not a or not b:
        return 99
    au, bu = a.upper(), b.upper()
    if abs(len(au) - len(bu)) != 1:
        return 99
    longer, shorter = (au, bu) if len(au) > len(bu) else (bu, au)
    i = j = 0
    diffs = 0
    while i < len(longer) and j < len(shorter):
        if longer[i] == shorter[j]:
            i += 1
            j += 1
        else:
            i += 1
            diffs += 1
            if diffs > 1:
                return 99
    remaining = (len(longer) - i) + (len(shorter) - j)
    return 1 if diffs + remaining == 1 else 99


def combined_pn_distance(a: str, b: str) -> int:
    """
    המרחק הקטן מבין שלוש תבניות שגיאת OCR נפוצות:
    1. החלפת תווים דומים (B↔8, O↔0, I↔1, S↔5, Z↔2, G↔6).
    2. החלפת סדר בין שני תווים סמוכים (BBJ1 ↔ BB1J).
    3. ספרה/אות בודדת שנעלמה או התווספה (BP7053A ↔ BP70534A).
    ערך גבוה אם אף תבנית לא מתאימה (הבדל אמיתי, לא שגיאת קריאה).
    """
    return min(
        ocr_confusion_distance(a, b),
        transposition_distance(a, b),
        insertion_deletion_distance(a, b),
    )


def correct_pn_with_filename(extracted_pn: str, filename: str) -> tuple[str, bool]:
    """
    אם שם הקובץ מכיל מועמד ל-P/N שנבדל מהערך שחולץ רק ב-OCR-confusion
    (B↔8, O↔0 וכו') בעד 2 תווים — החזר את גרסת שם הקובץ.

    מחזיר: (corrected_pn, was_corrected)
    """
    if not extracted_pn:
        return extracted_pn, False
    fname_pn = extract_pn_from_filename(filename)
    if not fname_pn or fname_pn == extracted_pn.upper():
        return extracted_pn, False
    dist = combined_pn_distance(extracted_pn, fname_pn)
    if 1 <= dist <= 2:
        return fname_pn, True
    return extracted_pn, False


# ───────────────────────────────────────────────────────────────
# נרמול סיומת אות חסרה (BB1J0219 ↔ BB1J0219A)
# ───────────────────────────────────────────────────────────────
def normalize_dwg_vs_pn(stage1: dict) -> tuple[bool, str]:
    """
    ברוב שרטוטי ה-PART של רפאל, ``part_number`` ו-``drawing_number`` זהים.
    אם הם נבדלים **בתו יחיד שהוא OCR-confusion ידוע** (למשל 7↔T: ``BP70534A``
    ↔ ``BPT0534A``) — זו כמעט בוודאות שגיאת קריאה באחד מהם.

    כללים:
    - אם אחד מהם מתחיל באות ואז 2+ ספרות ברצף, והשני באות ואז אות — הצורה
      עם הספרות היא כמעט בוודאות הנכונה (T בתחילת ``BPT0534A`` חשודה).
    - אחרת, העדף את ה-``part_number`` (מזהה ראשי).

    מחזיר (was_normalized, canonical_value).
    """
    pn = (stage1.get("part_number") or "").strip()
    dn = (stage1.get("drawing_number") or "").strip()
    if not pn or not dn or pn == dn:
        return False, pn or dn
    if combined_pn_distance(pn, dn) != 1:
        return False, pn

    def _digit_body_score(s: str) -> int:
        """ספירת ספרות רצופות אחרי קידומת של 2 אותיות (מבנה רפאל תקין)."""
        if len(s) < 3 or not s[0].isalpha() or not s[1].isalpha():
            return 0
        count = 0
        for ch in s[2:]:
            if ch.isdigit():
                count += 1
            else:
                break
        return count

    pn_score = _digit_body_score(pn)
    dn_score = _digit_body_score(dn)
    if dn_score > pn_score:
        stage1["part_number"] = dn
        return True, dn
    if pn_score > dn_score:
        stage1["drawing_number"] = pn
        return True, pn
    # שוויון — העדף את ה-PN
    stage1["drawing_number"] = pn
    return True, pn


def normalize_trailing_letter(stage1: dict) -> bool:
    """
    אם ``part_number`` שווה ל-``drawing_number`` מלבד סיומת אות אחת (A, B, C...) —
    השלם לצורה הארוכה יותר. מחזיר True אם בוצע נרמול.

    דוגמה: pn="BB1J0219", dwg="BB1J0219A" → pn="BB1J0219A".
    """
    pn = (stage1.get("part_number") or "").strip()
    dn = (stage1.get("drawing_number") or "").strip()
    if not pn or not dn or pn == dn:
        return False
    pu, du = pn.upper(), dn.upper()
    # אחד מהם סיומת-אות של השני
    if du == pu + du[-1] and du[-1].isalpha():
        stage1["part_number"] = dn
        return True
    if pu == du + pu[-1] and pu[-1].isalpha():
        stage1["drawing_number"] = pn
        return True
    return False


# ───────────────────────────────────────────────────────────────
# Cross-reference של P/N מול BOM של כל השרטוטים
# ───────────────────────────────────────────────────────────────
def collect_bom_part_numbers(drawings: list[dict]) -> set[str]:
    """אוסף את כל ה-P/Ns מתוך BOM של כל השרטוטים (UPPERCASE)."""
    pns: set[str] = set()
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        for it in d.get("bom_items") or []:
            if isinstance(it, dict):
                p = (it.get("part_number") or "").strip().upper()
                if p:
                    pns.add(p)
    return pns


def cross_reference_part_numbers(drawings: list[dict]) -> list[str]:
    """
    מצליב P/N של כל שרטוט מול ה-BOM של כל שאר השרטוטים. אם P/N של שרטוט
    לא מופיע בשום BOM אבל קיים מועמד קרוב (OCR-confusion או החלפת סמוכים,
    מרחק ≤ 2) — מתקן את השרטוט.

    מחזיר רשימת הודעות תיקון (לצורכי לוג / אזהרות).
    """
    bom_pns = collect_bom_part_numbers(drawings)
    if not bom_pns:
        return []
    corrections: list[str] = []
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        pn = (d.get("part_number") or "").strip()
        if not pn or pn.upper() in bom_pns:
            continue
        # לא כל שרטוט חייב להופיע ב-BOM (שורש למשל). נתקן רק אם קיים מועמד קרוב.
        best = None
        best_dist = 99
        for bpn in bom_pns:
            dist = combined_pn_distance(pn, bpn)
            if dist < best_dist:
                best_dist = dist
                best = bpn
        if best and 1 <= best_dist <= 2:
            old_pn = pn
            d["part_number"] = best
            dn = (d.get("drawing_number") or "").strip()
            if dn.upper() == old_pn.upper():
                d["drawing_number"] = best
            msg = f"🔧 BOM cross-ref: {old_pn} → {best} (distance={best_dist})"
            logger.info(msg)
            corrections.append(msg)
    return corrections


# ───────────────────────────────────────────────────────────────
# Reconcile — משלים/מתקן part_number משם הקובץ או drawing_number
# ───────────────────────────────────────────────────────────────
def reconcile_part_number(stage1: dict, filename: str) -> None:
    """
    משלים part_number כש-Stage 1 לא הצליח לחלץ, או מתקן שגיאות OCR לפי שם הקובץ.

    כללים (לפי סדר):
    1. אם יש part_number, אבל הוא שונה ממועמד בשם הקובץ רק ב-OCR-confusion
       (B↔8, O↔0, I↔1, S↔5, Z↔2, G↔6) — העדף את גרסת שם הקובץ. זה מתקן טעויות
       נפוצות כמו "BNB0760B" → "BN80760B" (ה-B המרכזי הוא 8).
       במקרה כזה נתקן גם את drawing_number אם הוא זהה ל-part_number הישן.
    2. אם part_number ריק אבל drawing_number קיים → השתמש ב-drawing_number
       (נפוץ ברפאל — אותו ערך מופיע ב-P.N. וב-DRAWING NO.).
    3. אחרת, אם שם הקובץ מכיל מועמד סביר — השתמש בו.
    """
    pn = (stage1.get("part_number") or "").strip()
    if pn:
        corrected, was_corrected = correct_pn_with_filename(pn, filename)
        if was_corrected:
            logger.info(
                "🔧 part_number תוקן לפי שם הקובץ (OCR confusion): %s → %s",
                pn, corrected,
            )
            stage1["part_number"] = corrected
            dn = (stage1.get("drawing_number") or "").strip()
            if dn == pn:
                stage1["drawing_number"] = corrected
        if normalize_trailing_letter(stage1):
            logger.info(
                "🔧 part_number / drawing_number סוננו לסיומת-אות תואמת: %s / %s",
                stage1.get("part_number"), stage1.get("drawing_number"),
            )
        was_norm, canonical = normalize_dwg_vs_pn(stage1)
        if was_norm:
            logger.info(
                "🔧 part_number / drawing_number אוחדו (OCR confusion): %s / %s → %s",
                pn, stage1.get("drawing_number") or stage1.get("part_number"), canonical,
            )
        return

    dn = (stage1.get("drawing_number") or "").strip()
    if dn:
        stage1["part_number"] = dn
        logger.info("📝 part_number הושלם מ-drawing_number: %s", dn)
        return

    fname_pn = extract_pn_from_filename(filename)
    if fname_pn:
        stage1["part_number"] = fname_pn
        logger.info("📝 part_number הושלם משם הקובץ: %s", fname_pn)


# ───────────────────────────────────────────────────────────────
# Drawing-number fallback: אם DWG ריק אבל P/N קיים → DWG = P/N
# מקובל בלקוחות בינוניים/קטנים (Mechanico-Shaftech, Elbit במקרים רבים)
# שבהם אין שדה DWG נפרד וה-P/N משמש גם כ-drawing_number.
# ───────────────────────────────────────────────────────────────
_EMPTY_MARKERS = {"", "-", "—", "N/A", "NA", "NONE", "NULL"}


def _is_empty_marker(val: str) -> bool:
    return (val or "").strip().upper() in _EMPTY_MARKERS


def reconcile_drawing_number(stage1: dict) -> bool:
    """
    אם ``drawing_number`` ריק/סמן-ריק אבל ``part_number`` קיים —
    השתמש ב-``part_number``. מחזיר True אם בוצעה השלמה.
    """
    pn = (stage1.get("part_number") or "").strip()
    dn = (stage1.get("drawing_number") or "").strip()
    if pn and _is_empty_marker(dn):
        stage1["drawing_number"] = pn
        logger.info("📝 drawing_number הושלם מ-part_number (אין DWG נפרד): %s", pn)
        return True
    return False


# ───────────────────────────────────────────────────────────────
# Revision fallback: title block → revisions table → filename
# ───────────────────────────────────────────────────────────────
_REV_FILENAME_RE = re.compile(
    r"(?:^|[_#\-\s])Rev\.?[\s_\-]?([A-Z0-9]{1,3})(?=[_#\-\s\.]|$)",
    re.IGNORECASE,
)


def _extract_rev_from_filename(filename: str) -> str:
    """מוצא תבנית 'RevX' / 'Rev_X' / '#RevX' בשם הקובץ."""
    if not filename:
        return ""
    stem = Path(filename).stem
    m = _REV_FILENAME_RE.search(stem)
    return m.group(1).upper() if m else ""


def _latest_rev_from_table(stage1: dict) -> str:
    """הערך האחרון בטבלת REVISIONS (אם נחלץ)."""
    table = stage1.get("revisions_history") or stage1.get("revisions_table") or []
    if not isinstance(table, list) or not table:
        return ""
    last = table[-1]
    if isinstance(last, dict):
        return (last.get("rev") or last.get("revision") or "").strip()
    return str(last or "").strip()


def reconcile_revision(stage1: dict, filename: str = "") -> bool:
    """
    ממלא ``revision`` לפי סדר עדיפויות:
      1. הערך הקיים ב-stage1 (אם לא ריק).
      2. הערך האחרון ב-revisions_history / revisions_table.
      3. תבנית RevX בשם הקובץ.
    מחזיר True אם בוצעה השלמה.
    """
    rev = (stage1.get("revision") or "").strip()
    if not _is_empty_marker(rev):
        return False

    from_table = _latest_rev_from_table(stage1)
    if from_table and not _is_empty_marker(from_table):
        stage1["revision"] = from_table
        logger.info("📝 revision הושלם מטבלת REVISIONS: %s", from_table)
        return True

    from_fname = _extract_rev_from_filename(filename)
    if from_fname:
        stage1["revision"] = from_fname
        logger.info("📝 revision הושלם משם הקובץ: %s", from_fname)
        return True

    return False
