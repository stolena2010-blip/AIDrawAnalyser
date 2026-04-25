"""
Unit tests ל-core.validators — שכבת ולידציה לזיהוי הזיות.

הרצה:
    pytest tests/test_validators.py -v
"""
import pytest

from core.validators import (
    _normalize_standard,
    run_all_validators,
    validate_all_paint_brands,
    validate_coating_classification,
    validate_customer_internal_specs,
    validate_customer_prefix_consistency,
    validate_packing_note,
    validate_paint_brand,
    validate_ral_codes,
    validate_standards,
    validate_surface_prep_and_post_process,
)


# ─────────────────────────────────────────────────────────────────
# validate_ral_codes
# ─────────────────────────────────────────────────────────────────
class TestValidateRalCodes:
    def test_valid_ral_no_warning(self):
        report = {
            "painting_processes": [
                {"step_no": "10", "name": "PAINT RAL 9005", "standard": ""}
            ],
            "standards": [],
        }
        assert validate_ral_codes(report) == []

    def test_invalid_ral_flagged(self):
        report = {
            "painting_processes": [
                {"step_no": "10", "name": "PAINT RAL 9999", "standard": ""}
            ],
            "standards": [],
        }
        warnings = validate_ral_codes(report)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "INVALID_RAL"
        assert warnings[0]["severity"] == "CRITICAL"
        assert "9999" in warnings[0]["value"]

    def test_3_digit_ral_normalized_to_4(self):
        # "RAL 100" → "0100" — לא קיים → CRITICAL
        # אבל "RAL 9005" → "9005" — קיים, OK
        report = {
            "painting_processes": [],
            "standards": ["RAL 9005"],
        }
        assert validate_ral_codes(report) == []

    def test_ral_in_standards_field(self):
        report = {
            "painting_processes": [],
            "standards": ["RAL 8888"],  # invalid
        }
        warnings = validate_ral_codes(report)
        assert len(warnings) == 1
        assert warnings[0]["source"] == "standards"

    def test_no_ral_no_warning(self):
        report = {"painting_processes": [{"name": "PAINT GREEN"}], "standards": []}
        assert validate_ral_codes(report) == []


# ─────────────────────────────────────────────────────────────────
# validate_paint_brand
# ─────────────────────────────────────────────────────────────────
class TestValidatePaintBrand:
    def test_known_brand_returns_none(self):
        # מותג מוכר → None (תקין)
        assert validate_paint_brand("EPOXY PRIMER BY TAMBOUR") is None

    def test_known_brand_no_by_pattern(self):
        # מותג מוכר נמצא בטקסט גם בלי "BY"
        assert validate_paint_brand("TAMBOUR EPOXY 5500") is None

    def test_unknown_brand_in_by_pattern(self):
        # תבנית "X BY Y" עם מותג לא מוכר → אזהרה
        warning = validate_paint_brand("PAINT BY UNKNOWNVENDOR")
        assert warning is not None
        assert warning["type"] == "UNKNOWN_PAINT_BRAND"
        assert warning["severity"] == "HIGH"
        assert "UNKNOWNVENDOR" in warning["value"]

    def test_no_by_pattern_returns_none(self):
        # אין תבנית "BY" — אין על מה להתריע
        assert validate_paint_brand("PAINT FINISH") is None

    def test_empty_text(self):
        assert validate_paint_brand("") is None


class TestValidateAllPaintBrands:
    def test_collects_warnings_from_all_processes(self):
        report = {
            "painting_processes": [
                {"step_no": "10", "name": "PAINT BY UNKNOWN1"},
                {"step_no": "20", "name": "PAINT BY TAMBOUR"},
                {"step_no": "30", "name": "PAINT BY UNKNOWN2"},
            ]
        }
        warnings = validate_all_paint_brands(report)
        assert len(warnings) == 2  # רק שני הלא-מוכרים

    def test_empty_painting_processes(self):
        report = {"painting_processes": []}
        assert validate_all_paint_brands(report) == []


# ─────────────────────────────────────────────────────────────────
# validate_coating_classification
# ─────────────────────────────────────────────────────────────────
class TestValidateCoatingClassification:
    def test_primer_in_coating_flagged(self):
        coatings = [{"step_no": "10", "name": "EPOXY PRIMER"}]
        warnings = validate_coating_classification(coatings)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "MISCLASSIFIED_COATING"
        assert warnings[0]["severity"] == "HIGH"

    def test_actual_coating_with_primer_keyword_ok(self):
        # כש-MIL-DTL-16232 מופיע (תקן ציפוי אמיתי), PRIMER לא מסמן
        coatings = [{"step_no": "10", "name": "EPOXY PRIMER MIL-DTL-16232"}]
        # `is_actual` נכון, ולכן is_primer לבד לא מספיק לסימון
        warnings = validate_coating_classification(coatings)
        assert warnings == []

    def test_masking_flagged_medium(self):
        coatings = [{"step_no": "20", "name": "MASKING REQUIRED"}]
        warnings = validate_coating_classification(coatings)
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "MEDIUM"

    def test_legitimate_coating_no_warning(self):
        coatings = [{"step_no": "10", "name": "ZINC PLATING PER QQ-Z-325"}]
        assert validate_coating_classification(coatings) == []

    def test_empty_list(self):
        assert validate_coating_classification([]) == []


# ─────────────────────────────────────────────────────────────────
# validate_packing_note
# ─────────────────────────────────────────────────────────────────
class TestValidatePackingNote:
    def test_known_template_no_warning(self):
        text = ("PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE "
                "DURING PROCESS, STORAGE AND SHIPMENT")
        assert validate_packing_note(text) is None

    def test_explicit_no_packing_marker_info(self):
        warning = validate_packing_note("[NO_PACKING_REQUIREMENT_IN_DRAWING]")
        assert warning is not None
        assert warning["type"] == "NO_PACKING_REQUIREMENT_IN_DRAWING"
        assert warning["severity"] == "INFO"

    def test_empty_returns_missing(self):
        warning = validate_packing_note("")
        assert warning is not None
        assert warning["type"] == "MISSING_PACKING"
        assert warning["severity"] == "MEDIUM"

    def test_too_short_returns_missing(self):
        warning = validate_packing_note("OK")
        assert warning is not None
        assert warning["type"] == "MISSING_PACKING"

    def test_unusual_text_flagged(self):
        # טקסט ארוך אך לא דומה לתבניות מוכרות
        warning = validate_packing_note(
            "USE COLORED SOAP AND DANCE TWICE AROUND THE BOX BEFORE SHIPPING"
        )
        assert warning is not None
        assert warning["type"] == "UNUSUAL_PACKING_NOTE"
        assert warning["severity"] == "HIGH"

    def test_dict_with_en_field(self):
        d = {"en": "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE "
                   "DURING PROCESS, STORAGE AND SHIPMENT"}
        assert validate_packing_note(d) is None

    def test_dict_with_he_fallback(self):
        d = {"en": "", "he": ""}
        warning = validate_packing_note(d)
        assert warning is not None
        assert warning["type"] == "MISSING_PACKING"


# ─────────────────────────────────────────────────────────────────
# validate_customer_prefix_consistency
# ─────────────────────────────────────────────────────────────────
class TestValidateCustomerPrefixConsistency:
    def test_bas_with_bird_no_warning(self):
        # PN BAS-prefix + customer="BIRD..." → תאם
        report = {"part_number": "BAS12345", "customer": "BIRD Aerosystems Ltd."}
        assert validate_customer_prefix_consistency(report) == []

    def test_bas_with_rafael_flagged(self):
        # PN BAS-prefix אבל customer="RAFAEL" → אי-עקביות (HIGH)
        report = {"part_number": "BAS12345", "customer": "RAFAEL Advanced Defense"}
        warnings = validate_customer_prefix_consistency(report)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "CUSTOMER_PREFIX_MISMATCH"
        assert warnings[0]["severity"] == "HIGH"

    def test_pwrl_with_rafael_no_warning(self):
        # PWRL prefix → RAFAEL → תאם (קידומת ארוכה תופסת לפני "P" קצרה)
        report = {
            "part_number": "PWRL30512A",
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
        }
        assert validate_customer_prefix_consistency(report) == []

    def test_unknown_prefix_no_warning(self):
        # קידומת לא במפה → לא בודקים
        report = {"part_number": "ZZZ12345", "customer": "Anyone"}
        assert validate_customer_prefix_consistency(report) == []

    def test_empty_pn_no_warning(self):
        report = {"part_number": "", "customer": "RAFAEL"}
        assert validate_customer_prefix_consistency(report) == []

    def test_empty_customer_no_warning(self):
        report = {"part_number": "BAS12345", "customer": ""}
        assert validate_customer_prefix_consistency(report) == []


# ─────────────────────────────────────────────────────────────────
# validate_customer_internal_specs
# ─────────────────────────────────────────────────────────────────
class TestValidateCustomerInternalSpecs:
    def test_kretos_internal_spec_flagged_info(self):
        report = {
            "customer": "KRETOS General Microwave",
            "standards": ["I-630028", "MIL-STD-130"],
        }
        warnings = validate_customer_internal_specs(report)
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "INFO"
        assert "I-630028" in warnings[0]["value"]

    def test_iai_5902_pattern(self):
        report = {
            "customer": "Israel Aerospace Industries",
            "standards": ["5902Y004"],
        }
        warnings = validate_customer_internal_specs(report)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "CUSTOMER_INTERNAL_SPEC"

    def test_unknown_customer_no_warning(self):
        report = {"customer": "Random LLC", "standards": ["I-630028"]}
        assert validate_customer_internal_specs(report) == []

    def test_empty_customer_no_warning(self):
        report = {"customer": "", "standards": ["I-630028"]}
        assert validate_customer_internal_specs(report) == []

    def test_no_matches_in_standards(self):
        # יש customer מוכר אבל standards לא תואמים את ה-pattern
        report = {
            "customer": "KRETOS General Microwave",
            "standards": ["MIL-STD-130", "ASTM A123"],
        }
        assert validate_customer_internal_specs(report) == []


# ─────────────────────────────────────────────────────────────────
# validate_surface_prep_and_post_process
# ─────────────────────────────────────────────────────────────────
class TestValidateSurfacePrepAndPostProcess:
    def test_pickling_in_notes_missing_in_processes(self):
        report = {
            "notes": "PICKLING REQUIRED PER MIL-STD-XXX",
            "additional_processes": [],
        }
        warnings = validate_surface_prep_and_post_process(report)
        assert any(w["type"] == "MISSING_SURFACE_PREP" for w in warnings)

    def test_pickling_in_both_no_warning(self):
        report = {
            "notes": "PICKLING REQUIRED",
            "additional_processes": [
                {"name_en": "Pickling Treatment", "name_he": "צריבה"},
            ],
        }
        warnings = validate_surface_prep_and_post_process(report)
        assert not any(w["type"] == "MISSING_SURFACE_PREP" for w in warnings)

    def test_hydrogen_embrittlement_missing(self):
        report = {
            "notes": "HYDROGEN EMBRITTLEMENT RELIEF AT 191C",
            "additional_processes": [],
        }
        warnings = validate_surface_prep_and_post_process(report)
        assert any(w["type"] == "MISSING_POST_PROCESS" for w in warnings)

    def test_no_keywords_no_warning(self):
        report = {"notes": "PAINT GREEN", "additional_processes": []}
        assert validate_surface_prep_and_post_process(report) == []


# ─────────────────────────────────────────────────────────────────
# _normalize_standard — נרמול לפני השוואה
# ─────────────────────────────────────────────────────────────────
class TestNormalizeStandard:
    @pytest.mark.parametrize("input_std,expected", [
        ("PS- 111.21", "PS-111.21"),       # רווח אחרי מקף
        ("Y14. 6", "Y14.6"),                # רווח אחרי נקודה
        ("MIL-STD-130", "MIL-STD-130"),    # תקין
        ("  ASME  Y14  ", "ASME Y14"),     # רווחים מיותרים
        ("", ""),
    ])
    def test_normalization(self, input_std, expected):
        assert _normalize_standard(input_std) == expected


# ─────────────────────────────────────────────────────────────────
# validate_standards — זיהוי הזיות תקנים
# ─────────────────────────────────────────────────────────────────
class TestValidateStandards:
    @pytest.mark.parametrize("std", [
        # תקנים תקינים — לא צריכים לסמן
        "MIL-STD-130", "MIL-DTL-5541", "AMS 2700", "AMS-C-26074",
        "ASTM A123", "ASME Y14.5", "QQ-P-416", "FED-STD-595",
        "PS-111", "RAFDOCS", "TILDOCS-1234", "AWS D1.1",
        "ANSI Y14.5", "ISO 9001", "EN 10204", "DIN 933",
        "BS 4882", "SAE AMS-QQ-P-416", "IPC-A-610", "JEDEC J-STD-020",
        "UL 94", "CSA-Z245", "MS33540", "AN-310-1", "NASA-STD-5008",
        "NACE MR0175", "EN ISO 9001", "TT-C-490", "AISI 4340",
        "UNS S30400", "RAFAEL PROCEDURE 18.00.10", "P.S.231900",
        "FED. STD. 595A", "A-A-56032", "ANSI/ASQ Z1.4",
    ])
    def test_known_prefixes_not_flagged(self, std):
        report = {"standards": [std]}
        warnings = validate_standards(report)
        assert warnings == [], f"{std!r} שלא היה אמור להתריע — {warnings!r}"

    @pytest.mark.parametrize("ignored", [
        "ISO STANDARDS", "MIL STANDARDS", "APPLICABLE STANDARDS",
        "VT", "PT", "MT", "UT", "RT", "GTAW", "GMAW", "TIG", "MIG",
        "WPS", "RoHS", "RoHS COMPLIANT", "RoHS DIRECTIVE",
        "REACH", "REACH COMPLIANCE", "SQUEGLIA",
    ])
    def test_ignore_list_not_flagged(self, ignored):
        report = {"standards": [ignored]}
        assert validate_standards(report) == []

    def test_hallucinated_standard_flagged(self):
        # קידומת לא קיימת (AWI אינו גוף תקינה)
        report = {"standards": ["AWI-STD-1916"]}
        warnings = validate_standards(report)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "SUSPICIOUS_STANDARD"
        assert warnings[0]["severity"] == "HIGH"

    def test_ral_color_not_flagged(self):
        # קוד RAL הוא צבע — לא תקן, אבל גם לא הזיה. דילוג.
        report = {"standards": ["RAL 9005"]}
        assert validate_standards(report) == []

    def test_customer_internal_spec_not_flagged(self):
        # KRETOS עם I-630028 — קוד פנימי, לא הזיה
        report = {
            "customer": "KRETOS General Microwave",
            "standards": ["I-630028"],
        }
        assert validate_standards(report) == []

    def test_normalized_ps_with_space_not_flagged(self):
        # "PS- 111.21" עם רווח אחרי מקף → ינורמל ל-"PS-111.21" → תקין
        report = {"standards": ["PS- 111.21"]}
        assert validate_standards(report) == []

    def test_empty_standards(self):
        assert validate_standards({"standards": []}) == []

    def test_skip_empty_strings(self):
        # ערכים ריקים בתוך הרשימה לא צריכים לסמן
        report = {"standards": ["", None, "MIL-STD-130"]}
        assert validate_standards(report) == []


# ─────────────────────────────────────────────────────────────────
# run_all_validators — אינטגרציה
# ─────────────────────────────────────────────────────────────────
class TestRunAllValidators:
    def test_clean_report_no_warnings(self):
        report = {
            "part_number": "BP70534A",
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "painting_processes": [],
            "coating_processes": [],
            "additional_processes": [],
            "standards": ["MIL-STD-130"],
            "notes": "",
            "packaging_notes": (
                "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE "
                "DURING PROCESS, STORAGE AND SHIPMENT"
            ),
        }
        assert run_all_validators(report) == []

    def test_collects_multiple_warning_types(self):
        report = {
            "part_number": "BAS12345",                    # → CUSTOMER_PREFIX_MISMATCH
            "customer": "RAFAEL",
            "painting_processes": [{"step_no": "10", "name": "PAINT RAL 9999"}],  # INVALID_RAL
            "coating_processes": [{"step_no": "20", "name": "EPOXY PRIMER"}],     # MISCLASSIFIED
            "additional_processes": [],
            "standards": ["AWI-STD-1916"],                # SUSPICIOUS_STANDARD
            "notes": "",
            "packaging_notes": "",                        # MISSING_PACKING
        }
        warnings = run_all_validators(report)
        types = {w["type"] for w in warnings}
        assert "CUSTOMER_PREFIX_MISMATCH" in types
        assert "INVALID_RAL" in types
        assert "MISCLASSIFIED_COATING" in types
        assert "SUSPICIOUS_STANDARD" in types
        assert "MISSING_PACKING" in types

    def test_handles_minimal_report(self):
        # report עם רק שדות חיוניים — לא קורס
        report = {"packaging_notes": "[NO_PACKING_REQUIREMENT_IN_DRAWING]"}
        warnings = run_all_validators(report)
        # יוצאת רק ה-INFO על אריזה
        assert all(w["severity"] in {"INFO", "MEDIUM"} for w in warnings)
