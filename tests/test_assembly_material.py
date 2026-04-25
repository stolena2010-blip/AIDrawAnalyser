"""
Unit tests ל-core.assembly.material — חילוץ חומר מ-OCR + מסנני noise.

הרצה:
    pytest tests/test_assembly_material.py -v
"""
import pytest

from core.assembly.material import (
    _extract_material_direct,
    _extract_material_from_text,
    _looks_like_material,
    is_material_instruction_only,
)


# ─────────────────────────────────────────────────────────────────
# is_material_instruction_only — מסנן הוראות שאינן חומר
# ─────────────────────────────────────────────────────────────────
class TestIsMaterialInstructionOnly:
    @pytest.mark.parametrize("text", [
        "USE EXTRUSION MCM-MC-08028-01.",   # תופסים ב-new7
        "PER MIL-DTL-5541",
        "SEE NOTE 5",
        "REFER TO PS-111",
        "REFERENCE DRAWING 1234",
        "AS PER NOTE 7",
        "AS REQUIRED",
        "ACC TO STD-123",
        "ACC. TO MIL-STD-130",
        "ACCORDING TO BLUEPRINT",
    ])
    def test_instruction_only_flagged(self, text):
        assert is_material_instruction_only(text) is True

    @pytest.mark.parametrize("text", [
        # הוראות שכוללות חומר אמיתי — לגיטימיות
        "USE STAINLESS STEEL 304",
        "USE AL 6061-T6",
        "PER ASTM A123 STEEL 4140",
        "AS PER SAE-AMS-4016 ALUMINUM 5052",
    ])
    def test_instruction_with_material_not_flagged(self, text):
        assert is_material_instruction_only(text) is False

    @pytest.mark.parametrize("text", [
        # חומרים אמיתיים בלי קידומת הוראה
        "AL 6061-T6",
        "STAINLESS STEEL 303",
        "TITANIUM Ti-6AL-4V",
        "DELRIN ROD",
        "BRASS C36000",
    ])
    def test_pure_material_not_flagged(self, text):
        assert is_material_instruction_only(text) is False

    def test_empty(self):
        assert is_material_instruction_only("") is False

    def test_whitespace_only(self):
        assert is_material_instruction_only("   ") is False


# ─────────────────────────────────────────────────────────────────
# _looks_like_material
# ─────────────────────────────────────────────────────────────────
class TestLooksLikeMaterial:
    @pytest.mark.parametrize("text", [
        "AL 6061-T6", "STAINLESS STEEL 303", "TITANIUM ALLOY",
        "DELRIN", "PEEK", "BRASS C36000", "INCONEL 718",
        "ALUMINUM 7075", "PLATE 5052",
    ])
    def test_real_materials(self, text):
        assert _looks_like_material(text) is True

    @pytest.mark.parametrize("text", [
        "USE EXTRUSION", "PER NOTE 5", "SEE DRAWING",
        "MARK PART NUMBER", "QTY 2", "",
    ])
    def test_non_materials(self, text):
        assert _looks_like_material(text) is False


# ─────────────────────────────────────────────────────────────────
# _extract_material_from_text — חיפוש שדה MATERIAL מסומן
# ─────────────────────────────────────────────────────────────────
class TestExtractMaterialFromText:
    def test_label_on_separate_line(self):
        ocr = "TITLE\nMATERIAL\nAL 6061-T6\nQTY"
        result = _extract_material_from_text(ocr)
        assert "AL 6061-T6" in result

    def test_inline_label_with_colon(self):
        ocr = "MATERIAL: STAINLESS STEEL 304\nNEXT LINE"
        result = _extract_material_from_text(ocr)
        assert "STAINLESS STEEL 304" in result

    def test_matl_abbreviation(self):
        ocr = "MATL: AL 7075-T6"
        result = _extract_material_from_text(ocr)
        assert "AL 7075-T6" in result

    def test_skips_noise_phrases(self):
        # "OTHER SIZE" / "SIMILAR MATERIAL" — disclaimer ignored
        ocr = "MATERIAL\nOTHER SIZE\nAL 6061-T6"
        result = _extract_material_from_text(ocr)
        # שורת disclaimer דולגת, לוקח את הבאה אם שייך לחומר
        assert "6061" in result

    def test_no_label_returns_empty(self):
        ocr = "JUST SOME RANDOM TEXT"
        assert _extract_material_from_text(ocr) == ""

    def test_empty_text(self):
        assert _extract_material_from_text("") == ""


# ─────────────────────────────────────────────────────────────────
# _extract_material_direct — regex direct search (fallback אחרון)
# ─────────────────────────────────────────────────────────────────
class TestExtractMaterialDirect:
    @pytest.mark.parametrize("text,expected_substr", [
        ("ALUMINUM ALLOY 6061-T651 PER MIL-A-8625", "6061-T651"),
        ("AL 7075-T6", "7075"),
        ("STAINLESS STEEL 303", "303"),
        ("LOW CARBON STEEL SAE 1020", "1020"),
        ("STAINLESS STEEL 15-5PH", "15-5PH"),
        ("TITANIUM Ti-6AL-4V", "Ti-6"),
        ("DELRIN ROD", "DELRIN"),
        ("PEEK SHEET", "PEEK"),
    ])
    def test_extracts_material(self, text, expected_substr):
        result = _extract_material_direct(text)
        assert expected_substr in result, f"{result!r} missing {expected_substr!r}"

    def test_no_material_in_text_returns_empty(self):
        assert _extract_material_direct("RANDOM NOISE NO MATERIAL HERE") == ""

    def test_empty_text(self):
        assert _extract_material_direct("") == ""

    def test_finds_material_in_long_text(self):
        # חומר באמצע טקסט ארוך
        text = (
            "Some preamble. " * 20
            + "MATERIAL: STAINLESS STEEL 304 PER ASTM A276 "
            + "More stuff. " * 20
        )
        result = _extract_material_direct(text)
        assert "304" in result

    def test_truncates_at_200(self):
        text = "STAINLESS STEEL 304 " + "x" * 500
        result = _extract_material_direct(text)
        assert len(result) <= 200
