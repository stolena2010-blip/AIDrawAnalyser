"""
Unit tests ל-master_matcher.

הרצה:
    pytest tests/ -v
"""
import pandas as pd

from core.master_matcher import (
    _detect_color,
    _detect_phosphorus_level,
    _detect_type,
    _extract_std_codes,
    _extract_thickness_range,
    _extract_type_class,
    _ranges_overlap,
    _score_master,
)


# ─────────────────────────────────────────────
# _detect_type
# ─────────────────────────────────────────────
class TestDetectType:
    def test_zinc_english(self):
        assert _detect_type("ZINC PLATING") == "zinc"

    def test_zinc_hebrew(self):
        assert _detect_type("ציפוי אבץ") == "zinc"

    def test_electroless_nickel_priority(self):
        # electroless_nickel חייב להיתפס לפני nickel הרגיל
        assert _detect_type("ELECTROLESS NICKEL") == "electroless_nickel"

    def test_hard_anodize_priority(self):
        assert _detect_type("HARD ANODIZE TYPE III") == "hard_anodize"

    def test_conversion_aliases(self):
        assert _detect_type("ALODINE") == "conversion"
        assert _detect_type("CHEM FILM") == "conversion"
        assert _detect_type("IRIDITE") == "conversion"

    def test_no_match(self):
        assert _detect_type("RANDOM TEXT") is None


# ─────────────────────────────────────────────
# _detect_color
# ─────────────────────────────────────────────
class TestDetectColor:
    def test_blue_white_equivalents(self):
        assert _detect_color("NATURAL CHROMATE") == "blue_white"
        assert _detect_color("CLEAR ZINC") == "blue_white"
        assert _detect_color("BLUE/WHITE") == "blue_white"

    def test_yellow(self):
        assert _detect_color("YELLOW CHROMATE") == "yellow"

    def test_hebrew_yellow(self):
        assert _detect_color("צהוב") == "yellow"


# ─────────────────────────────────────────────
# _detect_phosphorus_level
# ─────────────────────────────────────────────
class TestPhosphorusLevel:
    def test_high_phosphor(self):
        assert _detect_phosphorus_level("HIGH PHOSPHOR") == "high"

    def test_low_phosphor(self):
        assert _detect_phosphorus_level("LOW PHOSPHOR") == "low"

    def test_requires_phosphor_keyword(self):
        # "HIGH" לבד לא מספיק
        assert _detect_phosphorus_level("HIGH QUALITY") is None

    def test_medium_variants(self):
        assert _detect_phosphorus_level("MEDIUM PHOSPHOR") == "medium"
        assert _detect_phosphorus_level("MED PHOSPHOR") == "medium"


# ─────────────────────────────────────────────
# _extract_std_codes
# ─────────────────────────────────────────────
class TestStdCodes:
    def test_mil_codes(self):
        codes = _extract_std_codes("MIL-A-8625 Type II Class 1")
        assert "MILA8625" in codes

    def test_astm_codes(self):
        codes = _extract_std_codes("ASTM B633 Class 1A")
        assert "ASTMB633" in codes

    def test_version_letter_stripped(self):
        # AMS-C-26074D → AMSC26074 (ללא אות גרסה)
        codes = _extract_std_codes("AMS-C-26074D")
        assert "AMSC26074" in codes


# ─────────────────────────────────────────────
# _extract_type_class
# ─────────────────────────────────────────────
class TestTypeClass:
    def test_extract_type(self):
        tc = _extract_type_class("Type II Class 1A")
        assert "TYPEII" in tc
        assert "CLASS1A" in tc

    def test_grade(self):
        tc = _extract_type_class("Grade B")
        assert "GRADEB" in tc


# ─────────────────────────────────────────────
# _extract_thickness_range
# ─────────────────────────────────────────────
class TestThicknessRange:
    def test_range_microns(self):
        r = _extract_thickness_range("5-10 mic")
        assert r == (5.0, 10.0)

    def test_single_value_with_tolerance(self):
        # 15µm ± 15% = (12.75, 17.25)
        r = _extract_thickness_range("15 microns")
        assert r is not None
        assert 12 < r[0] < 14
        assert 16 < r[1] < 18

    def test_no_match(self):
        assert _extract_thickness_range("no numbers") is None


# ─────────────────────────────────────────────
# _ranges_overlap
# ─────────────────────────────────────────────
class TestRangesOverlap:
    def test_full_overlap(self):
        assert _ranges_overlap((5, 10), (5, 10)) == 1.0

    def test_no_overlap(self):
        assert _ranges_overlap((5, 10), (20, 30)) == 0.0

    def test_partial_overlap(self):
        # חפיפה > 0
        result = _ranges_overlap((5, 10), (8, 13))
        assert result > 0.0
        assert result < 1.0


# ─────────────────────────────────────────────
# _score_master — בדיקות אינטגרציה
# ─────────────────────────────────────────────
class TestScoreMaster:
    def test_exact_match_high_score(self):
        coating = {
            "type": "Zinc",
            "name": "Zinc plating blue/white",
            "standard": "ASTM B633 Type II Class 1",
            "thickness": "5-10 microns",
            "rohs": True,
        }
        master = pd.Series({
            "desc": "BLUE/WHITE ZINC-RoHS",
            "standard": "ASTM B633 Type II Class 1",
            "thickness": "5-10 mic",
        })
        score, _ = _score_master(coating, master)
        # התאמה מלאה צריכה לתת ציון גבוה
        assert score > 80

    def test_different_type_penalty(self):
        coating = {
            "type": "Zinc",
            "name": "Zinc plating",
            "standard": "ASTM B633",
        }
        master = pd.Series({
            "desc": "NICKEL PLATING",
            "standard": "QQ-N-290",
            "thickness": "",
        })
        score, _ = _score_master(coating, master)
        # סוגים שונים → ציון נמוך / שלילי
        assert score < 20
