"""
Unit tests ל-core.pdf_utils — בעיקר input validation.

הרצה:
    pytest tests/test_pdf_utils.py -v
"""

import pytest

from core.exceptions import PDFError
from core.pdf_utils import (
    MAX_PDF_MB,
    MAX_PDF_PAGES,
    _validate_pdf_source,
)


# ─────────────────────────────────────────────────────────────────
# _validate_pdf_source
# ─────────────────────────────────────────────────────────────────
class TestValidatePdfSource:
    # ── path-based ──
    def test_valid_pdf_path_passes(self, tmp_path):
        # קובץ עם magic bytes נכונים — לא זורק
        p = tmp_path / "ok.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"x" * 1000)
        # לא זורק
        _validate_pdf_source(p)

    def test_nonexistent_path_passes_through(self, tmp_path):
        # מסלול לא קיים — לא זורק (יטופל ע"י fitz.open עם הודעה ידידותית)
        p = tmp_path / "missing.pdf"
        _validate_pdf_source(p)  # שותק

    def test_oversized_file_raises(self, tmp_path, monkeypatch):
        # קובץ מעל מגבלה
        monkeypatch.setattr("core.pdf_utils.MAX_PDF_MB", 1)  # 1MB
        p = tmp_path / "big.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024))  # 2MB
        with pytest.raises(PDFError) as exc_info:
            _validate_pdf_source(p)
        assert "גדול מדי" in exc_info.value.user_message
        assert "MAX_PDF_MB" in exc_info.value.suggestion

    def test_bad_magic_bytes_raises(self, tmp_path):
        # קובץ ZIP עם סיומת .pdf — magic bytes שגויים
        p = tmp_path / "fake.pdf"
        p.write_bytes(b"PK\x03\x04" + b"x" * 1000)  # ZIP header
        with pytest.raises(PDFError) as exc_info:
            _validate_pdf_source(p)
        assert "אינו PDF תקני" in exc_info.value.user_message

    def test_empty_file_raises_bad_magic(self, tmp_path):
        # קובץ ריק
        p = tmp_path / "empty.pdf"
        p.write_bytes(b"")
        with pytest.raises(PDFError):
            _validate_pdf_source(p)

    # ── bytes-based ──
    def test_valid_bytes_pass(self):
        data = b"%PDF-1.4\n" + b"x" * 1000
        _validate_pdf_source(data)

    def test_oversized_bytes_raises(self, monkeypatch):
        monkeypatch.setattr("core.pdf_utils.MAX_PDF_MB", 1)
        data = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024)
        with pytest.raises(PDFError):
            _validate_pdf_source(data)

    def test_bytes_bad_magic_raises(self):
        data = b"<html>not a pdf</html>"
        with pytest.raises(PDFError) as exc_info:
            _validate_pdf_source(data)
        assert "PDF" in exc_info.value.user_message

    def test_bytearray_supported(self):
        data = bytearray(b"%PDF-1.4\n" + b"x" * 1000)
        _validate_pdf_source(data)

    # ── env var configurability ──
    def test_max_mb_default_is_50(self):
        # ברירת המחדל לא צריכה להיות נמוכה מדי
        assert MAX_PDF_MB >= 10

    def test_max_pages_default_is_reasonable(self):
        # שרטוטים אמיתיים ≤ 10 עמודים, מגבלה ברירת מחדל סבירה
        assert 5 <= MAX_PDF_PAGES <= 50


# ─────────────────────────────────────────────────────────────────
# Integration: pdf_to_images עם PDF אמיתי קטן
# ─────────────────────────────────────────────────────────────────
def _create_minimal_pdf(pages: int = 1) -> bytes:
    """יוצר PDF מינימלי בזיכרון עם N עמודים — דרך PyMuPDF (קיים בפרויקט)."""
    import fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)  # Letter
        page.insert_text((100, 100), f"Test page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


class TestPdfToImagesIntegration:
    """בדיקות שמריצות את pdf_to_images על PDF אמיתי (לא רק validation)."""

    def test_renders_single_page_pdf(self, tmp_path):
        from core.pdf_utils import pdf_to_images
        pdf_path = tmp_path / "single.pdf"
        pdf_path.write_bytes(_create_minimal_pdf(pages=1))
        images = pdf_to_images(pdf_path, dpi=72)  # DPI נמוך = מהיר
        assert len(images) == 1
        # base64 string לא ריק
        assert isinstance(images[0], str)
        assert len(images[0]) > 100

    def test_renders_multi_page_pdf(self, tmp_path):
        from core.pdf_utils import pdf_to_images
        pdf_path = tmp_path / "multi.pdf"
        pdf_path.write_bytes(_create_minimal_pdf(pages=3))
        images = pdf_to_images(pdf_path, dpi=72)
        assert len(images) == 3

    def test_validation_blocks_oversized_via_pdf_to_images(self, tmp_path, monkeypatch):
        """ולידציה אמיתית — קובץ חורג גודל לא מגיע ל-render."""
        from core.pdf_utils import pdf_to_images
        monkeypatch.setattr("core.pdf_utils.MAX_PDF_MB", 1)
        big = tmp_path / "huge.pdf"
        big.write_bytes(b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024))
        with pytest.raises(PDFError) as exc:
            pdf_to_images(big)
        assert "גדול מדי" in exc.value.user_message

    def test_validation_blocks_too_many_pages(self, tmp_path, monkeypatch):
        from core.pdf_utils import pdf_to_images
        monkeypatch.setattr("core.pdf_utils.MAX_PDF_PAGES", 2)
        pdf_path = tmp_path / "many.pdf"
        pdf_path.write_bytes(_create_minimal_pdf(pages=5))
        with pytest.raises(PDFError) as exc:
            pdf_to_images(pdf_path)
        assert "עמודים" in exc.value.user_message
        assert "5" in exc.value.user_message  # page count מופיע בהודעה

    def test_corrupt_pdf_raises_friendly_error(self, tmp_path):
        from core.pdf_utils import pdf_to_images
        # PDF עם magic bytes נכונים אבל תוכן פגום — עובר validation, נופל ב-fitz
        bad = tmp_path / "corrupt.pdf"
        bad.write_bytes(b"%PDF-1.4\nNOT A REAL PDF AT ALL")
        with pytest.raises(PDFError) as exc:
            pdf_to_images(bad)
        assert "PDF" in exc.value.user_message

    def test_bytes_input_supported(self):
        from core.pdf_utils import pdf_to_images
        data = _create_minimal_pdf(pages=1)
        images = pdf_to_images(data, dpi=72)
        assert len(images) == 1


class TestImageFileToB64:
    def test_png_loads(self, tmp_path):
        from PIL import Image

        from core.pdf_utils import image_file_to_b64
        p = tmp_path / "test.png"
        Image.new("RGB", (200, 200), color="white").save(p)
        result = image_file_to_b64(p)
        assert isinstance(result, list)
        assert len(result) == 1
        assert len(result[0]) > 100  # base64 לא ריק

    def test_jpg_converted_to_png(self, tmp_path):
        from PIL import Image

        from core.pdf_utils import image_file_to_b64
        p = tmp_path / "test.jpg"
        Image.new("RGB", (200, 200), color="blue").save(p)
        result = image_file_to_b64(p)
        assert len(result) == 1

    def test_nonexistent_image_raises(self):
        from core.exceptions import ImageError
        from core.pdf_utils import image_file_to_b64
        with pytest.raises(ImageError):
            image_file_to_b64("/no/such/file.png")
