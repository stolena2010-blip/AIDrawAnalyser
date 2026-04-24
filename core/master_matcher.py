"""
Masters matcher — מציאת התאמת מאסטרים לציפויי השרטוט.

קובץ Masters.xlsx מכיל ~1239 מאסטרים, כל אחד עם:
  - master_id (ms.X)
  - desc (תיאור באנגלית, למשל "BLUE/WHITE ZINC-RoHS")
  - standard (תקן עם Type/Class/Grade)
  - thickness (טווח עובי, למשל "5-10 mic")
  - color, rohs

כל ציפוי בשרטוט מוערך מול כל המאסטרים, ומוחזרים top-3 התאמות הכי גבוהות.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# קריאה ממשתנה סביבה עם fallback לנתיב ברירת המחדל
def _get_masters_path() -> Path:
    """מחזיר את נתיב ה-Masters.xlsx הנוכחי (מ-runtime או מ-.env)."""
    try:
        from core.azure_client import get_masters_xlsx_path
        custom_path = get_masters_xlsx_path()
        if custom_path:
            return Path(custom_path).resolve()
    except (ImportError, Exception):
        pass
    
    env_path = os.getenv("MASTERS_XLSX_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()
    
    return Path(__file__).resolve().parent.parent / "Masters.xlsx"

MASTERS_PATH = _get_masters_path()


# ─── ציון התאמה ───
W_STANDARD = 30.0      # התאמת קוד תקן (MIL-C-5541, PS-111.21, ASTM B633 וכו')
W_STANDARD_EXTRA_PENALTY = -12.0  # קנס לכל תקן שמופיע במאסטר אך לא בשרטוט
W_TYPE_CLASS = 20.0    # Type/Class/Grade בתוך התקן
W_COATING_TYPE = 50.0  # סוג ציפוי (zinc, nickel, anodize, conversion) — הכי קריטי
W_COATING_TYPE_PENALTY = -30.0  # קנס כשסוגי הציפוי שונים לחלוטין
W_COLOR = 8.0          # צבע (NATURAL≡BLUE/WHITE)
W_THICKNESS = 15.0     # חפיפת טווח עובי
W_ROHS = 12.0          # תאימות RoHS — חשוב יותר
W_ROHS_PENALTY = -10.0 # קנס כשהשרטוט דורש RoHS אבל המאסטר לא תואם
W_PHOSPHORUS = 15.0    # התאמת רמת זרחן ב-Electroless Nickel (High/Medium/Low)
W_PHOSPHORUS_PENALTY = -10.0  # קנס כשרמת הזרחן הפוכה


_TYPE_KEYWORDS = {
    "zinc": ["ZINC", "ZINK", "אבץ"],
    "nickel": ["NICKEL", "ניקל"],
    "electroless_nickel": ["ELECTROLESS"],
    "anodize": ["ANODIZE", "ANODIC", "אנודייז"],
    "hard_anodize": ["HARD ANODIZE", "TYPE III ANOD"],
    "conversion": ["CONVERSION", "ALODINE", "CHEM FILM", "IRIDITE", "CHROMATE CONV", "תמורה"],
    "passivation": ["PASSIVAT", "פסיבציה"],
    "cadmium": ["CADMIUM"],
    "chrome": ["CHROME", "CHROMIUM", "כרום"],
    "tin": ["TIN PLAT"],
    "silver": ["SILVER"],
    "gold": ["GOLD"],
    "copper": ["COPPER"],
    "black_oxide": ["BLACK OXIDE", "BLACKENING"],
    "phosphate": ["PHOSPHATE"],
}

_COLOR_KEYWORDS = {
    "yellow": ["YELLOW", "צהוב"],
    # NATURAL ו-CLEAR בעולם ציפויי האבץ = BLUE/WHITE chromate (אותו ציפוי)
    "blue_white": ["BLUE/WHITE", "BLUE\\WHITE", "BLUE WHITE", "כחלבן",
                   "NATURAL", "CLEAR"],
    "blue": ["BLUE", "כחול"],
    "black": ["BLACK", "שחור"],
    "olive": ["OLIVE"],
    "green": ["GREEN", "ירוק"],
}


@lru_cache(maxsize=1)
def load_masters() -> pd.DataFrame:
    """טעינת קובץ המאסטרים פעם אחת ושמירה ב-cache."""
    masters_path = _get_masters_path()
    if not masters_path.exists():
        logger.warning("Masters.xlsx not found at %s", masters_path)
        return pd.DataFrame(
            columns=["master_id", "desc", "standard", "thickness", "color", "col5", "rohs", "full_name"]
        )
    df = pd.read_excel(masters_path)
    df.columns = ["master_id", "desc", "standard", "thickness", "color", "col5", "rohs", "full_name"]
    for c in df.columns:
        df[c] = df[c].astype(str).fillna("").replace({"nan": "", "None": ""})
    logger.info("Loaded %d masters from %s", len(df), masters_path)
    return df


# ─── עזרים לנירמול ───
_THICKNESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)")
_TYPE_RE = re.compile(r"\bTYPE\s*[IVX0-9]+\b", re.IGNORECASE)
_CLASS_RE = re.compile(r"\bCLASS\s*[A-Z0-9]+\b", re.IGNORECASE)
_GRADE_RE = re.compile(r"\bGRADE\s*[A-Z0-9-]+\b", re.IGNORECASE)
_STD_CODE_RE = re.compile(
    r"\b(?:MIL[- ][A-Z]+[- ]?\d+[A-Z]?|"
    r"AMS[- ]?[A-Z]?[- ]?\d+[A-Z]?|"
    r"ASTM[- ]?[A-Z]?[- ]?\d+[A-Z]?|"
    r"QQ[- ]?[A-Z][- ]?\d+[A-Z]?|"
    r"FED[- ]STD[- ]?\d+|"
    r"PS[- ]?\d+(?:\.\d+)?|"
    r"RAFDOCS[- ]?\d+|"
    r"TILDOCS[- ]?#?\d+)\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").upper()).strip()


def _extract_thickness_range(text: str) -> tuple[float, float] | None:
    """מחזיר (low, high) במיקרון מתוך טקסט עובי — או None."""
    if not text:
        return None
    t = str(text).lower()
    # נרמל יחידות
    mult = 1.0
    if "in" in t and "mic" not in t and "µ" not in t:
        # inches → microns
        mult = 25400.0
    elif "mm" in t:
        mult = 1000.0
    m = _THICKNESS_RE.search(t)
    if not m:
        return None
    if m.group(1) and m.group(2):
        lo = float(m.group(1)) * mult
        hi = float(m.group(2)) * mult
    else:
        v = float(m.group(3)) * mult
        lo = v * 0.85
        hi = v * 1.15
    return (lo, hi)


def _ranges_overlap(r1: tuple[float, float], r2: tuple[float, float]) -> float:
    """מחזיר ציון 0..1 לפי חפיפת טווחים."""
    lo = max(r1[0], r2[0])
    hi = min(r1[1], r2[1])
    if hi < lo:
        return 0.0
    overlap = hi - lo
    avg_span = ((r1[1] - r1[0]) + (r2[1] - r2[0])) / 2 or 1.0
    return min(1.0, overlap / avg_span)


def _detect_type(text: str) -> str | None:
    t = _norm(text)
    # סדר מבוקר — ארוכים קודם
    for key in ("electroless_nickel", "hard_anodize"):
        for kw in _TYPE_KEYWORDS[key]:
            if kw.upper() in t:
                return key
    for key, kws in _TYPE_KEYWORDS.items():
        if key in ("electroless_nickel", "hard_anodize"):
            continue
        for kw in kws:
            if kw.upper() in t:
                return key
    return None


def _detect_color(text: str) -> str | None:
    t = _norm(text)
    # blue_white קודם — כולל את הכינויים NATURAL ו-CLEAR (chromate שקוף = BLUE/WHITE)
    for kw in _COLOR_KEYWORDS["blue_white"]:
        if kw.upper() in t:
            return "blue_white"
    for key, kws in _COLOR_KEYWORDS.items():
        if key == "blue_white":
            continue
        for kw in kws:
            if kw.upper() in t:
                return key
    return None


def _detect_phosphorus_level(text: str) -> str | None:
    """מזהה רמת זרחן ב-Electroless Nickel: HIGH / MEDIUM / LOW."""
    t = _norm(text)
    # נדרש שתופיע גם המילה PHOSPHOR* כדי להבחין בהקשר
    if "PHOSPHOR" not in t:
        return None
    if "HIGH" in t:
        return "high"
    if "MEDIUM" in t or "MED " in t or "MID" in t:
        return "medium"
    if "LOW" in t:
        return "low"
    return None


def _extract_std_codes(text: str) -> set[str]:
    """מחזיר סט קודי תקן מנורמלים (ללא רווחים, ללא REV)."""
    codes = set()
    for m in _STD_CODE_RE.finditer(str(text or "")):
        c = m.group(0).upper().replace(" ", "").replace("-", "")
        # הסרת אות גרסה בודדת בסוף (כגון AMSC26074D → AMSC26074)
        # כך שהשרטוט "AMS-C-26074" יזוהה כזהה למאסטר "AMS-C-26074D".
        c = re.sub(r"(\d)[A-Z]$", r"\1", c)
        codes.add(c)
    return codes


def _extract_type_class(text: str) -> set[str]:
    """מחזיר סט {'TYPE2', 'CLASS1A', ...}."""
    out = set()
    for r in (_TYPE_RE, _CLASS_RE, _GRADE_RE):
        for m in r.finditer(str(text or "")):
            out.add(m.group(0).upper().replace(" ", ""))
    return out


def _coating_text(coating: dict) -> str:
    """אוסף את כל הטקסט הזמין על הציפוי."""
    return " ".join(
        str(coating.get(k, "") or "")
        for k in ("type", "type_he", "name", "standard", "thickness")
    )


# ─── ציון התאמה ───
def _score_master(coating: dict, master: pd.Series) -> tuple[float, dict]:
    """מחזיר (score, breakdown) להתאמה בין ציפוי בודד למאסטר בודד."""
    breakdown = {}
    score = 0.0

    coat_text = _coating_text(coating)
    master_text = f"{master['desc']} {master['standard']}"

    # 1. תקן — קודי MIL/ASTM/QQ/PS
    coat_codes = _extract_std_codes(coat_text)
    master_codes = _extract_std_codes(master_text)
    if coat_codes and master_codes:
        common = coat_codes & master_codes
        extra_in_master = master_codes - coat_codes  # תקנים שהמאסטר דורש אך אינם בשרטוט
        if common:
            ratio = len(common) / max(len(coat_codes), 1)
            s = W_STANDARD * ratio
            score += s
            breakdown["תקן"] = (s, ", ".join(sorted(common)))
        # קנס על תקנים נוספים במאסטר שאינם מופיעים בשרטוט —
        # לדוגמה: מאסטר "Tin over Electroless Nickel" עם תקן ASTM B545 (בדיל)
        # בשרטוט שיש בו רק תקן ניקל אלקטרולס. ללא קנס המאסטר היה מקבל
        # ציון מלא ולכן נבחר בטעות.
        if extra_in_master:
            penalty = W_STANDARD_EXTRA_PENALTY * len(extra_in_master)
            score += penalty
            breakdown["תקנים עודפים במאסטר"] = (
                penalty, ", ".join(sorted(extra_in_master))
            )

    # 2. Type/Class/Grade
    coat_tc = _extract_type_class(coat_text)
    master_tc = _extract_type_class(master_text)
    if coat_tc and master_tc:
        common_tc = coat_tc & master_tc
        if common_tc:
            ratio = len(common_tc) / max(len(coat_tc), 1)
            s = W_TYPE_CLASS * ratio
            score += s
            breakdown["Type/Class"] = (s, ", ".join(sorted(common_tc)))

    # 3. סוג ציפוי — הכי קריטי. ציפוי שונה לחלוטין → קנס שלילי שמסנן בפועל
    coat_type = _detect_type(coat_text)
    master_type = _detect_type(master_text)
    if coat_type and master_type:
        if coat_type == master_type:
            score += W_COATING_TYPE
            breakdown["סוג ציפוי"] = (W_COATING_TYPE, coat_type)
        elif (coat_type, master_type) in {("nickel", "electroless_nickel"), ("electroless_nickel", "nickel"),
                                          ("anodize", "hard_anodize"), ("hard_anodize", "anodize")}:
            score += W_COATING_TYPE * 0.5
            breakdown["סוג ציפוי (חלקי)"] = (W_COATING_TYPE * 0.5, f"{coat_type}~{master_type}")
        else:
            score += W_COATING_TYPE_PENALTY
            breakdown["סוג ציפוי שונה"] = (W_COATING_TYPE_PENALTY, f"{coat_type} vs {master_type}")
    elif coat_type and not master_type:
        # יש לנו סוג מזוהה לציפוי אבל לא במאסטר — הורדה קלה
        score -= 5.0

    # 4. צבע
    coat_color = _detect_color(coat_text)
    master_color = _detect_color(master_text)
    if coat_color and master_color and coat_color == master_color:
        score += W_COLOR
        breakdown["צבע"] = (W_COLOR, coat_color)

    # 5. עובי — חפיפת טווחים
    coat_thick = _extract_thickness_range(coating.get("thickness", "") or "") \
        or _extract_thickness_range(coat_text)
    master_thick = _extract_thickness_range(master["thickness"]) \
        or _extract_thickness_range(master["standard"])
    if coat_thick and master_thick:
        overlap = _ranges_overlap(coat_thick, master_thick)
        if overlap > 0:
            s = W_THICKNESS * overlap
            score += s
            breakdown["עובי"] = (s, f"{coat_thick[0]:.0f}-{coat_thick[1]:.0f} ↔ {master_thick[0]:.0f}-{master_thick[1]:.0f}µm")

    # 6. RoHS
    coat_rohs = bool(coating.get("rohs"))
    master_rohs = "ROHS" in _norm(master_text) or "RoHS" in str(master["desc"])
    if coat_rohs and master_rohs:
        score += W_ROHS
        breakdown["RoHS"] = (W_ROHS, "✓")
    elif coat_rohs and not master_rohs:
        # השרטוט מחייב RoHS — מאסטר ללא RoHS פחות מתאים
        score += W_ROHS_PENALTY
        breakdown["RoHS חסר"] = (W_ROHS_PENALTY, "drawing requires RoHS")

    # 7. רמת זרחן ב-Electroless Nickel (High/Medium/Low Phosphorus)
    coat_phos = _detect_phosphorus_level(coat_text)
    master_phos = _detect_phosphorus_level(master_text)
    if coat_phos and master_phos:
        if coat_phos == master_phos:
            score += W_PHOSPHORUS
            breakdown["רמת זרחן"] = (W_PHOSPHORUS, coat_phos)
        else:
            score += W_PHOSPHORUS_PENALTY
            breakdown["רמת זרחן שונה"] = (
                W_PHOSPHORUS_PENALTY, f"{coat_phos} vs {master_phos}"
            )

    return score, breakdown


def find_top_masters(coating: dict, top_n: int = 3, min_score: float = 15.0) -> list[dict]:
    """מציאת top_n מאסטרים מתאימים לציפוי בודד."""
    df = load_masters()
    if df.empty:
        return []

    scored = []
    for _, row in df.iterrows():
        score, breakdown = _score_master(coating, row)
        if score >= min_score:
            scored.append({
                "master_id": row["master_id"],
                "desc": row["desc"],
                "standard": row["standard"],
                "thickness": row["thickness"],
                "full_name": row["full_name"].replace("\\\\", " | ").replace("\\", " | "),
                "score": round(score, 1),
                "breakdown": breakdown,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def match_all_coatings(coating_processes: list, painting_processes: list | None = None,
                        top_n: int = 3) -> list[dict]:
    """מחזיר רשימת התאמות לכל ציפוי בשרטוט.

    הערה: מאסטרים מתבצעים רק על coating_processes — לא על צביעות.
    הפרמטר painting_processes נשמר לתאימות לאחור אך מתעלמים ממנו.
    """
    results = []
    for coat in (coating_processes or []):
        if not isinstance(coat, dict):
            continue
        matches = find_top_masters(coat, top_n=top_n)
        results.append({
            "coating": coat,
            "kind": "coating",
            "matches": matches,
        })
    return results
