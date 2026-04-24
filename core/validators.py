"""
שכבת ולידציה לאחר חילוץ — מגן מפני הזיות נפוצות.
מחזיר רשימת אזהרות בפורמט אחיד: [{"type", "severity", "source", "value", "message"}]
"""
import re
from difflib import SequenceMatcher

# ─── RAL codes ───────────────────────────────────────────────────────────────

VALID_RAL_CODES = {
    "1000", "1001", "1002", "1003", "1004", "1005", "1006", "1007",
    "1011", "1012", "1013", "1014", "1015", "1016", "1017", "1018",
    "1019", "1020", "1021", "1023", "1024", "1026", "1027", "1028",
    "2000", "2001", "2002", "2003", "2004", "2005", "2008", "2009",
    "2010", "2011", "2012", "2013",
    "3000", "3001", "3002", "3003", "3004", "3005", "3007", "3009",
    "3011", "3012", "3013", "3014", "3015", "3016", "3017", "3018",
    "3020", "3022", "3024", "3026", "3027", "3028", "3031", "3032",
    "3033",
    "5000", "5001", "5002", "5003", "5004", "5005", "5007", "5008",
    "5009", "5010", "5011", "5012", "5013", "5014", "5015", "5017",
    "5018", "5019", "5020", "5021", "5022", "5023", "5024",
    "6000", "6001", "6002", "6003", "6004", "6005", "6006", "6007",
    "6008", "6009", "6010", "6011", "6012", "6013", "6014", "6015",
    "6016", "6017", "6018", "6019", "6020", "6021", "6022", "6024",
    "6025", "6026", "6027", "6028", "6029", "6032", "6033", "6034",
    "7000", "7001", "7002", "7003", "7004", "7005", "7006", "7008",
    "7009", "7010", "7011", "7012", "7013", "7015", "7016", "7021",
    "7022", "7023", "7024", "7026", "7030", "7031", "7032", "7033",
    "7034", "7035", "7036", "7037", "7038", "7039", "7040", "7042",
    "7043", "7044", "7045", "7046", "7047", "7048",
    "8000", "8001", "8002", "8003", "8004", "8007", "8008", "8011",
    "8012", "8014", "8015", "8016", "8017", "8019", "8022", "8023",
    "8024", "8025", "8028", "8029",
    "9001", "9002", "9003", "9004", "9005", "9006", "9007", "9010",
    "9011", "9016", "9017", "9018",
}

_RAL_PATTERN = re.compile(r'RAL\s*(\d{3,4})', re.IGNORECASE)


def validate_ral_codes(report_json: dict) -> list[dict]:
    """מוצא קודי RAL ומאמת שהם תקינים."""
    warnings = []
    texts_to_scan: list[tuple[str, str]] = []

    for proc in report_json.get("painting_processes", []):
        step = proc.get("step_no", "painting")
        texts_to_scan.append((step, proc.get("name", "")))
        texts_to_scan.append((step, proc.get("standard", "")))

    for std in report_json.get("standards", []):
        texts_to_scan.append(("standards", str(std)))

    for source, text in texts_to_scan:
        for match in _RAL_PATTERN.finditer(text or ""):
            code = match.group(1).zfill(4)  # normalize 3→4 digits
            if code not in VALID_RAL_CODES:
                warnings.append({
                    "type": "INVALID_RAL",
                    "severity": "CRITICAL",
                    "source": source,
                    "value": f"RAL {code}",
                    "message": f"RAL {code} אינו קוד RAL תקני — ייתכן שנקרא בשגיאה. בדוק ידנית.",
                })

    return warnings


# ─── Paint brands ─────────────────────────────────────────────────────────────

KNOWN_PAINT_BRANDS = {
    "TAMBOUR", "TAMAGLAS", "TAMGLAS", "NIRLAT", "TIKKURILA",
    "SHERWIN-WILLIAMS", "SHERWIN WILLIAMS", "SHERWINWILLIAMS",
    "AKZONOBEL", "JOTUN", "HEMPEL", "PPG", "INTERNATIONAL",
    "SIGMA", "CARBOLINE", "DUPONT", "AXALTA", "BASF",
    "NIPPON", "KANSAI", "SIKKENS", "RUST-OLEUM",
}

_BY_PATTERN = re.compile(r'\b(\w[\w\s]{1,20})\s+BY\s+(\w+)\b', re.IGNORECASE)


def validate_paint_brand(text: str, source: str = "") -> dict | None:
    """
    בודק אם שם יצרן הצבע (בתבנית 'XXX BY YYY') מוכר.
    מחזיר אזהרה אם לא, אחרת None.
    """
    text_upper = text.upper()
    for brand in KNOWN_PAINT_BRANDS:
        if brand in text_upper:
            return None  # מותג מוכר — תקין

    match = _BY_PATTERN.search(text)
    if match:
        manufacturer = match.group(2).upper()
        if manufacturer not in KNOWN_PAINT_BRANDS:
            return {
                "type": "UNKNOWN_PAINT_BRAND",
                "severity": "HIGH",
                "source": source,
                "value": match.group(0),
                "message": (
                    f"שם היצרן '{match.group(2)}' לא מוכר. "
                    f"בדוק ידנית — מותגים נפוצים: TAMBOUR, JOTUN, SHERWIN-WILLIAMS."
                ),
            }
    return None


def validate_all_paint_brands(report_json: dict) -> list[dict]:
    """סורק את כל תהליכי הצביעה ומאמת שמות יצרנים."""
    warnings = []
    for proc in report_json.get("painting_processes", []):
        name = proc.get("name", "")
        source = proc.get("step_no", "painting")
        w = validate_paint_brand(name, source)
        if w:
            warnings.append(w)
    return warnings


# ─── Coating classification ───────────────────────────────────────────────────

_PRIMER_KEYWORDS = ["PRIMER", "PAINT", "TOP COAT", "TOPCOAT", "POLYURETHANE", "EPOXY"]
_MASKING_KEYWORDS = ["MASK", "MASKING"]
_ACTUAL_COATING_KEYWORDS = [
    "PLATING", "ANODIZE", "ANODIC", "PASSIVAT", "BLACK OXIDE",
    "CONVERSION COAT", "MIL-DTL-16232", "QQ-Z-325",
    "MIL-PRF-46010", "AMS-C-26074", "ELECTROLESS",
]


def validate_coating_classification(coating_processes: list) -> list[dict]:
    """
    בודק שפריטים ב-coating_processes לא מכילים פריימר/צביעה/מיסוך.
    """
    warnings = []
    for proc in coating_processes:
        name = (proc.get("name", "") or "").upper()
        step = proc.get("step_no", "coating")

        is_primer = any(kw in name for kw in _PRIMER_KEYWORDS)
        is_masking = any(kw in name for kw in _MASKING_KEYWORDS)
        is_actual = any(kw in name for kw in _ACTUAL_COATING_KEYWORDS)

        if is_primer and not is_actual:
            warnings.append({
                "type": "MISCLASSIFIED_COATING",
                "severity": "HIGH",
                "source": step,
                "value": name[:80],
                "message": (
                    f"סעיף {step} מכיל מילת מפתח PRIMER/PAINT — "
                    "שייך ל-painting_processes, לא ל-coating_processes."
                ),
            })
        elif is_masking:
            warnings.append({
                "type": "MISCLASSIFIED_COATING",
                "severity": "MEDIUM",
                "source": step,
                "value": name[:80],
                "message": (
                    f"סעיף {step} הוא הוראת מיסוך — "
                    "שייך ל-additional_processes, לא ל-coating_processes."
                ),
            })

    return warnings


# ─── Packing notes ────────────────────────────────────────────────────────────

_KNOWN_PACKING_TEMPLATES = [
    "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE DURING PROCESS, STORAGE AND SHIPMENT",
    "EACH PART SHALL BE INDIVIDUALLY PACKED",
    "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE DURING PROCESS, STORAGE AND SUPPLY",
    "PREVENT CORROSION",
    "PHYSICAL DAMAGE",
]


def validate_packing_note(packaging_notes: dict | str) -> dict | None:
    """
    בודק האם הוראת האריזה נראית סבירה (דומה לתבניות ידועות).
    מחזיר אזהרה אם:
      • ריק — לא ברור אם לא קיים או לא חולץ (MISSING_PACKING).
      • `[NO_PACKING_REQUIREMENT_IN_DRAWING]` — סמן מפורש שאין דרישה (INFO).
      • טקסט לא דומה לתבניות ידועות — similarity נמוך = חשד להזיה.
    """
    if isinstance(packaging_notes, dict):
        text = packaging_notes.get("en", "") or packaging_notes.get("he", "")
    else:
        text = str(packaging_notes or "")

    text = text.strip()
    text_upper = text.upper()

    # 1. סמן מפורש "לא קיים בשרטוט" — INFO, לא אזהרה חשודה
    if "NO_PACKING_REQUIREMENT" in text_upper:
        return {
            "type": "NO_PACKING_REQUIREMENT_IN_DRAWING",
            "severity": "INFO",
            "source": "packaging_notes",
            "value": text[:80] or "(empty)",
            "message": "השרטוט אינו כולל דרישת אריזה — המודל סימן זאת במפורש.",
        }

    # 2. ריק לחלוטין — לא ברור אם 'לא קיים' או 'המודל דילג'
    if not text or len(text) < 10:
        return {
            "type": "MISSING_PACKING",
            "severity": "MEDIUM",
            "source": "packaging_notes",
            "value": "(empty)",
            "message": (
                "שדה packaging_notes ריק — לא ברור אם אין דרישת אריזה או "
                "שהמודל דילג. בדוק ידנית בשרטוט; אם אין דרישה — הערך הנכון "
                "הוא '[NO_PACKING_REQUIREMENT_IN_DRAWING]'."
            ),
        }


    # בדיקה מהירה — מכיל מילת מפתח מוכרת?
    for tmpl in _KNOWN_PACKING_TEMPLATES:
        if tmpl in text_upper:
            return None

    # בדיקת similarity לתבנית הארוכה
    best_ratio = max(
        SequenceMatcher(None, text_upper, tmpl.upper()).ratio()
        for tmpl in _KNOWN_PACKING_TEMPLATES
    )

    if best_ratio < 0.45:
        return {
            "type": "UNUSUAL_PACKING_NOTE",
            "severity": "HIGH",
            "source": "packaging_notes",
            "value": text[:100],
            "message": (
                f"הוראת האריזה לא דומה לתבניות ידועות (similarity: {best_ratio:.0%}). "
                "ייתכן שנוצרה בהזיה — בדוק ידנית."
            ),
        }

    return None


# ─── Missing categories: Pickling / Hydrogen Embrittlement ───────────────────
# תהליכים שהמודל פוספם לעיתים קרובות — מילות מפתח ב-NOTES שמחייבות entry
# ב-additional_processes. אם המילה בטקסט אבל אין entry תואם → אזהרה.

_SURFACE_PREP_KEYWORDS = re.compile(
    r"\b(PICKLING|PICKLE|NITRIC\s*ACID|HYDROFLUORIC|HNO3|\bHF\b|"
    r"REMOVE\s+TINT|TINT\s+REMOVAL|GLASS\s+BEAD\s+BLAST|"
    r"ALKALINE\s+CLEAN|DEGREASE|ETCHING)\b",
    re.IGNORECASE,
)

_POST_PROCESS_KEYWORDS = re.compile(
    r"\b(HYDROGEN\s+EMBRITTLEMENT|EMBRITTLEMENT\s+RELIEF|"
    r"HYDROGEN\s+DEGASSING|DEHYDROGENATION|STRESS\s+RELIEF(?:\s+BAKE)?|"
    r"POST[-\s]?PLATE\s+BAKE|BAKING\s+AFTER\s+PLAT)",
    re.IGNORECASE,
)


def _collect_additional_text(report_json: dict) -> str:
    """מאחד את כל הטקסטים של additional_processes למחרוזת אחת לחיפוש."""
    parts: list[str] = []
    for p in report_json.get("additional_processes", []) or []:
        if isinstance(p, dict):
            parts.append(str(p.get("name_en", "")))
            parts.append(str(p.get("name_he", "")))
            parts.append(str(p.get("details", "")))
        else:
            parts.append(str(p or ""))
    return " | ".join(parts).upper()


def validate_surface_prep_and_post_process(report_json: dict) -> list[dict]:
    """
    מזהה שמילות מפתח של 'הכנת שטח' / post-process הופיעו ב-NOTES אבל לא
    נחלצו ל-additional_processes. זה סימן שהמודל פספם.
    """
    warnings: list[dict] = []
    notes_text = str(report_json.get("notes", "") or "")
    additional_text = _collect_additional_text(report_json)

    # Pickling / surface preparation
    if _SURFACE_PREP_KEYWORDS.search(notes_text):
        if not _SURFACE_PREP_KEYWORDS.search(additional_text):
            warnings.append({
                "type": "MISSING_SURFACE_PREP",
                "severity": "HIGH",
                "source": "additional_processes",
                "value": "Pickling / surface preparation",
                "message": (
                    "מילת מפתח של הכנת שטח (PICKLING / HF / NITRIC ACID / "
                    "REMOVE TINT / GLASS BEAD BLAST) מופיעה ב-NOTES אבל לא "
                    "חולצה ל-additional_processes. ייתכן שהמודל דילג — "
                    "בדוק את NOTES של השרטוט."
                ),
            })

    # Hydrogen Embrittlement / post-plate treatments
    if _POST_PROCESS_KEYWORDS.search(notes_text):
        if not _POST_PROCESS_KEYWORDS.search(additional_text):
            warnings.append({
                "type": "MISSING_POST_PROCESS",
                "severity": "HIGH",
                "source": "additional_processes",
                "value": "Hydrogen Embrittlement / post-plate treatment",
                "message": (
                    "HYDROGEN EMBRITTLEMENT / STRESS RELIEF / BAKING מופיע "
                    "ב-NOTES אבל לא חולץ ל-additional_processes. תהליכים "
                    "אלה קריטיים לאיכות החלק — בדוק ידנית."
                ),
            })

    return warnings


# ─── Standards hallucination (unknown issuing body) ───────────────────────────

# גופי תקינה/סדרות ידועות. כל תקן שלא מתחיל באחת התבניות האלה — חשוד.
# שמור על רשימה שמרנית: עדיף false-negative נדיר מאשר המון false-positive רועשים.
_KNOWN_STANDARD_PATTERNS = [
    re.compile(r"^MIL[\s\-]", re.IGNORECASE),          # MIL-DTL-5541, MIL-STD-130
    re.compile(r"^AMS[\s\-]?[A-Z0-9]", re.IGNORECASE), # AMS 2700, AMS-C-26074
    re.compile(r"^ASTM[\s\-]?[A-Z0-9]", re.IGNORECASE),
    re.compile(r"^ASME[\s\-]?[A-Z0-9]", re.IGNORECASE),
    re.compile(r"^QQ[\s\-]", re.IGNORECASE),           # QQ-P-416, QQ-Z-325
    re.compile(r"^FED[\s\-]?STD", re.IGNORECASE),
    re.compile(r"^PS[\s\-]?\d", re.IGNORECASE),        # customer Part Spec
    re.compile(r"^RAFDOCS", re.IGNORECASE),
    re.compile(r"^TILDOCS", re.IGNORECASE),
    re.compile(r"^AWS[\s\-]?[A-Z0-9]", re.IGNORECASE),
    re.compile(r"^ANSI[\s\-]?[A-Z0-9]", re.IGNORECASE),
    re.compile(r"^ISO[\s\-]?\d", re.IGNORECASE),
    re.compile(r"^EN[\s\-]?\d", re.IGNORECASE),
    re.compile(r"^DIN[\s\-]?\d", re.IGNORECASE),
    re.compile(r"^BS[\s\-]?(EN[\s\-]?)?\d", re.IGNORECASE),
    re.compile(r"^SAE[\s\-]?[A-Z0-9]", re.IGNORECASE),
    re.compile(r"^NAS[MT]?[\s\-]?\d", re.IGNORECASE),   # NAS, NASM, NAST
    re.compile(r"^IPC[\s\-]?[A-Z0-9]", re.IGNORECASE),
    re.compile(r"^JEDEC", re.IGNORECASE),
    re.compile(r"^UL[\s\-]?\d", re.IGNORECASE),
    re.compile(r"^CSA[\s\-]", re.IGNORECASE),
    re.compile(r"^MS[\s\-]?\d{4,}", re.IGNORECASE),     # Military drawing (MS33540)
    re.compile(r"^AN[\s\-]?\d{3,}", re.IGNORECASE),     # Army-Navy standard
    re.compile(r"^NASA[\s\-]", re.IGNORECASE),
    re.compile(r"^DO[\s\-]?\d{3,}", re.IGNORECASE),     # RTCA DO-xxx
    re.compile(r"^FAR[\s\-]?\d", re.IGNORECASE),
    re.compile(r"^RTCA[\s\-]", re.IGNORECASE),
    re.compile(r"^JIS[\s\-]?[A-Z0-9]", re.IGNORECASE),  # Japan
    re.compile(r"^GB[\s\-]?\d", re.IGNORECASE),         # China
    re.compile(r"^BOEING", re.IGNORECASE),
    re.compile(r"^BAC[\s\-]?\d", re.IGNORECASE),        # Boeing Aircraft Company
    re.compile(r"^AIRBUS", re.IGNORECASE),
    re.compile(r"^ABS[\s\-]?\d", re.IGNORECASE),        # Airbus / American Bureau of Shipping
    re.compile(r"^SSPC[\s\-]", re.IGNORECASE),          # Society for Protective Coatings
    re.compile(r"^NACE[\s\-]", re.IGNORECASE),          # Corrosion engineers
    re.compile(r"^EN[\s\-]?ISO[\s\-]?\d", re.IGNORECASE),  # EN ISO xxxx (composite)
    re.compile(r"^BS[\s\-]?EN[\s\-]?ISO[\s\-]?\d", re.IGNORECASE),
]


def validate_standards(report_json: dict) -> list[dict]:
    """
    מסמן תקנים עם קידומת גוף-תקינה לא מוכרת — מצב הזיה נפוץ.
    דוגמה נתפסת: 'AWI-STD-1916' (הגוף 'AWI' לא קיים).
    """
    warnings: list[dict] = []
    for std in report_json.get("standards", []) or []:
        std_text = str(std or "").strip()
        if not std_text:
            continue
        if any(pat.match(std_text) for pat in _KNOWN_STANDARD_PATTERNS):
            continue
        warnings.append({
            "type": "SUSPICIOUS_STANDARD",
            "severity": "HIGH",
            "source": "standards",
            "value": std_text,
            "message": (
                f"התקן '{std_text}' אינו תואם גוף תקינה מוכר "
                "(MIL/AMS/ASTM/ASME/AWS/ISO/EN/DIN/BS/SAE/NAS/ANSI/IPC/UL/...) — "
                "חשד להזיה של המודל."
            ),
        })
    return warnings


# ─── Combined validator ───────────────────────────────────────────────────────

def run_all_validators(report_json: dict) -> list[dict]:
    """
    מריץ את כל הולידטורים על דוח חילוץ ומחזיר רשימת אזהרות.
    """
    warnings: list[dict] = []
    warnings.extend(validate_ral_codes(report_json))
    warnings.extend(validate_all_paint_brands(report_json))
    warnings.extend(validate_coating_classification(
        report_json.get("coating_processes", [])
    ))
    warnings.extend(validate_standards(report_json))
    warnings.extend(validate_surface_prep_and_post_process(report_json))
    packing_warning = validate_packing_note(
        report_json.get("packaging_notes", {})
    )
    if packing_warning:
        warnings.append(packing_warning)
    return warnings
