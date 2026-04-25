"""
Orchestration tests ל-core.assembly.pipeline — בודקים שה-pipeline קורא לכל
שלביו בסדר הנכון, מעביר תוצאות בין שלבים, וכותב cache. **לא** בודקים את
איכות החילוץ עצמו (זה תפקיד ה-regression tests + הרצות יד-בטך על נתונים אמיתיים).

Mock strategy: פוצים את `_call_vision` ו-`pdf_to_images` כדי לא לקרוא
לAzure / לרנדר PDF. הקלט/פלט בכל שלב נשלט ידנית.

הרצה:
    pytest tests/test_assembly_pipeline.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_pdf(tmp_path):
    """קובץ PDF מינימלי שעובר את validate_pdf_source (magic bytes + size)."""
    p = tmp_path / "BP70534A-A.pdf"
    p.write_bytes(b"%PDF-1.4\n" + b"x" * 1000)
    return p


@pytest.fixture
def mock_azure_usage():
    """אובייקט Usage מינימלי שמדומה ל-OpenAI Usage."""
    return SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)


@pytest.fixture
def stage1_result():
    """פלט typical של Stage 1 — שדות בסיסיים."""
    return {
        "part_number": "BP70534A",
        "drawing_number": "BP70534A",
        "revision": "A",
        "customer": "RAFAEL Advanced Defense Systems Ltd.",
        "cage_code": "1931",
        "material": "AL 6061-T6",
        "title": "TEST DRAWING",
        "assembly_role": "PART",
        "bom_items": [],
    }


@pytest.fixture
def stage2_result():
    """פלט typical של Stage 2 — תהליכים + תקנים."""
    return {
        "standards": ["MIL-STD-130"],
        "machining_processes": [],
        "coating_processes": [],
        "painting_processes": [],
        "additional_processes": [],
        "packaging_notes": {
            "en": "PACKING SHALL PREVENT CORROSION AND PHYSICAL DAMAGE "
                  "DURING PROCESS, STORAGE AND SHIPMENT",
            "he": "",
        },
        "notes": "",
        "final_approval": [],
    }


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    """כל בדיקה מקבלת תיקיית cache משלה — אין דליפה בין בדיקות."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr("core.drawing_cache._CACHE_DIR", cache_dir)
    return cache_dir


@pytest.fixture
def mock_pipeline_externals(stage1_result, stage2_result, mock_azure_usage):
    """
    Patches קבועים לכל בדיקות ה-pipeline:
    - pdf_to_images: מחזיר רשימת base64 דמה
    - _call_vision: מחזיר stage1 בקריאה ראשונה, stage2 בשנייה
    - is_ocr_available: False (מוסיר את OCR לחלוטין)
    - get_client / get_deployment: ערכי דמה
    """
    call_count = {"n": 0}

    def fake_call_vision(client, deployment, prompt, images):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return stage1_result.copy(), mock_azure_usage
        return stage2_result.copy(), mock_azure_usage

    with patch("core.assembly.pipeline.pdf_to_images", return_value=["BASE64_PAGE_1"]), \
         patch("core.assembly.pipeline._call_vision", side_effect=fake_call_vision) as cv, \
         patch("core.assembly.pipeline.is_ocr_available", return_value=False), \
         patch("core.assembly.pipeline.get_client", return_value=MagicMock()), \
         patch("core.assembly.pipeline.get_deployment", return_value="gpt-test"):
        yield {"call_vision": cv, "call_count": call_count}


# ─────────────────────────────────────────────────────────────────
# extract_assembly_drawing — orchestration
# ─────────────────────────────────────────────────────────────────
class TestExtractAssemblyDrawingOrchestration:
    def test_calls_vision_twice_for_stage1_and_stage2(self, fake_pdf, mock_pipeline_externals):
        from core.assembly.pipeline import extract_assembly_drawing
        extract_assembly_drawing(fake_pdf)
        assert mock_pipeline_externals["call_count"]["n"] == 2

    def test_result_has_required_metadata_fields(self, fake_pdf, mock_pipeline_externals):
        from core.assembly.pipeline import extract_assembly_drawing
        result = extract_assembly_drawing(fake_pdf)
        assert "_cost_info" in result
        assert "_ocr_used" in result
        assert "source_filename" in result
        assert result["source_filename"] == "BP70534A-A.pdf"

    def test_result_merges_stage1_and_stage2(self, fake_pdf, mock_pipeline_externals):
        from core.assembly.pipeline import extract_assembly_drawing
        result = extract_assembly_drawing(fake_pdf)
        # stage1 fields
        assert result["part_number"] == "BP70534A"
        assert result["customer"] == "RAFAEL Advanced Defense Systems Ltd."
        # stage2 fields
        assert "standards" in result
        assert result["standards"] == ["MIL-STD-130"]

    def test_cache_hit_skips_vision_call(self, fake_pdf, mock_pipeline_externals):
        from core.assembly.pipeline import extract_assembly_drawing
        # 1st run: cache MISS → 2 vision calls
        extract_assembly_drawing(fake_pdf)
        first_count = mock_pipeline_externals["call_count"]["n"]
        # 2nd run: cache HIT → no additional calls
        result = extract_assembly_drawing(fake_pdf)
        assert mock_pipeline_externals["call_count"]["n"] == first_count
        assert result["part_number"] == "BP70534A"

    def test_missing_file_raises_pdf_error(self, mock_pipeline_externals):
        from core.assembly.pipeline import extract_assembly_drawing
        from core.exceptions import PDFError
        with pytest.raises(PDFError) as exc:
            extract_assembly_drawing("/nonexistent/path/to/file.pdf")
        assert "לא נמצא" in exc.value.user_message

    def test_post_processing_runs_after_extraction(self, fake_pdf, mock_pipeline_externals,
                                                    stage1_result, stage2_result, mock_azure_usage):
        """
        אם המודל מחזיר PN עם OCR confusion (BNB0760B במקום BN80760B)
        ושם הקובץ הוא BN80760B — reconcile_part_number חייב לתקן.
        זה מאמת שה-pipeline באמת קורא ל-post-processing.
        """
        # Override fake_pdf לשם קובץ עם PN אמיתי
        from core.assembly.pipeline import extract_assembly_drawing
        # Use a fixed bad-OCR stage1 with mismatched filename
        bad_stage1 = stage1_result.copy()
        bad_stage1["part_number"] = "BNB0760B"
        bad_stage1["drawing_number"] = "BNB0760B"

        fname = fake_pdf.parent / "BN80760B-A-PD-bn80760b_a.pdf"
        fname.write_bytes(b"%PDF-1.4\n" + b"x" * 1000)

        # Re-mock with the bad stage1
        call_count = {"n": 0}
        def fake_call(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return bad_stage1.copy(), mock_azure_usage
            return stage2_result.copy(), mock_azure_usage

        with patch("core.assembly.pipeline._call_vision", side_effect=fake_call):
            result = extract_assembly_drawing(fname)

        # post-processing should have corrected PN from filename
        assert result["part_number"] == "BN80760B", \
            "reconcile_part_number didn't fire post-processing"

    def test_validators_collect_into_pn_warnings(self, fake_pdf, mock_pipeline_externals,
                                                   stage1_result, stage2_result, mock_azure_usage):
        """אם validator מזהה משהו — צריך להופיע ב-_pn_warnings."""
        from core.assembly.pipeline import extract_assembly_drawing
        # Stage 2 עם תקן חשוד
        bad_stage2 = stage2_result.copy()
        bad_stage2["standards"] = ["AWI-STD-1916"]  # קידומת לא מוכרת

        call_count = {"n": 0}
        def fake_call(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return stage1_result.copy(), mock_azure_usage
            return bad_stage2.copy(), mock_azure_usage

        with patch("core.assembly.pipeline._call_vision", side_effect=fake_call):
            result = extract_assembly_drawing(fake_pdf)

        assert "_pn_warnings" in result
        # SUSPICIOUS_STANDARD צריך להופיע באחד מההודעות
        all_warnings = " | ".join(result["_pn_warnings"])
        assert "SUSPICIOUS_STANDARD" in all_warnings or "AWI" in all_warnings

    def test_pdf_validation_error_propagates_without_vision_call(self, fake_pdf,
                                                                   mock_pipeline_externals):
        """אם pdf_to_images זורק PDFError (למשל validation fail) — נתחיל propagate
        בלי לקרוא ל-Vision."""
        from core.assembly.pipeline import extract_assembly_drawing
        from core.exceptions import PDFError

        def fake_raise(*args, **kwargs):
            raise PDFError(
                "PDF too large",
                user_message="הקובץ גדול מדי.",
                suggestion="הקטיני אותו.",
            )
        with patch("core.assembly.pipeline.pdf_to_images", side_effect=fake_raise):
            with pytest.raises(PDFError) as exc:
                extract_assembly_drawing(fake_pdf)
            assert "גדול מדי" in exc.value.user_message
        # Vision לא נקרא — קריאת validation נעשתה לפני
        assert mock_pipeline_externals["call_count"]["n"] == 0


# ─────────────────────────────────────────────────────────────────
# analyze_relationships — orchestration
# ─────────────────────────────────────────────────────────────────
class TestAnalyzeRelationshipsOrchestration:
    def test_empty_results_returns_default_structure(self):
        from core.assembly.relationships import analyze_relationships
        result = analyze_relationships([])
        assert "summary_he" in result
        assert result["assemblies"] == []
        assert result["orphans"] == []

    def test_single_drawing_calls_text_api_once(self, mock_azure_usage):
        from core.assembly.relationships import analyze_relationships
        fake_response = (
            {"summary_he": "test", "assemblies": [], "orphans": [],
             "missing_children": [], "warnings_he": []},
            mock_azure_usage,
        )
        with patch("core.assembly.relationships._call_text_json", return_value=fake_response) as ctj, \
             patch("core.assembly.relationships.get_client", return_value=MagicMock()), \
             patch("core.assembly.relationships.get_deployment", return_value="gpt-test"):
            result = analyze_relationships([
                {"part_number": "BP70534A", "drawing_number": "BP70534A",
                 "assembly_role": "PART", "bom_items": []},
            ])
            assert ctj.call_count == 1
            assert "_cost_info" in result

    def test_filters_overview_image_from_assemblies_tree(self, mock_azure_usage):
        """אם תמונת overview הוחזרה כ-assembly — צריכה להיות מסוננת."""
        from core.assembly.relationships import analyze_relationships
        fake_response = (
            {
                "summary_he": "test",
                "assemblies": [
                    {"parent_part_number": "OVERVIEW.PNG",
                     "parent_drawing_number": "OVERVIEW.PNG",
                     "children": []},
                    {"parent_part_number": "BP70534A",
                     "parent_drawing_number": "BP70534A",
                     "children": []},
                ],
                "orphans": [], "missing_children": [], "warnings_he": [],
            },
            mock_azure_usage,
        )
        with patch("core.assembly.relationships._call_text_json", return_value=fake_response), \
             patch("core.assembly.relationships.get_client", return_value=MagicMock()), \
             patch("core.assembly.relationships.get_deployment", return_value="gpt-test"):
            result = analyze_relationships([
                {"part_number": "BP70534A", "assembly_role": "PART"},
                {"part_number": "OVERVIEW.PNG",
                 "assembly_role": "Assembly Overview Image",
                 "source_filename": "overview.png"},
            ])
            # Overview הוסר; רק BP70534A נשאר
            assert len(result["assemblies"]) == 1
            assert result["assemblies"][0]["parent_part_number"] == "BP70534A"
            # אזהרה הופיעה
            assert any("IMAGE_FILTERED" in w for w in result["warnings_he"])
