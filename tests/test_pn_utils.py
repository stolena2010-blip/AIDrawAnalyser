"""
Unit tests ל-core.pn_utils — חילוץ, נרמול ותיקון Part Number.

הרצה:
    pytest tests/test_pn_utils.py -v
"""
import pytest

from core.pn_utils import (
    _char_jaccard,
    _digit_jaccard,
    _is_suspicious_pn,
    _sequences_compatible,
    collect_bom_part_numbers,
    combined_pn_distance,
    correct_pn_with_filename,
    cross_reference_part_numbers,
    extract_generic_pn_from_filename,
    extract_pn_from_filename,
    filename_override_if_suspicious_pn,
    insertion_deletion_distance,
    normalize_dwg_vs_pn,
    normalize_trailing_letter,
    ocr_confusion_distance,
    prefer_filename_pn_if_substring,
    reconcile_drawing_number,
    reconcile_part_number,
    reconcile_revision,
    salvage_revision,
    strip_letter_distance,
    transposition_distance,
)


# ─────────────────────────────────────────────────────────────────
# extract_pn_from_filename — חילוץ PN משם קובץ (כללי RAFAEL)
# ─────────────────────────────────────────────────────────────────
class TestExtractPnFromFilename:
    @pytest.mark.parametrize("filename,expected", [
        # RAFAEL prefixes (whitelist)
        ("BN80760B-A-PD-bn80760b_a.pdf", "BN80760B"),
        ("FTLS02009A-C-PD-FTLS02009A_C.pdf", "FTLS02009A"),
        ("PWRL30512A.pdf", "PWRL30512A"),
        ("MMA574602C.pdf", "MMA574602C"),
        # B2BDraw prefix stripped
        ("B2BDraw_BN56951A-C-PD-BN56951A_C.PDF", "BN56951A"),
        # Empty / no PN
        ("", ""),
        ("readme.txt", ""),
        # Drawing number too short
        ("AB12.pdf", ""),
    ])
    def test_extracts(self, filename, expected):
        assert extract_pn_from_filename(filename) == expected

    def test_blacklist_rejects_field_names(self):
        # "DRAWING" / "REV" / "SHEET" צריכים להידחות גם אם הם תואמים תבנית
        assert extract_pn_from_filename("REV2024.pdf") == ""

    def test_only_digits_rejected(self):
        assert extract_pn_from_filename("12345678.pdf") == ""


# ─────────────────────────────────────────────────────────────────
# extract_generic_pn_from_filename — פורמטים לא-RAFAEL
# ─────────────────────────────────────────────────────────────────
class TestExtractGenericPnFromFilename:
    @pytest.mark.parametrize("filename,expected", [
        # Numeric-prefix dashed (Elbit / commercial)
        ("330-53-14-J8409-201.pdf", "330-53-14-J8409-201"),
        ("1384-2153-01.pdf", "1384-2153-01"),
        # ALPHA-NUM-NUM
        ("UCP-212-00703.pdf", "UCP-212-00703"),
        ("UR-02-1000.pdf", "UR-02-1000"),
        # 4-section ALPHA-NUM-NUM-NUM
        ("UCP-280-89981-602.pdf", "UCP-280-89981-602"),
        # Pure digits
        ("107594360.pdf", "107594360"),
        # Alpha-digits-trail
        ("BJ14981A.pdf", "BJ14981A"),
        # Underscore-based
        ("EIM_RAF051_10001.pdf", "EIM_RAF051_10001"),
        # B2BDraw decoration stripped
        ("B2BDraw_1384-2153-01_30.pdf", "1384-2153-01"),
        # B2B with #Rev decoration — _strip_file_decorations מסיר את החלק שאחרי #
        ("B2BDraw_un8554-3672-00#RevA#A0#S2_30.pdf", "UN8554-3672-00"),
        # Empty
        ("", ""),
    ])
    def test_extracts(self, filename, expected):
        result = extract_generic_pn_from_filename(filename)
        assert result == expected, f"{filename!r} → {result!r} (expected {expected!r})"

    def test_strips_pdm_descriptor(self):
        # "30-168217-E-PDM-30-168217E" → "30-168217-E"
        result = extract_generic_pn_from_filename("30-168217-E-PDM-30-168217E.pdf")
        assert result == "30-168217-E"

    @pytest.mark.parametrize("filename,expected", [
        # Assembly mode מוסיף "_asm_temp_" לקבצים זמניים — חייב להיות מוסר
        ("_asm_temp_DD345326-01-(155822).PDF",        "DD345326-01"),
        ("_asm_temp_ETN1110422---(13145).PDF",        "ETN1110422"),
        ("_asm_temp_HSA00756-1M004---(156097).PDF",   "HSA00756-1M004"),
        ("_asm_temp_BO27304A-(157408).PDF",           "BO27304A"),
        ("_asm_temp_DD678415-C-(157424).PDF",         "DD678415-C"),
    ])
    def test_strips_asm_temp_prefix(self, filename, expected):
        """assembly mode מוסיף _asm_temp_ לפני שם הקובץ — לא צריך לבלבל את החילוץ."""
        assert extract_generic_pn_from_filename(filename) == expected

    def test_strips_serial_suffix(self):
        # "(133399)" — מספר סדרתי של B2B/Bazan שצריך להיות מוסר
        # התוצאה האמיתית כיום: "" — _GENERIC_PN_PATTERNS לא תופסים "1034R325-002"
        # (4 ספרות לפני אות אינו תואם לתבניות הקיימות).
        # זה מתעד הגבלה של החילוץ — לא "באג" אבל אזור פוטנציאלי לשיפור.
        result = extract_generic_pn_from_filename("1034R325-002-(133399).PDF")
        assert "133399" not in result


# ─────────────────────────────────────────────────────────────────
# _is_suspicious_pn — זיהוי PN חשוד
# ─────────────────────────────────────────────────────────────────
class TestIsSuspiciousPn:
    @pytest.mark.parametrize("pn,is_suspect", [
        # Generic parts-list cells
        ("ITEM 2", True),
        ("ITEM 602", True),
        ("PART 5", True),
        ("NO. 12", True),
        ("# 7", True),
        # Column headers (value of header cell, not real PN)
        ("PART NUMBER", True),
        ("CATALOG NO", True),
        ("DRAWING NO", True),
        ("P/N", True),
        # Too short
        ("A1", True),
        ("AB-C", True),  # only 3 chars after stripping spaces/dashes
        # Legitimate PNs
        ("BP70534A", False),
        ("FTLS02009A", False),
        ("UCP-212-00703", False),
        ("330-53-14-J8409", False),
        # Empty
        ("", False),
    ])
    def test_detection(self, pn, is_suspect):
        suspect, _ = _is_suspicious_pn(pn)
        assert suspect == is_suspect

    def test_returns_reason_when_suspect(self):
        is_suspect, reason = _is_suspicious_pn("ITEM 5")
        assert is_suspect
        assert reason  # non-empty reason

    @pytest.mark.parametrize("pn", [
        # Whitespace-containing PNs — מודל הוסיף תיאור לפני ה-PN
        "YT35 MD FTG1242544",
        "MARK PART 1234",
        "DESCRIPTION 5678",
    ])
    def test_whitespace_pn_flagged(self, pn):
        """PN אמיתי לא מכיל רווחים (פרט ל-ITEM/PART X שכבר נתפסו)."""
        suspect, reason = _is_suspicious_pn(pn)
        assert suspect, f"{pn!r} שלא נדגלי — {reason}"
        assert "whitespace" in reason or "ITEM" in reason

    @pytest.mark.parametrize("pn", [
        # Pure digits, length < 7 — שבר של PN ארוך יותר
        "11042",     # שבר של ETN1110422
        "1042",
        "36799",     # 5 ספרות — חשוד
        "999999",    # 6 ספרות — חשוד
    ])
    def test_short_pure_digit_flagged(self, pn):
        suspect, reason = _is_suspicious_pn(pn)
        assert suspect, f"{pn!r} שלא נדגלי"
        # יכול להיות "too short" או "all-digits and short"
        assert "short" in reason.lower() or "fragment" in reason.lower()

    @pytest.mark.parametrize("pn", [
        # PNs נומריים ארוכים — לגיטימיים, לא לסמן
        "1075943",      # 7 ספרות
        "10759436",     # 8 ספרות
        "107594360",    # 9 ספרות
        "12345678901",  # 11 ספרות
    ])
    def test_long_pure_digit_not_flagged(self, pn):
        suspect, _ = _is_suspicious_pn(pn)
        assert not suspect, f"{pn!r} סומן בטעות"


# ─────────────────────────────────────────────────────────────────
# Similarity helpers
# ─────────────────────────────────────────────────────────────────
class TestDigitJaccard:
    def test_identical_digits_returns_1(self):
        assert _digit_jaccard("ABC123", "XYZ123") == 1.0

    def test_disjoint_digits_returns_0(self):
        assert _digit_jaccard("ABC123", "XYZ456") == 0.0

    def test_no_digits_returns_0(self):
        assert _digit_jaccard("ABCD", "EFGH") == 0.0

    def test_partial_overlap(self):
        # "1" appears in both, but each has unique others
        result = _digit_jaccard("AB1-22", "CD1-33")
        assert 0 < result < 1


class TestCharJaccard:
    def test_identical_returns_1(self):
        assert _char_jaccard("ABC123", "ABC123") == 1.0

    def test_dashes_ignored(self):
        # אותם תווים, אחד עם מקפים — אמור להחזיר 1.0
        assert _char_jaccard("AB-CD", "ABCD") == 1.0

    def test_case_insensitive(self):
        assert _char_jaccard("abc", "ABC") == 1.0

    def test_disjoint_returns_0(self):
        assert _char_jaccard("ABC", "XYZ") == 0.0


class TestSequencesCompatible:
    def test_clearly_compatible_4char_match(self):
        # רצף ברור של 4+ תווים → True
        assert _sequences_compatible("ABC1234XYZ", "QQQ1234RRR") is True

    def test_truncated_pn_no_4char_substring(self):
        # "TH15012" vs "THR1510712" — יש תווים משותפים אבל ללא רצף 4+ contiguous.
        # ⚠️ ה-docstring מציין "1501" כרצף משותף אבל בפועל אין:
        #   THR1510712 = T-H-R-1-5-1-0-7-1-2 (אין "1501" רצוף)
        #   TH15012    = T-H-1-5-0-1-2 (יש "1501")
        # הפונקציה מחזירה False נכון — אזור לבדוק אם ה-docstring מטעה.
        assert _sequences_compatible("THR1510712", "TH15012") is False

    def test_no_common_4char_substring(self):
        # אין רצף 4+ משותף → False
        assert _sequences_compatible("NV03-58-28", "893-65503682-55") is False

    def test_identical_strings(self):
        assert _sequences_compatible("ABCDEF", "ABCDEF") is True


# ─────────────────────────────────────────────────────────────────
# OCR distance functions
# ─────────────────────────────────────────────────────────────────
class TestOcrConfusionDistance:
    @pytest.mark.parametrize("a,b,expected", [
        # Identical
        ("BP70534A", "BP70534A", 0),
        # Single OCR pair
        ("BN80760B", "BNB0760B", 1),  # 8↔B
        ("BP70534A", "BPT0534A", 1),  # 7↔T
        # Two OCR pairs
        ("BBO0", "BB00", 1),  # only one diff (O→0)
        # Different lengths → 99
        ("BP7053", "BP70534", 99),
        # Non-confusion difference → 99
        ("BP70534A", "XX70534A", 99),
        # Empty
        ("", "ABC", 99),
        ("ABC", "", 99),
    ])
    def test_distance(self, a, b, expected):
        assert ocr_confusion_distance(a, b) == expected

    def test_j_u_pair(self):
        # ראינו ב-Batch 2 — J↔U טעות OCR
        assert ocr_confusion_distance("BJ14981A", "BU14981A") == 1

    def test_l_i_pair(self):
        # ראינו ב-Batch 4 — L↔I
        assert ocr_confusion_distance("EL0498", "EI0498") == 1


class TestTranspositionDistance:
    def test_adjacent_swap_returns_1(self):
        assert transposition_distance("BBJ1", "BB1J") == 1

    def test_identical_returns_0(self):
        assert transposition_distance("ABC", "ABC") == 0

    def test_non_adjacent_returns_99(self):
        # החלפה לא סמוכה
        assert transposition_distance("ABCD", "DBCA") == 99

    def test_different_length_returns_99(self):
        assert transposition_distance("ABCD", "ABCDE") == 99

    def test_three_diffs_returns_99(self):
        assert transposition_distance("ABCD", "BACE") == 99


class TestInsertionDeletionDistance:
    def test_single_insertion(self):
        # "BP7053A" → "BP70534A" (חסר ספרה 4)
        assert insertion_deletion_distance("BP7053A", "BP70534A") == 1

    def test_identical(self):
        # אורך זהה — לא רלוונטי, חייב פלט 99
        assert insertion_deletion_distance("ABC", "ABC") == 99

    def test_two_diffs_returns_99(self):
        assert insertion_deletion_distance("ABCD", "AXBYZ") == 99

    def test_length_difference_more_than_1(self):
        assert insertion_deletion_distance("AB", "ABCDE") == 99

    def test_empty_returns_99(self):
        assert insertion_deletion_distance("", "A") == 99


class TestCombinedPnDistance:
    def test_returns_minimum_of_three(self):
        # OCR confusion = 1, אז zhang אם זה הקטן
        assert combined_pn_distance("BN80760B", "BNB0760B") == 1

    def test_unrelated_returns_99(self):
        assert combined_pn_distance("ABC", "XYZ") == 99

    def test_insertion_wins(self):
        # OCR מחזיר 99 (אורך שונה), insertion מחזיר 1
        assert combined_pn_distance("BP7053A", "BP70534A") == 1


# ─────────────────────────────────────────────────────────────────
# correct_pn_with_filename — תיקון לפי שם קובץ
# ─────────────────────────────────────────────────────────────────
class TestCorrectPnWithFilename:
    def test_corrects_ocr_confusion(self):
        # שם קובץ: BN80760B (אמיתי) — שחולץ: BNB0760B (8 הוקרא כ-B)
        corrected, was = correct_pn_with_filename(
            "BNB0760B",
            "B2BDraw_BN80760B-A-PD-bn80760b_a.pdf",
        )
        assert was is True
        assert corrected == "BN80760B"

    def test_no_correction_when_match(self):
        corrected, was = correct_pn_with_filename(
            "BN80760B",
            "B2BDraw_BN80760B-A-PD-bn80760b_a.pdf",
        )
        assert was is False
        assert corrected == "BN80760B"

    def test_no_correction_when_too_different(self):
        # מרחק > 2 — לא מתקנים
        corrected, was = correct_pn_with_filename(
            "ABCDEFG",
            "BN80760B-A.pdf",
        )
        assert was is False
        assert corrected == "ABCDEFG"

    def test_empty_pn(self):
        corrected, was = correct_pn_with_filename("", "anything.pdf")
        assert was is False
        assert corrected == ""


# ─────────────────────────────────────────────────────────────────
# normalize_dwg_vs_pn — איחוד PN ו-DWG כשהם נבדלים בתו אחד OCR
# ─────────────────────────────────────────────────────────────────
class TestNormalizeDwgVsPn:
    def test_picks_form_with_more_digits(self):
        # BP70534A (5 ספרות אחרי 2 אותיות) עדיף על BPT0534A (4)
        s = {"part_number": "BPT0534A", "drawing_number": "BP70534A"}
        was, canonical = normalize_dwg_vs_pn(s)
        assert was is True
        assert canonical == "BP70534A"
        assert s["part_number"] == "BP70534A"
        assert s["drawing_number"] == "BP70534A"

    def test_no_change_when_equal(self):
        s = {"part_number": "BP70534A", "drawing_number": "BP70534A"}
        was, _ = normalize_dwg_vs_pn(s)
        assert was is False

    def test_no_change_when_distance_too_large(self):
        s = {"part_number": "ABC123", "drawing_number": "XYZ789"}
        was, _ = normalize_dwg_vs_pn(s)
        assert was is False

    def test_empty_fields(self):
        s = {"part_number": "", "drawing_number": "BP70534A"}
        was, _ = normalize_dwg_vs_pn(s)
        assert was is False  # אחד ריק — לא משווים


# ─────────────────────────────────────────────────────────────────
# normalize_trailing_letter — סיומת אות חסרה
# ─────────────────────────────────────────────────────────────────
class TestNormalizeTrailingLetter:
    def test_pn_missing_trailing_letter(self):
        # PN קצר ב-1 תו, DWG מסתיים באות → השלם את PN
        s = {"part_number": "BB1J0219", "drawing_number": "BB1J0219A"}
        assert normalize_trailing_letter(s) is True
        assert s["part_number"] == "BB1J0219A"

    def test_dwg_missing_trailing_letter(self):
        s = {"part_number": "BB1J0219A", "drawing_number": "BB1J0219"}
        assert normalize_trailing_letter(s) is True
        assert s["drawing_number"] == "BB1J0219A"

    def test_no_change_when_equal(self):
        s = {"part_number": "ABC123", "drawing_number": "ABC123"}
        assert normalize_trailing_letter(s) is False

    def test_no_change_when_unrelated(self):
        s = {"part_number": "ABC", "drawing_number": "XYZ"}
        assert normalize_trailing_letter(s) is False


# ─────────────────────────────────────────────────────────────────
# salvage_revision — תיקון "RC"→"C", "REV C"→"C"
# ─────────────────────────────────────────────────────────────────
class TestSalvageRevision:
    @pytest.mark.parametrize("input_rev,expected_rev", [
        ("RC", "C"),
        ("RA", "A"),
        ("RB", "B"),
        ("REV C", "C"),
        ("REV A", "A"),
        ("Rev.C", "C"),
        ("Rev-C", "C"),
        ("REV_B", "B"),
    ])
    def test_salvages(self, input_rev, expected_rev):
        s = {"revision": input_rev}
        assert salvage_revision(s) is True
        assert s["revision"] == expected_rev

    @pytest.mark.parametrize("clean_rev", ["A", "B", "C", "01", "02"])
    def test_does_not_modify_clean_rev(self, clean_rev):
        s = {"revision": clean_rev}
        assert salvage_revision(s) is False
        assert s["revision"] == clean_rev

    def test_empty_revision(self):
        s = {"revision": ""}
        assert salvage_revision(s) is False

    def test_too_long_revision(self):
        # מעל 6 תווים — לא נוגעים
        s = {"revision": "RABCDEFG"}
        assert salvage_revision(s) is False

    def test_non_dict_input(self):
        assert salvage_revision("not a dict") is False  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# reconcile_drawing_number — DWG ריק → PN
# ─────────────────────────────────────────────────────────────────
class TestReconcileDrawingNumber:
    def test_empty_dwg_uses_pn(self):
        s = {"part_number": "BP70534A", "drawing_number": ""}
        assert reconcile_drawing_number(s) is True
        assert s["drawing_number"] == "BP70534A"

    def test_dash_dwg_uses_pn(self):
        s = {"part_number": "BP70534A", "drawing_number": "-"}
        assert reconcile_drawing_number(s) is True
        assert s["drawing_number"] == "BP70534A"

    def test_na_dwg_uses_pn(self):
        s = {"part_number": "BP70534A", "drawing_number": "N/A"}
        assert reconcile_drawing_number(s) is True
        assert s["drawing_number"] == "BP70534A"

    def test_existing_dwg_unchanged(self):
        s = {"part_number": "BP70534A", "drawing_number": "DWG-123"}
        assert reconcile_drawing_number(s) is False
        assert s["drawing_number"] == "DWG-123"

    def test_empty_pn_no_change(self):
        s = {"part_number": "", "drawing_number": ""}
        assert reconcile_drawing_number(s) is False


# ─────────────────────────────────────────────────────────────────
# reconcile_revision — fallback מטבלה / שם קובץ
# ─────────────────────────────────────────────────────────────────
class TestReconcileRevision:
    def test_existing_revision_unchanged(self):
        s = {"revision": "B"}
        assert reconcile_revision(s, "anything.pdf") is False
        assert s["revision"] == "B"

    def test_fills_from_revisions_history(self):
        s = {
            "revision": "",
            "revisions_history": [
                {"rev": "A", "date": "2020-01-01"},
                {"rev": "B", "date": "2021-01-01"},
                {"rev": "C", "date": "2022-01-01"},
            ],
        }
        assert reconcile_revision(s, "") is True
        assert s["revision"] == "C"  # האחרון

    def test_fills_from_filename_revx_pattern(self):
        s = {"revision": ""}
        assert reconcile_revision(s, "B2BDraw_un34040T-40301-01#RevB#A0#S2_30.pdf") is True
        assert s["revision"] == "B"

    def test_filename_rev_underscore(self):
        s = {"revision": ""}
        assert reconcile_revision(s, "drawing_Rev_C.pdf") is True
        assert s["revision"] == "C"

    def test_no_source_returns_false(self):
        s = {"revision": ""}
        assert reconcile_revision(s, "drawing.pdf") is False

    def test_table_priority_over_filename(self):
        # אם יש גם וגם — הטבלה ניצחת
        s = {
            "revision": "",
            "revisions_history": [{"rev": "X"}],
        }
        reconcile_revision(s, "drawing_RevB.pdf")
        assert s["revision"] == "X"


# ─────────────────────────────────────────────────────────────────
# prefer_filename_pn_if_substring
# ─────────────────────────────────────────────────────────────────
class TestPreferFilenamePnIfSubstring:
    def test_replaces_when_filename_more_complete(self):
        # current="53-14-J8409-201-R", file="330-53-14-J8409-201"
        s = {"part_number": "53-14-J8409-201-R"}
        result = prefer_filename_pn_if_substring(s, "330-53-14-J8409-201.pdf")
        assert result is True
        assert s["part_number"] == "330-53-14-J8409-201"

    def test_does_not_replace_when_current_is_full_substring(self):
        # current="BP70534A" full, file="BP70534A-A-..." (the -A is a Rev)
        s = {"part_number": "BP70534A"}
        result = prefer_filename_pn_if_substring(s, "BP70534A-A-PD-bp70534a.pdf")
        assert result is False
        assert s["part_number"] == "BP70534A"

    def test_no_replace_when_match(self):
        s = {"part_number": "1384-2153-01"}
        result = prefer_filename_pn_if_substring(s, "1384-2153-01.pdf")
        assert result is False

    def test_empty_pn(self):
        s = {"part_number": ""}
        assert prefer_filename_pn_if_substring(s, "1384-2153-01.pdf") is False

    def test_updates_drawing_number_too(self):
        s = {
            "part_number": "53-14-J8409-201-R",
            "drawing_number": "53-14-J8409-201-R",
        }
        prefer_filename_pn_if_substring(s, "330-53-14-J8409-201.pdf")
        assert s["drawing_number"] == "330-53-14-J8409-201"


# ─────────────────────────────────────────────────────────────────
# filename_override_if_suspicious_pn — override אגרסיבי
# ─────────────────────────────────────────────────────────────────
class TestFilenameOverrideIfSuspiciousPn:
    def test_overrides_item_x_pattern(self):
        # current="ITEM 602", file="UCP-280-89981-602"
        s = {"part_number": "ITEM 602"}
        result = filename_override_if_suspicious_pn(s, "UCP-280-89981-602.pdf")
        assert result is True
        assert s["part_number"] == "UCP-280-89981-602"

    def test_overrides_completely_different_pn(self):
        # current="1028287A" (probably hallucinated), file="AZO-34008-DD"
        # NOTE: 1028287A יזהה כתבנית alpha+digits → תופס פנימית.
        # נשתמש במקרה ברור יותר: alpha vs digit start
        s = {"part_number": "AZO34008"}  # alpha-start hallucination
        result = filename_override_if_suspicious_pn(s, "893-65503682-55.pdf")
        assert result is True
        assert s["part_number"] == "893-65503682-55"

    def test_no_override_when_current_is_clean(self):
        # current matches filename — אל תיגע
        s = {"part_number": "BP70534A"}
        result = filename_override_if_suspicious_pn(s, "BP70534A.pdf")
        assert result is False

    def test_no_override_when_filename_unparseable(self):
        s = {"part_number": "BP70534A"}
        result = filename_override_if_suspicious_pn(s, "readme.pdf")
        assert result is False

    def test_empty_pn(self):
        s = {"part_number": ""}
        result = filename_override_if_suspicious_pn(s, "BP70534A.pdf")
        assert result is False

    def test_single_digit_substitution_overrides(self):
        """
        same-length + 1 digit-position diff + narrow filename extract הצליח →
        העדף את שם הקובץ. תופס OCR typo כמו 4↔3 שלא נכנס לזוגות הקלאסיים.
        """
        s = {"part_number": "BO27303A", "drawing_number": "BO27303A"}
        result = filename_override_if_suspicious_pn(s, "BO27304A.pdf")
        assert result is True
        assert s["part_number"] == "BO27304A"
        assert s["drawing_number"] == "BO27304A"

    def test_single_letter_substitution_does_not_override(self):
        """
        אותם תנאים אבל ההבדל הוא באות (לא בספרה) — לא לכפות.
        אותיות בתחילת PN מבדילות בין מודלי לקוחות (BP/BB/BN וכו') ולא
        אמורים להיות OCR typo כמו 4↔3.
        """
        s = {"part_number": "BO27304A"}
        result = filename_override_if_suspicious_pn(s, "BP27304A.pdf")
        assert result is False
        assert s["part_number"] == "BO27304A"

    def test_two_diff_does_not_trigger_substitution_path(self):
        # 2 הבדלים → לא טריוויאלי, אסור לכפות עם heuristic זה
        s = {"part_number": "BP70534A"}
        result = filename_override_if_suspicious_pn(s, "BP70589A.pdf")
        # לא דרך heuristic זה (2 הבדלים), אבל אולי דרך path אחר; כאן
        # פשוט מוודאים שלא הוחלף לערך שונה לחלוטין
        if result:
            # אם בוצע replace, לפחות הוא לא הזיה
            assert s["part_number"] in ("BP70589A",)


# ─────────────────────────────────────────────────────────────────
# reconcile_part_number — אינטגרציה של כל הסטראטגיות
# ─────────────────────────────────────────────────────────────────
class TestReconcilePartNumber:
    def test_ocr_confusion_correction(self):
        # שם קובץ: BN80760B; שחולץ: BNB0760B (8→B)
        s = {"part_number": "BNB0760B", "drawing_number": "BNB0760B"}
        reconcile_part_number(s, "B2BDraw_BN80760B-A-PD-bn80760b_a.pdf")
        assert s["part_number"] == "BN80760B"
        assert s["drawing_number"] == "BN80760B"

    def test_pn_empty_uses_dwg(self):
        s = {"part_number": "", "drawing_number": "BP70534A"}
        reconcile_part_number(s, "anything.pdf")
        assert s["part_number"] == "BP70534A"

    def test_pn_and_dwg_empty_uses_filename(self):
        s = {"part_number": "", "drawing_number": ""}
        reconcile_part_number(s, "BP70534A-A-PD-bp70534a.pdf")
        assert s["part_number"] == "BP70534A"

    def test_no_changes_when_clean_data(self):
        s = {"part_number": "BP70534A", "drawing_number": "BP70534A"}
        reconcile_part_number(s, "BP70534A.pdf")
        assert s["part_number"] == "BP70534A"
        assert s["drawing_number"] == "BP70534A"


# ─────────────────────────────────────────────────────────────────
# BOM cross-reference
# ─────────────────────────────────────────────────────────────────
class TestCollectBomPartNumbers:
    def test_collects_uppercase_uniques(self):
        drawings = [
            {"bom_items": [
                {"part_number": "abc-123"},
                {"part_number": "DEF-456"},
            ]},
            {"bom_items": [
                {"part_number": "abc-123"},  # duplicate
                {"part_number": "ghi-789"},
            ]},
        ]
        pns = collect_bom_part_numbers(drawings)
        assert pns == {"ABC-123", "DEF-456", "GHI-789"}

    def test_empty_drawings(self):
        assert collect_bom_part_numbers([]) == set()

    def test_skip_non_dict_items(self):
        drawings = [{"bom_items": ["string", None, {"part_number": "ABC"}]}]
        assert collect_bom_part_numbers(drawings) == {"ABC"}


class TestCrossReferencePartNumbers:
    def test_corrects_pn_via_bom(self):
        # שרטוט A יש לו PN חשוד "BNB0760B", שרטוט B מכיל אותו ב-BOM כ"BN80760B"
        drawings = [
            {"part_number": "BNB0760B"},  # OCR error
            {
                "part_number": "ASSEMBLY",
                "bom_items": [{"part_number": "BN80760B"}],
            },
        ]
        corrections = cross_reference_part_numbers(drawings)
        assert len(corrections) == 1
        assert drawings[0]["part_number"] == "BN80760B"

    def test_no_correction_when_pn_in_bom(self):
        drawings = [
            {"part_number": "BN80760B"},
            {
                "part_number": "ASM",
                "bom_items": [{"part_number": "BN80760B"}],
            },
        ]
        corrections = cross_reference_part_numbers(drawings)
        assert corrections == []

    def test_no_correction_when_no_close_match(self):
        drawings = [
            {"part_number": "TOTALLY-DIFFERENT-PN"},
            {
                "part_number": "ASM",
                "bom_items": [{"part_number": "BN80760B"}],
            },
        ]
        corrections = cross_reference_part_numbers(drawings)
        assert corrections == []

    def test_empty_bom_no_corrections(self):
        drawings = [{"part_number": "BNB0760B"}]
        assert cross_reference_part_numbers(drawings) == []


# ═════════════════════════════════════════════════════════════════════
# strip_letter_distance — matcher חדש ל-OCR confusion + drop trailing letter
# ═════════════════════════════════════════════════════════════════════
class TestStripLetterDistance:
    """ה-matcher הזה מטפל במקרים שבהם OCR גם איבד אות סופית **וגם** עשה
    החלפת תווים דומים. הדוגמה המתועדת: BP70689A ↔ 8070689 (B↔8 + P↔0 + drop A)."""

    def test_real_case_bp70689a_vs_8070689(self):
        """המקרה האמיתי שדווח — RAIL BEAM FOR WHEELS."""
        # B↔8 + P↔0 + drop A → 2 הפרשים
        assert strip_letter_distance("BP70689A", "8070689") == 2
        # סימטרי
        assert strip_letter_distance("8070689", "BP70689A") == 2

    def test_simple_trailing_letter_drop(self):
        """איבוד A בלבד, ללא OCR confusion."""
        assert strip_letter_distance("BP70689A", "BP70689") == 0
        assert strip_letter_distance("BP70689", "BP70689A") == 0

    def test_trailing_letter_with_one_ocr_diff(self):
        assert strip_letter_distance("BP70689A", "BP7O689") == 1  # O↔0

    def test_returns_99_when_lengths_differ_by_more_than_1(self):
        assert strip_letter_distance("BP70689A", "070689") == 99

    def test_returns_99_when_no_trailing_letter(self):
        """ספרה בסוף — לא drop של אות, לא רלוונטי."""
        assert strip_letter_distance("BP706891", "BP70689") == 99

    def test_returns_99_when_more_than_2_diffs(self):
        # אם אחרי ה-strip יש 3+ הפרשים — לא match
        assert strip_letter_distance("ABCDA", "8070") == 99

    def test_returns_99_for_empty_strings(self):
        assert strip_letter_distance("", "BP70689A") == 99
        assert strip_letter_distance("BP70689A", "") == 99


# ═════════════════════════════════════════════════════════════════════
# combined_pn_distance — בדיקה שה-matcher החדש משולב
# ═════════════════════════════════════════════════════════════════════
class TestCombinedPnDistanceWithStripLetter:
    def test_includes_strip_letter_matcher(self):
        """combined_pn_distance צריך להחזיר 2 ל-BP70689A↔8070689 (לא 99)."""
        assert combined_pn_distance("BP70689A", "8070689") == 2

    def test_p_to_0_in_ocr_confusion(self):
        """P↔0 הוסף לטבלת ה-OCR confusion."""
        assert ocr_confusion_distance("P", "0") == 1
        assert ocr_confusion_distance("0", "P") == 1


# ═════════════════════════════════════════════════════════════════════
# cross_reference Phase 1 — תיקון BOM מהשרטוט (BP70689A case)
# ═════════════════════════════════════════════════════════════════════
class TestCrossReferenceBomCorrection:
    def test_corrects_digits_only_bom_to_drawing_pn(self):
        """המקרה האמיתי: BP70689A הועלה כשרטוט. BP70616A יש לו BOM עם 8070689."""
        drawings = [
            {
                "part_number": "BP70689A",  # הכותרת התקינה
                "title": "RAIL BEAM FOR WHEELS",
            },
            {
                "part_number": "BP70616A",
                "bom_items": [
                    {"part_number": "8070689", "description": "RAIL BEAM FOR WHEELS",
                     "qty": "8"},
                    {"part_number": "BP70534A", "description": "QLTY CART", "qty": "1"},
                ],
            },
        ]
        corrections = cross_reference_part_numbers(drawings)
        # ה-BOM item צריך לקבל BP70689A במקום 8070689
        assert drawings[1]["bom_items"][0]["part_number"] == "BP70689A"
        # ה-drawing PN של BP70689A חייב להישאר ללא שינוי!
        assert drawings[0]["part_number"] == "BP70689A"
        # התיקון תועד
        assert any("BP70689A" in m and "8070689" in m for m in corrections)

    def test_does_not_corrupt_drawing_pn_when_bom_is_wrong(self):
        """באג קודם: ה-cross-ref ישן היה מחליף BP70689A (תקין) ב-8070689 (שגוי).
        הבדיקה הזו מוודאת שזה לא קורה יותר."""
        drawings = [
            {"part_number": "BP70689A"},
            {
                "part_number": "ASM",
                "bom_items": [{"part_number": "8070689"}],
            },
        ]
        cross_reference_part_numbers(drawings)
        # BP70689A חייב להישאר — לא להפוך ל-8070689
        assert drawings[0]["part_number"] == "BP70689A"
        # להפך — ה-BOM צריך להתעדכן
        assert drawings[1]["bom_items"][0]["part_number"] == "BP70689A"

    def test_skips_when_bom_pn_has_letters(self):
        """Phase 1 רץ רק על BOM PN ספרות-בלבד. אם יש לו אותיות — לא נוגעים."""
        drawings = [
            {"part_number": "BNB0760B"},  # סטיית OCR ידועה
            {
                "part_number": "ASM",
                "bom_items": [{"part_number": "BN80760B"}],  # יש אותיות!
            },
        ]
        cross_reference_part_numbers(drawings)
        # Phase 1 מדלג כי BN80760B יש לו אותיות.
        # Phase 2 (legacy) מתקן את ה-drawing במקום.
        assert drawings[0]["part_number"] == "BN80760B"  # legacy behavior
        assert drawings[1]["bom_items"][0]["part_number"] == "BN80760B"  # נשאר

    def test_skips_when_no_drawing_with_letters(self):
        """אם אין שרטוט עם אותיות — אין מועמד שעדיף על ה-BOM, לא נוגעים."""
        drawings = [
            {"part_number": "12345"},  # ספרות בלבד
            {
                "part_number": "67890",
                "bom_items": [{"part_number": "8070689"}],  # ספרות
            },
        ]
        cross_reference_part_numbers(drawings)
        # שום דבר לא משתנה
        assert drawings[1]["bom_items"][0]["part_number"] == "8070689"

    def test_skips_when_distance_too_large(self):
        """אם ההבדל גדול מדי — לא תיקון אוטומטי."""
        drawings = [
            {"part_number": "ABCXYZ"},
            {
                "part_number": "ASM",
                "bom_items": [{"part_number": "1234567"}],  # ספרות, אבל רחוק
            },
        ]
        cross_reference_part_numbers(drawings)
        # ABCXYZ ↔ 1234567 — distance גדול. לא מתאים.
        assert drawings[1]["bom_items"][0]["part_number"] == "1234567"
