"""
Unit tests ל-core.text_utils — ניקוי טקסט, נרמול ביטויי OCR, ומיפויי CAGE/לקוח.

הרצה:
    pytest tests/test_text_utils.py -v
"""
import pytest

from core.text_utils import (
    CAGE_TO_CUSTOMER,
    CUSTOMER_TO_DEFAULT_CAGE,
    clean_bom_description,
    clean_bom_items_in_place,
    clean_cage_code,
    deduplicate_repeated_phrase,
    infer_cage_from_customer,
    infer_customer_from_cage,
    normalize_customer_in_place,
    normalize_customer_name,
    normalize_known_phrases,
    normalize_known_phrases_in_place,
)


# ─────────────────────────────────────────────────────────────────
# deduplicate_repeated_phrase — הסרת חזרות OCR
# ─────────────────────────────────────────────────────────────────
class TestDeduplicateRepeatedPhrase:
    def test_simple_word_repetition(self):
        assert deduplicate_repeated_phrase("HEAD HEAD HEAD HEAD BOLT") == "HEAD BOLT"

    def test_phrase_repetition(self):
        text = "SCREW NOM. SIZE 0.218 NOM. SIZE 0.218 NOM. SIZE 0.218"
        result = deduplicate_repeated_phrase(text)
        # ההופעה הראשונה של "NOM. SIZE 0.218" נשארת
        assert result.count("NOM. SIZE 0.218") == 1
        assert "SCREW" in result

    def test_no_repetition_unchanged(self):
        text = "JUST A NORMAL SENTENCE"
        assert deduplicate_repeated_phrase(text) == text

    def test_empty_string(self):
        assert deduplicate_repeated_phrase("") == ""

    def test_none_returns_empty(self):
        assert deduplicate_repeated_phrase(None) == ""  # type: ignore[arg-type]

    def test_two_repetitions_below_threshold(self):
        # min_repeat=3 → שתי הופעות לא מספיק כדי להפעיל ניקוי
        text = "WORD WORD"
        assert deduplicate_repeated_phrase(text, min_repeat=3) == text

    def test_custom_min_repeat(self):
        text = "X X X"
        # min_repeat=2 → צריך לדחוס
        assert deduplicate_repeated_phrase(text, min_repeat=2) == "X"


# ─────────────────────────────────────────────────────────────────
# clean_bom_description
# ─────────────────────────────────────────────────────────────────
class TestCleanBomDescription:
    def test_collapses_whitespace(self):
        assert clean_bom_description("HELLO    WORLD") == "HELLO WORLD"

    def test_strips_outer_whitespace(self):
        assert clean_bom_description("  HELLO  ") == "HELLO"

    def test_dedup_and_whitespace(self):
        # שני הניקויים בשרשור
        text = "ITEM   ITEM   ITEM   X"
        result = clean_bom_description(text)
        assert result == "ITEM X"

    def test_empty_string(self):
        assert clean_bom_description("") == ""


# ─────────────────────────────────────────────────────────────────
# normalize_known_phrases — תיקוני OCR מוכרים
# ─────────────────────────────────────────────────────────────────
class TestNormalizeKnownPhrases:
    @pytest.mark.parametrize("input_text,expected_substr", [
        # Z0 SQUEGLIA family
        ("ZQSQLAND NQE VALUE", "Z0 SQUEGLIA INDEX"),
        ("ZQ SQUEGLIA INDEX", "Z0 SQUEGLIA"),
        ("ZO SQUEGLIA", "Z0 SQUEGLIA"),
        # SQUEGLIA misspellings
        ("USE SUGELIA METHOD", "SQUEGLIA"),
        ("USE SUQEILA METHOD", "SQUEGLIA"),
        # AMS-C-26074 OCR error
        ("V25.4 AMS-C-26074", "SAE-AMS-C-26074"),
        # TO-prefix removal
        ("ACC. TO PS-DOC0002945", "PS-DOC"),
        ("ACC. TO RAFDOCS", "RAFDOCS"),
    ])
    def test_normalizations(self, input_text, expected_substr):
        result, corrections = normalize_known_phrases(input_text)
        assert expected_substr in result
        assert corrections  # תיקונים לא ריקים

    def test_no_correction_keeps_text(self):
        text = "PLAIN TEXT WITH NO OCR ERRORS"
        result, corrections = normalize_known_phrases(text)
        assert result == text
        assert corrections == []

    def test_empty_text(self):
        result, corrections = normalize_known_phrases("")
        assert result == ""
        assert corrections == []

    def test_ps_oo_to_ps_00(self):
        # PS5OO100 → PS500100 (OCR קרא 0 כ-O)
        result, _ = normalize_known_phrases("CHECK PS5OO100 SPEC")
        assert "PS500100" in result

    def test_pss_prefix_to_ps5(self):
        # PSSOO100 → PS500100 (S→5 + OO→00)
        result, _ = normalize_known_phrases("PSSOO100")
        assert "PS500100" in result


# ─────────────────────────────────────────────────────────────────
# normalize_known_phrases_in_place — נרמול רקורסיבי
# ─────────────────────────────────────────────────────────────────
class TestNormalizeKnownPhrasesInPlace:
    def test_normalizes_strings_in_dict(self):
        result = {
            "field1": "ZQSQLAND",
            "field2": "PLAIN",
        }
        corrections = normalize_known_phrases_in_place(result)
        assert "Z0 SQUEGLIA" in result["field1"]
        assert result["field2"] == "PLAIN"
        assert len(corrections) >= 1

    def test_normalizes_nested_lists_and_dicts(self):
        result = {
            "items": [
                {"description": "USE SUGELIA"},
                {"description": "PLAIN"},
            ],
        }
        normalize_known_phrases_in_place(result)
        assert result["items"][0]["description"] == "USE SQUEGLIA"

    def test_skips_underscore_keys(self):
        # מפתחות פנימיים (_xxx) צריכים להישאר ללא שינוי
        result = {"_internal": "ZQSQLAND", "public": "ZQSQLAND"}
        normalize_known_phrases_in_place(result)
        assert result["_internal"] == "ZQSQLAND"
        assert "Z0 SQUEGLIA" in result["public"]

    def test_dedups_correction_messages(self):
        result = {"a": "ZQSQLAND", "b": "ZQSQLAND", "c": "ZQSQLAND"}
        corrections = normalize_known_phrases_in_place(result)
        # אותו תיקון מופיע 3 פעמים אבל נספר פעם אחת ברשימה
        unique_descriptions = {c.split(" ×")[0] for c in corrections}
        # אין כפילויות במחרוזות תיקון אחרי dedup
        assert len(corrections) == len(unique_descriptions)

    def test_non_dict_returns_empty(self):
        assert normalize_known_phrases_in_place("not a dict") == []  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# clean_cage_code
# ─────────────────────────────────────────────────────────────────
class TestCleanCageCode:
    @pytest.mark.parametrize("input_cage,expected", [
        # Valid CAGE codes
        ("0772A", "0772A"),
        ("1410A", "1410A"),
        ("1GYX", "1GYX"),
        ("1931", "1931"),
        ("36035", "36035"),
        # Whitespace + lowercase
        ("  1931  ", "1931"),
        ("1410a", "1410A"),
        # Invalid (special chars) — OCR errors
        ("1!1", ""),
        ("1@31", ""),
        ("AB-CD", ""),
        ("XY YZ", ""),
        # Too short / too long
        ("AB", ""),
        ("ABCDEFG", ""),
        # Empty
        ("", ""),
    ])
    def test_validation(self, input_cage, expected):
        assert clean_cage_code(input_cage) == expected


# ─────────────────────────────────────────────────────────────────
# infer_customer_from_cage — מילוי customer לפי CAGE
# ─────────────────────────────────────────────────────────────────
class TestInferCustomerFromCage:
    def test_fills_customer_from_known_cage(self):
        s = {"customer": "", "cage_code": "1931"}
        assert infer_customer_from_cage(s) is True
        assert "RAFAEL" in s["customer"]

    def test_existing_customer_unchanged(self):
        s = {"customer": "Some Existing", "cage_code": "1931"}
        assert infer_customer_from_cage(s) is False
        assert s["customer"] == "Some Existing"

    def test_unknown_cage_no_change(self):
        s = {"customer": "", "cage_code": "ZZZZZ"}
        assert infer_customer_from_cage(s) is False
        assert s["customer"] == ""

    def test_invalid_cage_cleaned(self):
        # CAGE לא תקין מנוקה ל-"" + לא מתבצעת השלמה
        s = {"customer": "", "cage_code": "1!1"}
        assert infer_customer_from_cage(s) is False
        assert s["cage_code"] == ""

    def test_lowercase_cage_resolves_customer(self):
        # "0772a" מזוהה במפה (case-insensitive lookup) → customer מתמלא.
        # ⚠️ ה-cage_code עצמו נשאר באותיות קטנות — clean_cage_code "מתקן"
        # רק כש-CAGE פגום (תווים מיוחדים), לא רק מטעמי casing.
        s = {"customer": "", "cage_code": "0772a"}
        assert infer_customer_from_cage(s) is True
        assert "Elop" in s["customer"] or "ELOP" in s["customer"].upper()

    def test_non_dict_returns_false(self):
        assert infer_customer_from_cage("not a dict") is False  # type: ignore[arg-type]

    def test_all_known_cages_resolve(self):
        # כל CAGE שנמצא במפה צריך להחזיר customer לא-ריק
        for cage in CAGE_TO_CUSTOMER:
            s = {"customer": "", "cage_code": cage}
            infer_customer_from_cage(s)
            assert s["customer"], f"CAGE {cage} did not resolve"


# ─────────────────────────────────────────────────────────────────
# infer_cage_from_customer — reverse lookup
# ─────────────────────────────────────────────────────────────────
class TestInferCageFromCustomer:
    def test_fills_cage_from_known_customer(self):
        s = {
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "cage_code": "",
        }
        assert infer_cage_from_customer(s) is True
        assert s["cage_code"] == "1931"

    def test_existing_cage_unchanged(self):
        s = {
            "customer": "RAFAEL Advanced Defense Systems Ltd.",
            "cage_code": "9999",
        }
        assert infer_cage_from_customer(s) is False
        assert s["cage_code"] == "9999"

    def test_unknown_customer_no_change(self):
        s = {"customer": "Random Vendor", "cage_code": ""}
        assert infer_cage_from_customer(s) is False
        assert s["cage_code"] == ""

    def test_all_known_customers_resolve(self):
        for customer, expected_cage in CUSTOMER_TO_DEFAULT_CAGE.items():
            s = {"customer": customer, "cage_code": ""}
            assert infer_cage_from_customer(s) is True
            assert s["cage_code"] == expected_cage


# ─────────────────────────────────────────────────────────────────
# normalize_customer_name — איחוד aliases
# ─────────────────────────────────────────────────────────────────
class TestNormalizeCustomerName:
    @pytest.mark.parametrize("input_name,expected", [
        # EL-OR variations
        ("EL OR Systems Ltd", "EL-OR Systems Ltd."),
        ("EL-OR SYSTEMS LTD.", "EL-OR Systems Ltd."),
        ("ELOR SYSTEMS", "EL-OR Systems Ltd."),
        # Elbit Elop variations
        ("ELOP", "Elbit Systems Electro-Optics Elop Ltd."),
        ("ELBIT ELOP", "Elbit Systems Electro-Optics Elop Ltd."),
        # RAFAEL
        ("RAFAEL", "RAFAEL Advanced Defense Systems Ltd."),
        # IAI
        ("IAI", "Israel Aerospace Industries"),
        # Bird
        ("BIRD AEROSYSTEMS", "BIRD Aerosystems Ltd."),
    ])
    def test_aliases(self, input_name, expected):
        assert normalize_customer_name(input_name) == expected

    def test_unknown_name_unchanged(self):
        assert normalize_customer_name("Random Vendor LLC") == "Random Vendor LLC"

    def test_empty_returns_empty(self):
        assert normalize_customer_name("") == ""

    def test_strips_outer_whitespace(self):
        assert normalize_customer_name("  Random Co  ") == "Random Co"


class TestNormalizeCustomerInPlace:
    def test_changes_when_alias(self):
        s = {"customer": "ELOP"}
        assert normalize_customer_in_place(s) is True
        assert "Elop" in s["customer"]

    def test_no_change_when_canonical(self):
        s = {"customer": "RAFAEL Advanced Defense Systems Ltd."}
        assert normalize_customer_in_place(s) is False

    def test_empty_customer(self):
        s = {"customer": ""}
        assert normalize_customer_in_place(s) is False


# ─────────────────────────────────────────────────────────────────
# clean_bom_items_in_place
# ─────────────────────────────────────────────────────────────────
class TestCleanBomItemsInPlace:
    def test_cleans_descriptions(self):
        items = [
            {"description": "ITEM   ITEM   ITEM   X"},  # trio + spaces
            {"description": "PLAIN"},
        ]
        fixed = clean_bom_items_in_place(items)
        assert fixed == 1  # רק הראשון השתנה
        assert items[0]["description"] == "ITEM X"
        assert items[1]["description"] == "PLAIN"

    def test_empty_list(self):
        assert clean_bom_items_in_place([]) == 0

    def test_skip_non_dict_items(self):
        items = [{"description": "OK"}, "not a dict", None]
        # לא קורס + מחזיר 0 (אף אחד לא הצריך תיקון)
        assert clean_bom_items_in_place(items) == 0

    def test_missing_description_field(self):
        items = [{"part_number": "ABC"}]  # אין description
        # לא קורס; description ריק → cleaned ריק → אין תיקון
        assert clean_bom_items_in_place(items) == 0
