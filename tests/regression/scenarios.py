"""
תרחישי regression — קלטים סינתטיים שמדמים דפוסים אמיתיים שראינו ב-batches.

לכל תרחיש: filename + stage1 (raw) + stage2 (raw) + expected (אחרי post-process).
ראה [README.md](README.md) להוספת תרחישים חדשים.
"""
from __future__ import annotations


SCENARIOS: dict[str, dict] = {
    # ─────────────────────────────────────────────────────────────
    # 1. RAFAEL drawing — OCR confusion 8↔B ב-PN, צריך תיקון משם הקובץ
    # ─────────────────────────────────────────────────────────────
    "rafael_ocr_confusion_8b": {
        "description": "OCR קרא 8 כ-B ב-BN80760B; reconcile חייב לתקן משם הקובץ",
        "filename": "_asm_temp_BN80760B-A-PD-bn80760b_a.pdf",
        "stage1": {
            "part_number": "BNB0760B",       # OCR error: 8→B
            "drawing_number": "BNB0760B",
            "revision": "A",
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "cage_code": "1931",
            "material": "AL 6061-T6",
            "assembly_role": "PART",
            "bom_items": [],
        },
        "stage2": {
            "standards": ["MIL-STD-130", "QQ-P-416"],
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {
                "en": "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE "
                       "DURING PROCESS, STORAGE AND SHIPMENT",
                "he": "",
            },
        },
        "expected": {
            "part_number": "BN80760B",       # תוקן
            "drawing_number": "BN80760B",    # גם DWG תוקן (היה זהה)
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "cage_code": "1931",
        },
    },

    # ─────────────────────────────────────────────────────────────
    # 2. Material formerly — צריך פיצול לשדה material_formerly
    # ─────────────────────────────────────────────────────────────
    "elbit_material_formerly": {
        "description": "MATERIAL מכיל '(FORMERLY ...)' — הפרדה לשדה נפרד",
        "filename": "_asm_temp_8554-3672-00-RevA.pdf",
        "stage1": {
            "part_number": "8554-3672-00",
            "drawing_number": "8554-3672-00",
            "revision": "A",
            "customer": "Elbit Systems Ltd.",
            "material": "AL 5052-H32 PER SAE-AMS-4016 (FORMERLY AMS QQ-A-250/8)",
            "material_formerly": "",
            "assembly_role": "PART",
            "bom_items": [],
        },
        "stage2": {
            "standards": [],
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {"en": "[NO_PACKING_REQUIREMENT_IN_DRAWING]", "he": ""},
        },
        "expected": {
            "part_number": "8554-3672-00",
            "material": "AL 5052-H32 PER SAE-AMS-4016",  # נוקה
            "material_formerly": "AMS QQ-A-250/8",
            "customer": "Elbit Systems Ltd.",
        },
    },

    # ─────────────────────────────────────────────────────────────
    # 3. KRETOS internal spec — לא צריך להופיע כ-SUSPICIOUS_STANDARD
    # ─────────────────────────────────────────────────────────────
    "kretos_internal_spec_whitelisted": {
        "description": "I-630028 הוא קוד פנימי של KRETOS, לא צריך לסמן כהזיה",
        "filename": "_asm_temp_KRETOS-PART.pdf",
        "stage1": {
            "part_number": "ABC123456",
            "drawing_number": "ABC123456",
            "revision": "B",
            "customer": "KRETOS General Microwave",
            "cage_code": "2198A",
            "material": "STAINLESS STEEL 304",
            "assembly_role": "PART",
            "bom_items": [],
        },
        "stage2": {
            "standards": ["I-630028", "MIL-STD-130"],   # I-630028 = פנימי KRETOS
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {"en": "PACKING SHALL PREVENT CORROSION", "he": ""},
        },
        "expected": {
            "customer": "KRETOS General Microwave",
            # ה-validators לא צריכים לסמן I-630028 כ-SUSPICIOUS
        },
        "expected_warnings_must_not_contain": ["SUSPICIOUS_STANDARD"],
    },

    # ─────────────────────────────────────────────────────────────
    # 4. Salvage revision — "RC" צריך להיות מנוקה ל-"C"
    # ─────────────────────────────────────────────────────────────
    "salvage_mangled_revision": {
        "description": "OCR מיזג Rev עם ערך → 'RC' צריך להפוך ל-'C'",
        "filename": "_asm_temp_BP70534A.pdf",
        "stage1": {
            "part_number": "BP70534A",
            "drawing_number": "BP70534A",
            "revision": "RC",                # מולח OCR
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "material": "AL 6061",
            "assembly_role": "PART",
            "bom_items": [],
        },
        "stage2": {
            "standards": [],
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {"en": "PACKING SHALL PREVENT CORROSION", "he": ""},
        },
        "expected": {
            "revision": "C",
            "part_number": "BP70534A",
        },
    },

    # ─────────────────────────────────────────────────────────────
    # 5. Self-reference BOM — Parts List מצביע רק לעצמו → role=PART
    # ─────────────────────────────────────────────────────────────
    "self_ref_bom_classified_as_part": {
        "description": "BOM של פריט אחד עם אותו PN של השרטוט = PART, לא ASSEMBLY",
        "filename": "_asm_temp_BP70534A.pdf",
        "stage1": {
            "part_number": "BP70534A",
            "drawing_number": "BP70534A",
            "revision": "A",
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "material": "STEEL 4140",
            "assembly_role": "ASSEMBLY",     # שגוי — המודל סיווג כמכלול
            "bom_items": [
                {"item_no": 1, "part_number": "BP70534A", "qty": 1},
            ],
        },
        "stage2": {
            "standards": [],
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {"en": "PACKING SHALL PREVENT CORROSION", "he": ""},
        },
        "expected": {
            "assembly_role": "PART",         # תוקן
            "bom_items": [],                 # נוקה
        },
    },

    # ─────────────────────────────────────────────────────────────
    # 6. Customer alias — "ELOP" צריך להפוך לשם קנוני
    # ─────────────────────────────────────────────────────────────
    "customer_alias_normalization": {
        "description": "alias 'ELOP' → 'Elbit Systems Electro-Optics Elop Ltd.'",
        "filename": "_asm_temp_FTLS02009A.pdf",
        "stage1": {
            "part_number": "FTLS02009A",
            "drawing_number": "FTLS02009A",
            "revision": "C",
            "customer": "ELOP",              # alias קצר
            "cage_code": "",                 # ריק — צריך להתמלא מ-CAGE map
            "material": "AL 7075-T6",
            "assembly_role": "PART",
            "bom_items": [],
        },
        "stage2": {
            "standards": [],
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {"en": "PACKING SHALL PREVENT CORROSION", "he": ""},
        },
        "expected": {
            "customer": "Elbit Systems Electro-Optics Elop Ltd.",
            "cage_code": "0772A",            # מולא אוטומטית מ-CAGE_TO_DEFAULT
        },
    },

    # ─────────────────────────────────────────────────────────────
    # 7. PN with whitespace — צריך override משם הקובץ
    # ─────────────────────────────────────────────────────────────
    "pn_with_whitespace_override": {
        "description": "PN עם רווחים = הזיה ('YT35 MD ETG1242544') → override",
        "filename": "_asm_temp_ETG1242544-(157529).PDF",
        "stage1": {
            "part_number": "YT35 MD ETG1242544",   # יש רווחים → suspicious
            "drawing_number": "YT35 MD ETG1242544",
            "revision": "",
            "customer": "Israel Aerospace Industries",
            "material": "",
            "assembly_role": "PART",
            "bom_items": [],
        },
        "stage2": {
            "standards": [],
            "coating_processes": [],
            "painting_processes": [],
            "additional_processes": [],
            "packaging_notes": {"en": "[NO_PACKING_REQUIREMENT_IN_DRAWING]", "he": ""},
        },
        "expected": {
            "part_number": "ETG1242544",     # תוקן משם הקובץ
            "drawing_number": "ETG1242544",
        },
    },
}
