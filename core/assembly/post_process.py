"""
Post-extraction validators ולמתקנים שרצים על שרטוט בודד אחרי Stage 1+2.

כל פונקציה כאן פועלת על dict של שרטוט יחיד ומחזירה (bool was_changed) או
מחרוזת אזהרה. אין כאן קריאות ל-Azure ואין I/O.

קבוצות:
    Hallucination check    — _validate_standards_against_ocr
    Field fixers           — _split_material_formerly, _infer_drawing_number_from_pn,
                             _default_role_if_missing, _detect_self_reference_bom
    Spec / DWG validators  — _validate_spec_prefixes, _validate_dwg_prefix
"""
from __future__ import annotations

import re

# ───────────────────────────────────────────────────────────────
# לקוחות ידועים → קידומות P/N ו-DRAWING שחובה שיופיעו בתחילת המחרוזת
# ───────────────────────────────────────────────────────────────
_CUSTOMER_PREFIXES: dict[str, tuple[str, ...]] = {
    "BIRD AEROSYSTEMS": ("BAS",),
    "BIRD": ("BAS",),
    "RAFAEL": ("BP", "BB", "BN", "BO", "BG", "RF", "PWRL", "BBLE", "HLTA",
               "FTLS", "FTL", "MMA", "M1R", "8H-", "22H-", "R0", "R1"),
}


def _normalize_for_grep(text: str) -> str:
    """הסרת רווחים/מקפים/נקודות לצורך השוואת substring גמישה."""
    return re.sub(r"[\s\-\._/]+", "", (text or "").upper())


def _validate_standards_against_ocr(
    standards: list, ocr_text: str
) -> tuple[list[str], list[str]]:
    """
    מחזיר (standards_retained, flagged_hallucinations).
    תקן מאומת אם הוא מופיע (נורמליזציה של רווחים/מקפים) בטקסט ה-OCR.
    אם OCR ריק — לא נוכל לאמת, מחזירים הכל כמות שהוא.
    """
    if not standards:
        return [], []
    ocr_norm = _normalize_for_grep(ocr_text)
    if not ocr_norm:
        return list(standards), []
    kept: list[str] = []
    flagged: list[str] = []
    for std in standards:
        std_text = str(std or "").strip()
        if not std_text:
            continue
        std_norm = _normalize_for_grep(std_text)
        if std_norm and std_norm in ocr_norm:
            kept.append(std_text)
        else:
            # גם בדיקה על prefix קצר (לפחות 6 תווים משמעותיים) למקרה של
            # Class/Type סופי שנמחק
            core = re.split(r"\s+(?:TYPE|CLASS|GRADE|METHOD)\b", std_text,
                            maxsplit=1, flags=re.IGNORECASE)[0]
            core_norm = _normalize_for_grep(core)
            if len(core_norm) >= 6 and core_norm in ocr_norm:
                kept.append(std_text)
            else:
                flagged.append(std_text)
    return kept, flagged


_FORMERLY_RE = re.compile(
    r"\(\s*FORM(?:ERLY|ALY)[:\s]+(.+?)\)", re.IGNORECASE | re.DOTALL
)


def _split_material_formerly(stage1: dict) -> bool:
    """
    אם `material` מכיל ביטוי '(FORMERLY ...)' — מעביר את התוכן ל-material_formerly
    ומנקה אותו מה-material. מחזיר True אם בוצע תיקון.

    דוגמה (מ-Elbit 8554-3672-00):
      material = "AL 5052-H32 PER SAE-AMS-4016 (FORMERLY AMS QQ-A-250/8 OR AMS QQ-A-225/7)"
      → material = "AL 5052-H32 PER SAE-AMS-4016"
      → material_formerly = "AMS QQ-A-250/8 OR AMS QQ-A-225/7"
    """
    if not isinstance(stage1, dict):
        return False
    mat = (stage1.get("material") or "").strip()
    if not mat:
        return False
    # אם כבר יש material_formerly מפורש מהמודל — אל תדרוס
    existing_formerly = (stage1.get("material_formerly") or "").strip()
    if existing_formerly:
        return False
    m = _FORMERLY_RE.search(mat)
    if not m:
        return False
    formerly_content = m.group(1).strip().rstrip(".,; ")
    primary = _FORMERLY_RE.sub("", mat).strip()
    # נקי רווחים מרובים וסימני פיסוק תלויים
    primary = re.sub(r"\s{2,}", " ", primary).strip().rstrip(".,;")
    stage1["material"] = primary
    stage1["material_formerly"] = formerly_content
    return True


def _infer_drawing_number_from_pn(stage1: dict) -> bool:
    """
    אם drawing_number ריק/פסול אבל יש part_number — הנח ש-drawing_number = P/N.
    זו מוסכמה נפוצה בלקוחות קטנים (למשל Mechanico-Shaftech, Elbit) שאין להם
    שדה DWG נפרד. מחזיר True אם בוצע תיקון.
    """
    if not isinstance(stage1, dict):
        return False
    dwg = (stage1.get("drawing_number") or "").strip()
    pn = (stage1.get("part_number") or "").strip()
    if not pn:
        return False
    if dwg and dwg not in ("-", "—", "N/A", "n/a", "NA"):
        return False
    stage1["drawing_number"] = pn
    return True


def _default_role_if_missing(stage1: dict) -> bool:
    """
    אם assembly_role ריק — הסק אוטומטית:
    - אין BOM → PART
    - BOM קיים עם פריטים ≥ 1 שונים מה-P/N העצמי → ASSEMBLY
    - הכל self-reference → PART (נידון ב-_detect_self_reference_bom)
    מחזיר True אם עדכן.
    """
    if not isinstance(stage1, dict):
        return False
    role = (stage1.get("assembly_role") or "").strip()
    if role:
        return False
    bom = stage1.get("bom_items") or []
    pn = (stage1.get("part_number") or "").strip().upper()
    other_pns = [
        (it.get("part_number") or "").strip().upper()
        for it in bom if isinstance(it, dict)
    ]
    other_pns = [p for p in other_pns if p and p != pn]
    if other_pns:
        stage1["assembly_role"] = "ASSEMBLY"
    else:
        stage1["assembly_role"] = "PART"
    return True


def _detect_self_reference_bom(stage1: dict) -> bool:
    """
    אם ה-BOM מכיל רק שורות ש-P/N שלהן זהה ל-P/N של השרטוט עצמו —
    זה Parts List סטנדרטי, לא מכלול אמיתי. מנקה את ה-bom_items ומסמן
    role=PART. מחזיר True אם בוצע תיקון.
    """
    pn = (stage1.get("part_number") or "").strip().upper()
    items = stage1.get("bom_items") or []
    if not pn or not items:
        return False
    item_pns = [
        (it.get("part_number") or "").strip().upper()
        for it in items if isinstance(it, dict)
    ]
    non_empty = [p for p in item_pns if p]
    if not non_empty:
        return False
    # כל ה-items מצביעים לעצמו?
    if all(p == pn for p in non_empty):
        stage1["bom_items"] = []
        stage1["assembly_role"] = "PART"
        return True
    return False


_SUSPECT_SPEC_LOWERCASE_RE = re.compile(r"\b(sm|ps|rafdocs|gen)[\s.-]?\d", re.ASCII)
_KNOWN_SPEC_PREFIXES = ("PS-", "PS ", "SM-", "SM ", "RAFDOCS-", "GEN.", "GEN-",
                       "MIL-", "AMS-", "AMS ", "ASTM ", "ISO ", "FED-", "NAS",
                       "AS9100", "SAE-", "EN ISO", "EN-ISO", "AWS ", "QQ-",
                       "ASME ")


def _validate_spec_prefixes(standards: list) -> tuple[list[str], list[str]]:
    """
    מחזיר (standards_kept, warnings).
    מזהה שני דפוסים חשודים:
    1. prefix באותיות קטנות (sm/ps/rafdocs/gen) → כנראה שגיאת OCR, סמן warning.
    2. prefix לא מוכר (לא ברשימת הפרפיקסים המוכרים) → warning חזק יותר.

    אנחנו לא מוחקים תקנים — רק מדווחים כדי שהמשתמש יבחן.
    """
    if not standards:
        return [], []
    warnings: list[str] = []
    kept: list[str] = []
    for std in standards:
        std_text = str(std or "").strip()
        if not std_text:
            continue
        kept.append(std_text)
        # אותיות קטנות?
        if _SUSPECT_SPEC_LOWERCASE_RE.match(std_text):
            warnings.append(
                f"[WARN][LOWERCASE_SPEC_PREFIX] תקן '{std_text}' באותיות קטנות — "
                f"בד\"כ שגיאת OCR. הצורה הנכונה באות גדולה (PS-/SM-/RAFDOCS-)."
            )
            continue
        # prefix ידוע?
        std_upper = std_text.upper()
        if not any(std_upper.startswith(p) for p in _KNOWN_SPEC_PREFIXES):
            # נבדוק גם prefixes של 2-3 אותיות שלא שמנו מפורשות
            head = re.match(r"^([A-Z]{2,6})[\s\-.]?\d", std_upper)
            if head:
                prefix = head.group(1)
                # אם prefix קצר מדי או לא נראה סטנדרטי
                if len(prefix) < 2:
                    warnings.append(
                        f"[WARN][UNKNOWN_SPEC_PREFIX] תקן '{std_text}' עם prefix "
                        f"לא מוכר — אמתי ידנית."
                    )
    return kept, warnings


def _validate_dwg_prefix(stage1: dict) -> str:
    """
    בודק שה-DRAWING NUMBER מתחיל בקידומת ידועה של הלקוח. אם לא — מנסה
    לתקן אם המחרוזת מכילה את הקידומת במקום אחר (OCR סידר אחרת).
    מחזיר הודעת אזהרה אם לא ניתן היה לתקן בביטחון.
    """
    dwg = (stage1.get("drawing_number") or "").strip()
    customer = (stage1.get("customer") or "").strip().upper()
    if not dwg:
        return ""
    prefixes = _CUSTOMER_PREFIXES.get(customer, ())
    if not prefixes:
        # אפשר להסיק לקוח גם מהקידומת של ה-P/N
        pn_upper = (stage1.get("part_number") or "").strip().upper()
        for key, vals in _CUSTOMER_PREFIXES.items():
            if any(pn_upper.startswith(p) for p in vals):
                prefixes = vals
                break
    if not prefixes:
        return ""
    dwg_upper = dwg.upper()
    if any(dwg_upper.startswith(p.upper()) for p in prefixes):
        return ""
    # ניסיון תיקון: אם הקידומת מופיעה בסוף, הסר אותה ושים בתחילה
    for p in prefixes:
        pu = p.upper()
        if dwg_upper.endswith(pu):
            corrected = p + dwg[:-len(p)]
            stage1["drawing_number"] = corrected
            return (
                f"[INFO][DWG_PREFIX_REORDERED] DWG '{dwg}' תוקן ל-'{corrected}' "
                f"(הקידומת '{p}' היתה בסוף)"
            )
        if pu in dwg_upper and not dwg_upper.startswith(pu):
            # קידומת באמצע — סמן כ-warning אבל אל תתקן אוטומטית
            return (
                f"[WARN][DWG_PREFIX_MISMATCH] DWG '{dwg}' אמור להתחיל ב-'{p}' "
                f"עבור לקוח {customer or 'לא ידוע'} אבל הקידומת נמצאת באמצע."
            )
    return (
        f"[WARN][DWG_PREFIX_MISSING] DWG '{dwg}' לא מתחיל בקידומת ידועה "
        f"({'/'.join(prefixes)}) עבור לקוח {customer or 'לא ידוע'}."
    )
