"""
Pre-baked sample extraction result for Demo Mode.

מחזיר תוצאה מלאה (sanitized) שמדמה ניתוח של שרטוט אמיתי — כך שאפשר להראות
את כל הזרימה (תוצאות, אזהרות, ייצוא) בלי לקרוא ל-Azure ובלי לחשוף קבצים אמיתיים
של לקוחות.

שימוש:
    from core.demo_data import get_demo_result, DEMO_FILENAME
    st.session_state.result = get_demo_result()
    st.session_state.filename = DEMO_FILENAME
"""
from __future__ import annotations

from copy import deepcopy

DEMO_FILENAME = "demo_bracket_AC-12345-A.pdf"


_DEMO_RESULT: dict = {
    "source_filename": DEMO_FILENAME,
    "part_number": "AC-12345",
    "drawing_number": "AC-12345",
    "revision": "A",
    "customer": "ACME Aerospace Inc.",
    "cage_code": "AC001",
    "title": "MOUNTING BRACKET — UPPER",
    "catalog_number": "AC-12345-A",
    "material": "ALUMINUM ALLOY 6061-T6 PER AMS-QQ-A-250/11",
    "alternative_material": "ALUMINUM ALLOY 7075-T651 PER AMS-QQ-A-250/12",
    "material_formerly": "QQ-A-250/11 (obsolete — replaced by AMS-QQ-A-250/11)",
    "quantity": "1",
    "assembly_role": "PART",
    "os_level": "",
    "raw_weight": {"qty": "0.42", "unit": "kg"},
    "part_weight": {"qty": "0.31", "unit": "kg"},
    "general_instructions": [
        "ALL DIMENSIONS IN MILLIMETERS UNLESS OTHERWISE SPECIFIED",
        "BREAK ALL SHARP EDGES 0.2 MAX",
        "SURFACE FINISH 1.6 MICRON UNLESS OTHERWISE SPECIFIED",
    ],
    "environment_requirements": [
        "ESD CONTROLLED HANDLING REQUIRED",
    ],
    "bom_items": [],
    "machining_processes": [
        {
            "step_no": "10",
            "name_en": "ROUGH MILL",
            "name_he": "כירסום גס",
            "details": "STOCK: 60 x 80 x 12 mm. Leave 0.5 mm finish allowance.",
        },
        {
            "step_no": "20",
            "name_en": "FINISH MILL",
            "name_he": "כירסום גימור",
            "details": "Finish all surfaces to 1.6 micron Ra.",
        },
        {
            "step_no": "30",
            "name_en": "DEBURR",
            "name_he": "הסרת גרדים",
            "details": "Manual deburr; break all sharp edges 0.2 mm max.",
        },
    ],
    "welding_processes": [],
    "heat_treatment_processes": [],
    "coating_processes": [
        {
            "step_no": "40",
            "type": "CHROMATE CONVERSION",
            "type_he": "ציפוי כרומט",
            "name": "Class 1A clear chromate",
            "standard": "MIL-DTL-5541F",
            "thickness": "",
            "rohs": False,
            "color": "CLEAR",
        },
    ],
    "painting_processes": [
        {
            "step_no": "50",
            "type": "PRIMER",
            "type_he": "פריימר אפוקסי",
            "name": "Two-component epoxy primer",
            "standard": "MIL-PRF-23377K",
            "thickness": "20-30 microns",
            "rohs": True,
            "color": "GREEN",
        },
        {
            "step_no": "60",
            "type": "TOPCOAT",
            "type_he": "צבע עליון פוליאוריתן",
            "name": "Polyurethane topcoat per MIL-PRF-85285",
            "standard": "MIL-PRF-85285E",
            "thickness": "50-75 microns",
            "rohs": True,
            "color": "RAL 7035 LIGHT GREY",
        },
    ],
    "ndt_processes": [
        {
            "step_no": "70",
            "name_en": "FLUORESCENT PENETRANT INSPECTION",
            "name_he": "בדיקה פלואורסצנטית חודרת",
            "details": "Type I, Method C, Sensitivity Level 3 per ASTM E1417.",
        },
    ],
    "inspection_processes": [
        {
            "step_no": "80",
            "name_en": "DIMENSIONAL INSPECTION",
            "name_he": "בדיקת מימדים",
            "details": "100% per drawing, CMM report required.",
        },
        {
            "step_no": "90",
            "name_en": "VISUAL INSPECTION",
            "name_he": "בדיקה ויזואלית",
            "details": "Per ASTM E1417 acceptance criteria.",
        },
    ],
    "final_approval": [
        {
            "step_no": "100",
            "name_en": "QA STAMP + SERVICEABILITY TAG",
            "name_he": "חותמת QA + תג כשירות",
            "details": "Approved by authorized inspector.",
        },
    ],
    "additional_processes": [],
    "packaging_notes": {
        "he": "אריזה אנטי-סטטית בשקית ESD נפרדת. סימון חיצוני: P/N, REV, S/N.",
        "en": "Pack in individual ESD bag. Outer marking: P/N, REV, S/N.",
    },
    "standards": [
        "AMS-QQ-A-250/11",
        "MIL-DTL-5541F",
        "MIL-PRF-23377K",
        "MIL-PRF-85285E",
        "ASTM E1417",
        "RAL 7035",
    ],
    "notes": (
        "1. ALL DIMENSIONS IN MILLIMETERS.\n"
        "2. MATERIAL PER AMS-QQ-A-250/11; ALTERNATIVE PER AMS-QQ-A-250/12.\n"
        "3. CHROMATE CONVERSION COATING PER MIL-DTL-5541F CLASS 1A.\n"
        "4. PRIMER + TOPCOAT PER MIL-PRF-23377 + MIL-PRF-85285 RAL 7035.\n"
        "5. FPI PER ASTM E1417 TYPE I METHOD C SENS LEVEL 3.\n"
        "6. ESD HANDLING REQUIRED."
    ),
    "_ocr_used": True,
    "_validation_warnings": [
        {
            "type": "POSSIBLE_OBSOLETE_SPEC",
            "severity": "MEDIUM",
            "source": "material",
            "value": "QQ-A-250/11 (formerly)",
            "message": (
                "החומר מציין תקן QQ-A- ישן שהוחלף ב-AMS-QQ-A-. "
                "זוהה ככינוי 'formerly' — בדקי שהיצרן משתמש בתקן הנוכחי."
            ),
        },
        {
            "type": "PACKING_NOTE",
            "severity": "LOW",
            "source": "packaging",
            "value": "ESD bag + outer marking",
            "message": "אריזת ESD נדרשת — ודאי שצוות האריזה מעודכן.",
        },
    ],
    "_cost_info": {
        "input_tokens": 4823,
        "output_tokens": 1456,
        "total_cost_usd": 0.0341,
        "total_cost_ils": 0.124,
        "stages": [
            {
                "stage": "assembly_stage_1_basic",
                "model": "gpt-4o",
                "input_tokens": 2412,
                "output_tokens": 689,
                "total_cost_usd": 0.0153,
            },
            {
                "stage": "assembly_stage_2_full",
                "model": "gpt-4o",
                "input_tokens": 2411,
                "output_tokens": 767,
                "total_cost_usd": 0.0188,
            },
        ],
    },
    "_demo": True,
}


def get_demo_result() -> dict:
    """החזר עותק עמוק של תוצאת הדמו — בטוח לעריכה ע"י ה-UI."""
    return deepcopy(_DEMO_RESULT)


def is_demo_result(result: dict | None) -> bool:
    """בדיקה אם תוצאה הגיעה ממצב דמו (להצגת באנר מתאים)."""
    return bool(result and result.get("_demo"))
