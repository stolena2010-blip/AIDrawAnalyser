"""
Smoke tests ל-HTML report generation (storage/pdf_report.py).

הדוחות עכשיו HTML טהור — אין יותר תלות ב-PyMuPDF (AGPL).
הבדיקות מוודאות שה-HTML שמיוצר:
  • הוא קובץ HTML תקני
  • מכיל RTL + meta charset utf-8
  • מכיל את התוכן הצפוי (שם פריט, חומר, תקנים)
  • כולל את ה-print CSS לשמירה כ-PDF דרך הדפדפן
  • Excel exports ממשיכים לעבוד

הרצה:
    pytest tests/test_pdf_report_optional.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from storage import pdf_report


@pytest.fixture
def sample_drawing():
    return {
        "source_filename": "test.pdf",
        "part_number": "TEST-001",
        "drawing_number": "TEST-001",
        "revision": "A",
        "customer": "ACME Inc.",
        "material": "ALUMINUM 6061-T6",
        "assembly_role": "PART",
        "quantity": "1",
        "title": "Sample test bracket",
        "standards": ["MIL-DTL-5541F"],
        "notes": "Sample test notes — Hebrew: שלום עולם",
    }


# ─────────────────────────────────────────────────────────────────
# 1. build_assembly_html — single mode + assembly mode
# ─────────────────────────────────────────────────────────────────
class TestAssemblyHTML:
    def test_single_mode_produces_valid_html(self, tmp_path, sample_drawing):
        out = pdf_report.build_assembly_html(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "test.html",
            single_mode=True,
        )
        assert Path(out).exists()
        assert Path(out).stat().st_size > 1000
        content = Path(out).read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert 'dir="rtl"' in content
        assert 'charset="utf-8"' in content
        assert 'lang="he"' in content

    def test_html_contains_drawing_data(self, tmp_path, sample_drawing):
        out = pdf_report.build_assembly_html(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "test.html",
            single_mode=True,
        )
        content = Path(out).read_text(encoding="utf-8")
        assert "TEST-001" in content
        assert "ACME Inc." in content
        assert "ALUMINUM 6061-T6" in content
        assert "MIL-DTL-5541F" in content

    def test_html_contains_print_bar(self, tmp_path, sample_drawing):
        out = pdf_report.build_assembly_html(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "test.html",
            single_mode=True,
        )
        content = Path(out).read_text(encoding="utf-8")
        assert "window.print()" in content

    def test_html_contains_print_css(self, tmp_path, sample_drawing):
        out = pdf_report.build_assembly_html(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "test.html",
            single_mode=True,
        )
        content = Path(out).read_text(encoding="utf-8")
        assert "@page" in content
        assert "@media print" in content
        assert "size: A4" in content

    def test_assembly_mode_with_relationships(self, tmp_path, sample_drawing):
        rel = {
            "summary_he": "מכלול דמה לבדיקה.",
            "assemblies": [{
                "parent_part_number": "TEST-001",
                "parent_drawing_number": "TEST-001",
                "children": [
                    {"part_number": "CHILD-1", "qty": "2",
                     "description": "child 1", "drawing_number": "CHILD-1"},
                ],
            }],
            "orphans": [],
            "missing_children": [],
            "warnings_he": [],
        }
        out = pdf_report.build_assembly_html(
            drawings=[sample_drawing,
                      {**sample_drawing, "part_number": "CHILD-1"}],
            relationships=rel,
            out_path=tmp_path / "asm.html",
        )
        content = Path(out).read_text(encoding="utf-8")
        assert "CHILD-1" in content
        assert "מכלול דמה לבדיקה" in content


# ─────────────────────────────────────────────────────────────────
# 2. build_tree_html
# ─────────────────────────────────────────────────────────────────
class TestTreeHTML:
    def test_produces_valid_html(self, tmp_path, sample_drawing):
        out = pdf_report.build_tree_html(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "tree.html",
        )
        assert Path(out).exists()
        content = Path(out).read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert 'dir="rtl"' in content

    def test_contains_tree_specific_html(self, tmp_path, sample_drawing):
        out = pdf_report.build_tree_html(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "tree.html",
        )
        content = Path(out).read_text(encoding="utf-8")
        assert "עץ מוצר" in content


# ─────────────────────────────────────────────────────────────────
# 3. Excel exports continue to work (no regression)
# ─────────────────────────────────────────────────────────────────
class TestExcelStillWorks:
    def test_build_assembly_excel(self, tmp_path, sample_drawing):
        out = pdf_report.build_assembly_excel(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "test.xlsx",
        )
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0

    def test_build_tree_excel(self, tmp_path, sample_drawing):
        out = pdf_report.build_tree_excel(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "tree.xlsx",
        )
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0


# ─────────────────────────────────────────────────────────────────
# 4. Backwards-compat aliases (build_*_pdf → build_*_html)
# ─────────────────────────────────────────────────────────────────
class TestBackwardsCompat:
    def test_build_assembly_pdf_alias_exists(self):
        assert pdf_report.build_assembly_pdf is pdf_report.build_assembly_html

    def test_build_tree_pdf_alias_exists(self):
        assert pdf_report.build_tree_pdf is pdf_report.build_tree_html

    def test_alias_produces_html(self, tmp_path, sample_drawing):
        out = pdf_report.build_assembly_pdf(
            drawings=[sample_drawing], relationships=None,
            out_path=tmp_path / "test.html",
            single_mode=True,
        )
        content = Path(out).read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")


# ─────────────────────────────────────────────────────────────────
# 5. No more fitz dependency
# ─────────────────────────────────────────────────────────────────
class TestNoFitzImport:
    def test_module_does_not_expose_fitz(self):
        assert not hasattr(pdf_report, "fitz"), \
            "fitz import חזר! מטרת ה-migration ל-HTML הייתה להסיר אותו"

    def test_no_pdf_report_available_flag(self):
        assert not hasattr(pdf_report, "PDF_REPORT_AVAILABLE")

    def test_no_require_fitz_function(self):
        assert not hasattr(pdf_report, "_require_fitz")
