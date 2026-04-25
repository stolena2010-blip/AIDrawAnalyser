"""
Unit tests ל-core.two_pass — השוואת שתי הרצות + סימון [VERIFY] לאי-עקביות.

הרצה:
    pytest tests/test_two_pass.py -v
"""

from core.two_pass import (
    _mark_verify,
    compare_and_merge,
    should_run_two_pass,
)


# ─────────────────────────────────────────────────────────────────
# _mark_verify — תחליף ערכים ב-[VERIFY: ...]
# ─────────────────────────────────────────────────────────────────
class TestMarkVerify:
    def test_replaces_single_pattern(self):
        result = _mark_verify("RAL 9005 paint", ["RAL 9005"])
        assert result == "[VERIFY: RAL 9005] paint"

    def test_replaces_multiple_patterns(self):
        result = _mark_verify("a RAL 1001 b RAL 2002 c", ["RAL 1001", "RAL 2002"])
        assert "[VERIFY: RAL 1001]" in result
        assert "[VERIFY: RAL 2002]" in result

    def test_no_match_returns_unchanged(self):
        text = "no ral codes here"
        assert _mark_verify(text, ["RAL 9999"]) == text

    def test_empty_patterns(self):
        text = "RAL 9005 paint"
        assert _mark_verify(text, []) == text


# ─────────────────────────────────────────────────────────────────
# should_run_two_pass — מתי להפעיל אימות
# ─────────────────────────────────────────────────────────────────
class TestShouldRunTwoPass:
    def test_no_painting_returns_false(self):
        stage2 = {"painting_processes": []}
        assert should_run_two_pass(stage2) is False

    def test_painting_without_ral_or_brand_returns_false(self):
        stage2 = {
            "painting_processes": [{"step_no": "10", "name": "GENERIC PAINT"}],
        }
        assert should_run_two_pass(stage2) is False

    def test_painting_with_ral_returns_true(self):
        stage2 = {
            "painting_processes": [
                {"step_no": "10", "name": "PAINT RAL 9005"}
            ],
        }
        assert should_run_two_pass(stage2) is True

    def test_painting_with_brand_returns_true(self):
        stage2 = {
            "painting_processes": [
                {"step_no": "10", "name": "EPOXY BY TAMBOUR"}
            ],
        }
        assert should_run_two_pass(stage2) is True

    def test_no_painting_with_ral_in_other_field_returns_false(self):
        # יש RAL בשדה אחר (standards) אבל אין painting_processes — לא מריצים
        stage2 = {"painting_processes": [], "standards": ["RAL 9005"]}
        assert should_run_two_pass(stage2) is False


# ─────────────────────────────────────────────────────────────────
# compare_and_merge — השוואת שני results
# ─────────────────────────────────────────────────────────────────
class TestCompareAndMerge:
    def test_identical_results_no_warnings(self):
        r1 = {"painting_processes": [{"name": "PAINT RAL 9005"}]}
        r2 = {"painting_processes": [{"name": "PAINT RAL 9005"}]}
        merged, warnings = compare_and_merge(r1, r2)
        assert warnings == []
        assert merged["painting_processes"][0]["name"] == "PAINT RAL 9005"

    def test_ral_mismatch_creates_critical_warning(self):
        r1 = {"painting_processes": [{"name": "PAINT RAL 9005"}]}
        r2 = {"painting_processes": [{"name": "PAINT RAL 1023"}]}
        _, warnings = compare_and_merge(r1, r2)
        assert len(warnings) >= 1
        ral_warnings = [w for w in warnings if w["type"] == "RAL_MISMATCH"]
        assert len(ral_warnings) == 1
        assert ral_warnings[0]["severity"] == "CRITICAL"

    def test_ral_mismatch_marks_verify_in_merged(self):
        r1 = {"painting_processes": [{"name": "PAINT RAL 9005"}]}
        r2 = {"painting_processes": [{"name": "PAINT RAL 1023"}]}
        merged, _ = compare_and_merge(r1, r2)
        # ה-merged צריך לכלול סימון VERIFY (לפחות עבור הערך מ-r1)
        merged_str = str(merged)
        assert "VERIFY" in merged_str

    def test_brand_mismatch_creates_high_warning(self):
        r1 = {"painting_processes": [{"name": "EPOXY BY TAMBOUR"}]}
        r2 = {"painting_processes": [{"name": "EPOXY BY HEMPEL"}]}
        _, warnings = compare_and_merge(r1, r2)
        brand_warnings = [w for w in warnings if w["type"] == "BRAND_MISMATCH"]
        assert len(brand_warnings) == 1
        assert brand_warnings[0]["severity"] == "HIGH"

    def test_no_painting_no_warnings(self):
        r1 = {"machining_processes": [{"name": "DRILL"}]}
        r2 = {"machining_processes": [{"name": "DRILL"}]}
        _, warnings = compare_and_merge(r1, r2)
        assert warnings == []

    def test_returns_merged_based_on_first_result(self):
        # ה-merged בנוי מהרצה 1 עם סימונים — כל השדות מ-r1
        r1 = {"part_number": "BP70534A", "extra": "from_r1"}
        r2 = {"part_number": "BP70534A", "different": "from_r2"}
        merged, _ = compare_and_merge(r1, r2)
        assert merged.get("extra") == "from_r1"
        # שדה ייחודי ל-r2 לא יופיע ב-merged (זה הרצה 1 בסיסית)
        assert "different" not in merged

    def test_both_ral_present_in_one_only_flagged(self):
        # r1 עם 2 RAL, r2 עם 1 RAL
        r1 = {"painting_processes": [{"name": "PRIMER RAL 7035"}, {"name": "TOPCOAT RAL 9005"}]}
        r2 = {"painting_processes": [{"name": "PRIMER RAL 7035"}]}
        _, warnings = compare_and_merge(r1, r2)
        ral_warnings = [w for w in warnings if w["type"] == "RAL_MISMATCH"]
        assert len(ral_warnings) == 1

    def test_empty_results(self):
        r1, r2 = {}, {}
        merged, warnings = compare_and_merge(r1, r2)
        assert warnings == []
        assert merged == {}
