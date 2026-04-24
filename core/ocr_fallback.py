"""
OCR fallback — משתמש ב-Tesseract להוצאת טקסט כשה-Vision API לא מזהה מספיק.

שימוש: כאשר Stage 1 מחזיר שדות קריטיים ריקים, נריץ OCR ונחזיר את הטקסט
ל-Stage 1 עם prompt משופר שכולל את הטקסט שהוצא.
"""
import logging
import os
from pathlib import Path

from .pdf_utils import _render_pdf_to_pil
from .exceptions import OCRUnavailableError

logger = logging.getLogger(__name__)

try:
    import pytesseract
    TESSERACT_AVAILABLE = True

    # אם המשתמש הגדיר TESSERACT_PATH ב-.env או אם Tesseract מותקן במיקום
    # ברירת-המחדל הנפוץ ב-Windows אבל לא ב-PATH — הצבע עליו ישירות.
    _TESSERACT_DEFAULTS = [
        os.getenv("TESSERACT_PATH", "").strip(),
        r"C:\Program Files\Tesseract-OCR",
        r"C:\Program Files (x86)\Tesseract-OCR",
    ]
    for _dir in _TESSERACT_DEFAULTS:
        if not _dir:
            continue
        _exe = Path(_dir) / "tesseract.exe"
        if _exe.exists():
            pytesseract.pytesseract.tesseract_cmd = str(_exe)
            logger.info("Tesseract binary: %s", _exe)
            break
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract לא מותקן — OCR fallback לא יפעל")


def is_ocr_available() -> bool:
    """בודק אם Tesseract זמין במערכת."""
    if not TESSERACT_AVAILABLE:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text_from_pdf(
    pdf_path: str | Path,
    languages: str = "eng+heb",
    dpi: int = 300,
) -> str:
    """
    מפיק טקסט מ-PDF באמצעות OCR.

    Args:
        pdf_path: נתיב ל-PDF
        languages: שפות Tesseract (eng+heb = אנגלית + עברית)
        dpi: רזולוציה (גבוה יותר = דיוק יותר טוב, איטי יותר)

    Returns:
        טקסט משורשר מכל העמודים
    """
    if not is_ocr_available():
        raise OCRUnavailableError(
            "Tesseract not available",
            suggestion=(
                "התקיני Tesseract — "
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki | "
                "Linux: apt install tesseract-ocr tesseract-ocr-heb | "
                "Mac: brew install tesseract tesseract-lang"
            ),
        )

    pdf_path = Path(pdf_path)
    logger.info(f"OCR מופעל על: {pdf_path.name}")

    images = _render_pdf_to_pil(str(pdf_path), dpi=dpi)

    all_text = []
    for idx, img in enumerate(images, 1):
        try:
            text = pytesseract.image_to_string(img, lang=languages)
            all_text.append(f"=== עמוד {idx} ===\n{text}")
        except Exception as e:
            logger.warning(f"OCR נכשל על עמוד {idx}: {e}")
            continue

    full_text = "\n\n".join(all_text)
    logger.info(f"OCR חילץ {len(full_text)} תווים")
    return full_text


def should_use_fallback(stage1_result: dict) -> bool:
    """
    בודק אם צריך להפעיל OCR fallback.

    קריטריונים (אם 2+ שדות קריטיים ריקים — הפעל):
    - part_number
    - material
    - drawing_number
    """
    critical_fields = ["part_number", "material", "drawing_number"]
    empty_count = sum(
        1 for field in critical_fields
        if not stage1_result.get(field) or str(stage1_result.get(field)).strip() == ""
    )
    return empty_count >= 2


def build_enhanced_prompt(base_prompt: str, ocr_text: str) -> str:
    """בונה prompt משופר שכולל את טקסט ה-OCR."""
    ocr_snippet = ocr_text[:3000]

    return f"""{base_prompt}

---
OCR reference text extracted from the drawing (use as supporting evidence for text, numbers and standards):
{ocr_snippet}
---

Note: The drawing images are the primary source. Use OCR text to verify digits, standards and Hebrew/English text direction.
"""
