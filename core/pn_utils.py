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
# Generic PN from filename (הקידומת ה-"klassic" לא תמיד מתאימה)
# ───────────────────────────────────────────────────────────────
# מטפל בפורמטים נפוצים שלא נתפסים על ידי _PN_PATTERN:
#   • XXX-YYY-ZZZ-WW  (כגון 330-53-14-J8409-201, 8554-2845-00, 1384-2153-01)
#   • ALPHANUMERIC-NUM (כגון CX145-08120, UCP-212-00703)
#   • ALPHA-NUM-NUM    (כגון UR-02-1000, MEC-71-0075)
#   • Digits only (כגון 107594360)
_GENERIC_PN_PATTERNS = [
    # XXX-YYY-ZZZ... 2+ cluster-pairs with dashes (commercial/Elbit)
    re.compile(r"^(\d{3,}-[A-Z0-9]+(?:-[A-Z0-9]+){1,5})(?:[-_\.](\d+|REV|\w{3,8}))?$"),
    # ALPHA-NUM-NUM with dashes (UCP-212-00703, UR-02-1000)
    re.compile(r"^([A-Z]{2,4}-\d{1,4}-\d{2,6})$"),
    # ALPHA-NUM-NUM-NUM (UCP-280-89981-602) — 3 internal dashes
    re.compile(r"^([A-Z]{2,4}-\d{2,5}-\d{3,6}-\d{2,4})$"),
    # ALPHANUM+digits-digits (CX145-08120, MEC-71-0075)
    re.compile(r"^([A-Z]{1,4}\d{2,5}-\d{4,6})$"),
    # Alpha-prefix + digits + optional trailing letters (BJ14981A, MMA574602C)
    re.compile(r"^([A-Z]{1,4}\d{3,10}[A-Z]{0,2})$"),
    # Pure digits (5-12) + optional trailing letters (1028287A, 36799, 107594360)
    re.compile(r"^(\d{5,12}[A-Z]{0,2})$"),
    # Alpha-Num-Alpha (EO-G2226-H1) — 3 dashed sections, mixed
    re.compile(r"^([A-Z]{2,4}-[A-Z]?\d{3,6}-[A-Z]?\d{1,3})$"),
    # Underscore-based (EIM_RAF051_10001)
    re.compile(r"^([A-Z]{2,4}_[A-Z]{2,6}\d{2,5}_\d{3,8})$"),
    # ALPHA+DIGITS with dashed suffixes (EL0498-01-001, ER03105A-00)
    re.compile(r"^([A-Z]{1,4}\d{2,6}[A-Z]?(?:-[A-Z0-9]{1,6}){1,5})$"),
]


# Filenames with extra descriptors (e.g., "30-168217-E-PDM-30-168217E") — try
# to match the pattern in the FIRST segment before descriptor words like PDM/PD.
_FILENAME_CORE_RE = re.compile(
    r"^([A-Z]?\d{2,}[-_][A-Z0-9\-_]{3,30})[-_]?(?:PDM|PD|REV|EDIT|DRAFT)[-_]",
    re.IGNORECASE,
)


def _strip_file_decorations(stem: str) -> str:
    """מסיר קידומות/סיומות ידועות: B2BDraw_, (12345), _temp_, sheet numbers וכו'."""
    s = stem.upper()
    # _ASM_TEMP_ — קידומת שמצב assembly מוסיף לקבצים שעלו זמנית.
    # _TEMP_ — מצב single. שאר ה-prefixes — שמות לקוחות (B2B/B2BDraw, Draw_, Temp_).
    for prefix in ("_ASM_TEMP_", "B2BDRAW_", "DRAW_", "_TEMP_", "TEMP_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break  # אל תפעיל יותר מ-prefix אחד
    # מסיר (NNNNNN) בסוף (מספר סדרתי של Bazan/B2B)
    s = re.sub(r"-?\(\d{4,}\)$", "", s)
    # מסיר _DRILL / _PART / וכד'
    s = re.sub(r"_(DRILL|PART|SHEET|PAS|\d{2})$", "", s, flags=re.IGNORECASE)
    # מסיר סיומת `#RevX#A0#S2_30` של B2B
    s = re.sub(r"#[^#]+#[^#]+#[^#]+_?\d*$", "", s)
    return s.strip("-_ .")


def extract_generic_pn_from_filename(filename: str) -> str:
    """
    חילוץ מרחיב יותר של P/N משם הקובץ — מטפל גם בפורמטים ללא אותיות בהתחלה
    (330-53-14-..., CX145-08120, 107594360 וכו'). מחזיר "" אם לא נמצא.
    """
    if not filename:
        return ""
    stem = _strip_file_decorations(Path(filename).stem)

    # ניסיון 1: התבניות הישירות
    for pat in _GENERIC_PN_PATTERNS:
        m = pat.match(stem)
        if m:
            candidate = m.group(1)
            if 5 <= len(candidate) <= 30:
                return candidate.strip("-_ .")

    # ניסיון 2: חילוץ ה-core לפני descriptor words (PDM/PD/REV)
    # דוגמה: "30-168217-E-PDM-30-168217E" → "30-168217-E"
    m = _FILENAME_CORE_RE.match(stem)
    if m:
        core = m.group(1).strip("-_ .")
        if 5 <= len(core) <= 30:
            return core

    # ניסיון 3: הסרת suffix descriptor (כל מה שאחרי -PDM-/-PD-/-REV-)
    # ואז ניסיון חוזר של התבניות
    stripped = re.sub(
        r"[-_]?(?:PDM|PD|REV|EDIT|DRAFT|SHEET\d*)[-_].*$",
        "",
        stem,
        flags=re.IGNORECASE,
    ).strip("-_ .")
    if stripped and stripped != stem:
        for pat in _GENERIC_PN_PATTERNS:
            m = pat.match(stripped)
            if m:
                candidate = m.group(1)
                if 5 <= len(candidate) <= 30:
                    return candidate

    return ""


def _is_suspicious_pn(pn: str) -> tuple[bool, str]:
    """
    מזהה P/N שחולץ בצורה חשודה — סימן שהחילוץ נכשל וכדאי להעדיף את שם הקובץ.
    מחזיר (True/False, סיבה). סיבות:
      • "ITEM X" / "PART X" — המודל שלף שורה גנרית מ-Parts List
      • אורך קצר מדי (< 5) — בד"כ שבר
      • רק ספרות ומתחת ל-3 ספרות — בד"כ OCR fragment
      • שם השדה עצמו (PART NUMBER, CAT NO וכו') במקום הערך
      • רווחים פנימיים — PN-ים אמיתיים אינם מכילים רווח (זה תיאור/הוראה)
    """
    if not pn:
        return False, ""
    p = pn.strip().upper()
    # "ITEM 2", "ITEM 602", "PART 5"
    if re.match(r"^(?:ITEM|PART|NO\.?|NUM(?:BER)?|#)\s+\d+$", p):
        return True, "generic parts-list cell (ITEM/PART/NO X)"
    # Column header as value
    if p in {"PART NUMBER", "PART NO", "PART NO.", "P.N.", "P/N",
             "CATALOG NO", "CATALOG NUMBER", "DRAWING NO", "DWG NO"}:
        return True, "column header instead of value"
    # Internal whitespace — PN אמיתי אינו מכיל רווח. תופס מקרים כמו
    # "YT35 MD FTG1242544" שהמודל הוסיף תיאור לפני ה-PN.
    # (חריג: "ITEM X" / "PART X" כבר נתפסו לעיל ולא יגיעו לכאן.)
    if " " in p:
        return True, "contains internal whitespace (likely description, not PN)"
    # Too short
    if len(p.replace(" ", "").replace("-", "")) < 5:
        return True, "too short"
    # Pure-digits וקצר — רוב ה-PN-ים אמיתיים מתחילים באותיות.
    # תופס מקרים כמו "11042" (שבר של "ETN1110422") או "1042" (קצוץ).
    # ⚠️ סף של 7 כדי לא לטעון legit PNs נומריים כמו "36799" (5 ספרות,
    # נדיר אבל קיים) — נסמן רק עד 6. PNs נומריים גדולים כמו 107594360
    # (9 ספרות) לא מסומנים.
    compact = p.replace(" ", "").replace("-", "")
    if compact.isdigit() and len(compact) < 7:
        return True, "all-digits and short — likely fragment, not full PN"
    return False, ""


def _digit_jaccard(a: str, b: str) -> float:
    """מחזיר מידת דמיון בין רצפי הספרות של שני PN (0-1)."""
    da = set(re.findall(r"\d+", a))
    db = set(re.findall(r"\d+", b))
    if not da or not db:
        return 0.0
    inter = len(da & db)
    union = len(da | db)
    return inter / union if union else 0.0


def _char_jaccard(a: str, b: str) -> float:
    """
    מחזיר מידת דמיון בין קבוצות התווים של שני PN (ignore case + ללא מקפים).
    שימושי כש-digit_jaccard מפספס בגלל שאין ספרות חופפות אבל יש אותיות.
    """
    ca = set(re.sub(r"[\s\-\./_,]", "", a.upper()))
    cb = set(re.sub(r"[\s\-\./_,]", "", b.upper()))
    if not ca or not cb:
        return 0.0
    return len(ca & cb) / len(ca | cb)


def _sequences_compatible(a: str, b: str) -> bool:
    """
    האם ה-PN-ים חולקים רצפי תווים משמעותיים?
    מחזיר True אם לפחות רצף של 4+ תווים זהים מופיע בשניהם.

    דוגמאות:
      • "THR1510712" ו-"TH15012" — רצף "1501" ↔ "1501" (4 תווים) → True (יש קשר)
      • "NV03-58-28" ו-"893-65503682-55" — אין רצף משותף 4+ → False (שונים)
    """
    a_norm = re.sub(r"[\s\-\./_,]", "", a.upper())
    b_norm = re.sub(r"[\s\-\./_,]", "", b.upper())
    # Find longest common substring of length >= 4
    for length in range(min(len(a_norm), len(b_norm)), 3, -1):
        for i in range(len(a_norm) - length + 1):
            seg = a_norm[i:i + length]
            if seg in b_norm:
                return True
    return False


def filename_override_if_suspicious_pn(stage1: dict, filename: str) -> bool:
    """
    Override אגרסיבי: אם ה-P/N שחולץ הוא חשוד בבירור (ITEM/generic/fragment)
    או שאין לו קשר משמעותי לשם הקובץ — העדף את גרסת שם הקובץ.

    מתקן מקרים כמו:
      • UCP-280-89981-602 → "ITEM 602"  (generic parts cell)
      • 1028287A → "AZO-34008-DD"       (totally different — low digit overlap)
      • 30-168217-E → "3686217"         (missing prefix, but some digit overlap)

    מחזיר True אם בוצע override. מקפיד לא להחליף כשה-PN כבר תקין.
    """
    if not isinstance(stage1, dict):
        return False
    current = (stage1.get("part_number") or "").strip()
    if not current:
        return False
    fname_pn = extract_generic_pn_from_filename(filename)
    if not fname_pn or fname_pn.upper() == current.upper():
        return False

    # 1. P/N חשוד מפורשות (ITEM X / fragment / header)
    suspicious, reason = _is_suspicious_pn(current)
    if suspicious:
        logger.info(
            "🔧 filename override (%s): %s → %s", reason, current, fname_pn,
        )
        stage1["part_number"] = fname_pn
        dn = (stage1.get("drawing_number") or "").strip()
        if dn.upper() == current.upper() or _is_suspicious_pn(dn)[0]:
            stage1["drawing_number"] = fname_pn
        return True

    # 1.5 Same-length single-position diff + narrow fname extract הצליח —
    #     כמעט בוודאות OCR-typo בספרה אחת שלא נכנסה לזוגות הקלאסיים (כמו 4↔3).
    #     דוגמה: extracted='BO27303A', filename='BO27304A' → השתמש ב-filename.
    #
    #     דרישות הדוקות כדי לא לפגוע ב-PN לגיטימי:
    #     • אורך זהה
    #     • הבדל בעמדה אחת בלבד (כל שאר התווים זהים)
    #     • שני התווים הם ספרות (לא מבנה שונה)
    #     • narrow extract מהקובץ הצליח — סימן שהקובץ נראה כמו PN-אמיתי
    #       (קידומת whitelisted, לא רק generic regex)
    narrow_fname = extract_pn_from_filename(filename)
    if (
        narrow_fname
        and narrow_fname.upper() != current.upper()
        and len(narrow_fname) == len(current)
    ):
        cu, fu = current.upper(), narrow_fname.upper()
        diffs = [(i, cu[i], fu[i]) for i in range(len(cu)) if cu[i] != fu[i]]
        if len(diffs) == 1:
            i, c_ch, f_ch = diffs[0]
            if c_ch.isdigit() and f_ch.isdigit():
                logger.info(
                    "🔧 filename override (single-digit substitution at pos %d, %s→%s): %s → %s",
                    i, c_ch, f_ch, current, narrow_fname,
                )
                stage1["part_number"] = narrow_fname
                dn = (stage1.get("drawing_number") or "").strip()
                if dn.upper() == current.upper():
                    stage1["drawing_number"] = narrow_fname
                return True

    # 2. אין חפיפה מינימלית — שונה לחלוטין (Jaccard < 0.15 על ספרות+תווים)
    #    רק אם שם הקובץ נראה "עשיר" (יש בו לפחות 5 תווים)
    if len(fname_pn) >= 5:
        digit_sim = _digit_jaccard(current, fname_pn)
        char_sim = _char_jaccard(current, fname_pn)
        # שני הסימנים נמוכים + אין רצף משותף 4+ תווים → שונים לחלוטין
        if digit_sim < 0.15 and char_sim < 0.4:
            if not _sequences_compatible(current, fname_pn):
                ocr_dist = combined_pn_distance(current, fname_pn)
                if ocr_dist > 3:
                    logger.info(
                        "🔧 filename override (digit=%.2f char=%.2f no-seq, dist=%d): %s → %s",
                        digit_sim, char_sim, ocr_dist, current, fname_pn,
                    )
                    stage1["part_number"] = fname_pn
                    dn = (stage1.get("drawing_number") or "").strip()
                    if dn.upper() == current.upper():
                        stage1["drawing_number"] = fname_pn
                    return True

    # 2.5 Structure mismatch — אם ה-PN מתחיל באותיות והקובץ בספרות (או להפך),
    # **ואין רצף משותף 4+ תווים**, אלה כמעט בוודאות שני דברים שונים.
    # תופס: "NV03-58-28" vs "893-65503682-55" (הזיה של מספר זר)
    if len(fname_pn) >= 6 and len(current) >= 5:
        current_first = current.lstrip("-_ ").upper()[:2]
        fname_first = fname_pn.lstrip("-_ ").upper()[:2]
        current_starts_alpha = current_first and current_first[0].isalpha()
        fname_starts_digit = fname_first and fname_first[0].isdigit()
        # Structure mismatch (alpha-start vs digit-start)
        if current_starts_alpha and fname_starts_digit:
            if not _sequences_compatible(current, fname_pn):
                logger.info(
                    "🔧 filename override (structure mismatch, alpha-vs-digit): %s → %s",
                    current, fname_pn,
                )
                stage1["part_number"] = fname_pn
                dn = (stage1.get("drawing_number") or "").strip()
                if dn.upper() == current.upper():
                    stage1["drawing_number"] = fname_pn
                return True

    # 3. P/N קצר מאוד (<= 8 תווים) + שם הקובץ ארוך בהרבה + חולק prefix
    #    תופס מקרים כמו "TH15012" vs "THR1510712" (קיצור מילולי)
    if len(current) <= 8 and len(fname_pn) >= len(current) + 2:
        current_norm = re.sub(r"[\s\-\./_,]", "", current.upper())
        fname_norm = re.sub(r"[\s\-\./_,]", "", fname_pn.upper())
        # האם ה-current הוא prefix "חסר" של fname?
        # דוגמה: TH15012 → THR1510712: משווה T-H-1-5-0-1-2 vs T-H-R-1-5-1-0-7-1-2
        # יש overlap בהתחלה (TH) ובאמצע (150, 012).
        # פשוט: אם 50%+ מתווי ה-current מופיעים ברצף ב-fname, עדיף את fname
        chars_in_fname = sum(1 for c in current_norm if c in fname_norm)
        if chars_in_fname / max(len(current_norm), 1) >= 0.75:
            # יש קשר — אבל ה-current חסר תווים. העדף fname.
            # רק אם גם ה-OCR distance גדול (לא רק תו אחד שונה)
            ocr_dist = combined_pn_distance(current, fname_pn)
            if ocr_dist > 2 and not _sequences_compatible(current, fname_pn):
                # הסבר: תווים משותפים אבל לא רצף — קיצור או הזיה
                logger.info(
                    "🔧 filename override (truncated PN, %d/%d chars in fname): %s → %s",
                    chars_in_fname, len(current_norm), current, fname_pn,
                )
                stage1["part_number"] = fname_pn
                dn = (stage1.get("drawing_number") or "").strip()
                if dn.upper() == current.upper():
                    stage1["drawing_number"] = fname_pn
                return True

    return False


def prefer_filename_pn_if_substring(stage1: dict, filename: str) -> bool:
    """
    אם ה-P/N שחולץ מהמודל הוא תת-מחרוזת של P/N שמופיע בשם הקובץ —
    החלף אותו בגרסת שם הקובץ (יותר שלם). מתקן מקרים של PN מקוצץ כמו:
      filename='330-53-14-J8409-201_DRILL'  extracted='53-14-J8409-201-R'
      → P/N מעודכן ל-'330-53-14-J8409-201'

    ⚠️ **כלל עצירה**: אם ה-PN הקיים הוא כבר substring **מלא** של הקובץ
    (ללא הסרת סיומת), זה אומר שה-PN תקין והסיומת הנוספת היא Rev/qualifier.
    דוגמה: "BP70534A" ב-filename "BP70534A-A-PD-..." — ה-`-A` הוא Rev ולא
    חלק מה-PN. במקרה זה לא מחליפים.

    מחזיר True אם בוצעה החלפה.
    """
    if not isinstance(stage1, dict):
        return False
    current = (stage1.get("part_number") or "").strip()
    if not current:
        return False
    fname_pn = extract_generic_pn_from_filename(filename)
    if not fname_pn:
        return False
    if fname_pn.upper() == current.upper():
        return False

    current_upper = current.upper()
    fname_upper = fname_pn.upper()

    # כלל עצירה קריטי: אם ה-PN הקיים הוא substring מלא של הקובץ,
    # הסיומת הנוספת בקובץ היא Rev/qualifier — לא להחליף.
    # דוגמה: current="BP70534A" ו-fname_pn="BP70534A-A" → אל תחליף.
    fname_compact = re.sub(r"[\-\s\.]", "", fname_upper)
    current_compact = re.sub(r"[\-\s\.]", "", current_upper)
    if current_compact and current_compact in fname_compact:
        # current כולו נמצא בתוך fname — מסומן כתקין
        return False

    # בדיקת תת-מחרוזת (נרמול: הסר ספרת/אות בודדת בסוף הקיים, כגון "-R")
    current_stripped = re.sub(r"[-\s]?[A-Z0-9]$", "", current_upper)

    # תנאי 1: ה-PN הקיים (בגרסה מקוצצת) הוא substring של הקובץ
    if current_stripped and len(current_stripped) >= 6 and current_stripped in fname_upper:
        # רק אם גרסת הקובץ ארוכה יותר ב-2+ תווים (יותר מידע)
        if len(fname_upper) >= len(current) + 2:
            logger.info(
                "🔧 part_number הוחלף לגרסת שם הקובץ (שלמה יותר): %s → %s",
                current, fname_pn,
            )
            stage1["part_number"] = fname_pn
            # תקן גם drawing_number אם היה זהה
            dn = (stage1.get("drawing_number") or "").strip()
            if dn.upper() == current.upper():
                stage1["drawing_number"] = fname_pn
            return True
    return False


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
    # טיפוגרפיות מסוימות: J נראה כמו U (חסרת הגב הראשון)
    # דוגמה: BJ14981A (מה שבאמת בשרטוט) נקרא BU14981A ע"י הדגם
    ("J", "U"), ("U", "J"),
    # B ↔ 3 (OCR גרוע במיוחד באותיות קטנות)
    ("B", "3"), ("3", "B"),
    # E ↔ F (בחיתוך מדויק — חסר הקו התחתון)
    ("E", "F"), ("F", "E"),
    # L ↔ I (גופן בלוק — דומים במיוחד ב-CAPS)
    # דוגמה: EL0498-01-001 נקרא EI0498-01-001
    ("L", "I"), ("I", "L"),
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
    (B↔8, O↔0, L↔I וכו') בעד 2 תווים — החזר את גרסת שם הקובץ.

    בודק גם את המועמד הצר (extract_pn_from_filename) וגם את הגרסה הרחבה
    יותר (extract_generic_pn_from_filename) — מתקן גם PN עם סיומות כמו
    "EI0498-01-001" ↔ "EL0498-01-001".

    מחזיר: (corrected_pn, was_corrected)
    """
    if not extracted_pn:
        return extracted_pn, False
    # Try narrow candidate first
    candidates = []
    narrow = extract_pn_from_filename(filename)
    if narrow:
        candidates.append(narrow)
    # Also try generic (longer) candidate
    generic = extract_generic_pn_from_filename(filename)
    if generic and generic not in candidates:
        candidates.append(generic)

    extracted_upper = extracted_pn.upper()
    for fname_pn in candidates:
        if fname_pn.upper() == extracted_upper:
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
        # נסיון אחרון 1: אם שם הקובץ מכיל גרסה שלמה יותר של ה-PN (substring),
        # העדף את הגרסה השלמה. תפוס מקרים של "330-53-..." → "53-...-R".
        prefer_filename_pn_if_substring(stage1, filename)

        # נסיון אחרון 2: אם ה-PN נראה חשוד ("ITEM X", קצר, או שונה לחלוטין
        # משם הקובץ) — override אגרסיבי לגרסת שם הקובץ.
        # תופס: UCP-280-89981-602 → "ITEM 602", 1028287A → "AZO-34008-DD"
        filename_override_if_suspicious_pn(stage1, filename)
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


_MANGLED_REV_PATTERNS = [
    # "RC" → "C" — OCR מיזג "Rev" עם הערך (R+letter)
    (re.compile(r"^R([A-Z])$"), r"\1", "mangled-Rev-prefix"),
    # "REV C" → "C"
    (re.compile(r"^REV\s+([A-Z0-9]+)$", re.IGNORECASE), r"\1", "REV-prefix"),
    # "Rev.C" / "Rev-C" → "C"
    (re.compile(r"^REV[\.\-_]\s*([A-Z0-9]+)$", re.IGNORECASE), r"\1", "Rev-punct"),
]


def salvage_revision(stage1: dict) -> bool:
    """
    מתקן ערכי revision פגומים שהמודל החזיר בגלל OCR/parsing שגוי:
      • "RC"     → "C"      (R של "Rev" נצמד לאות הגרסה)
      • "REV C"  → "C"
      • "Rev.C"  → "C"
    מחזיר True אם בוצע תיקון.
    """
    if not isinstance(stage1, dict):
        return False
    rev = (stage1.get("revision") or "").strip().upper()
    if not rev or len(rev) > 6:
        return False
    for pat, repl, desc in _MANGLED_REV_PATTERNS:
        new_rev, n = pat.subn(repl, rev)
        if n > 0 and new_rev and new_rev != rev:
            logger.info("🔧 salvage_revision (%s): %r → %r", desc, rev, new_rev)
            stage1["revision"] = new_rev
            return True
    return False


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
