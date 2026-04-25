"""
המרת PDF לתמונות base64 לצורך שליחה ל-Vision API.
משתמש ב-pypdfium2 (Apache 2.0) — לא דורש בינארים חיצוניים (Poppler).
"""
import base64
import io
import os
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from .exceptions import ImageError, PDFError

# ───────────────────────────────────────────────────────────────
# מגבלות קלט — מגינות מפני קבצים שאין להם הצדקה עסקית.
# הסיבה העיקרית היא **בקרת עלות**: PDF של 200 עמודים בעלות $0.05 לעמוד
# ב-Vision API = $10 לקובץ אחד. שרטוטים הנדסיים אמיתיים ≤ 5-10 עמודים.
# ───────────────────────────────────────────────────────────────
MAX_PDF_MB = int(os.environ.get("MAX_PDF_MB", "50"))
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", "20"))
_PDF_MAGIC = b"%PDF-"


def _validate_pdf_source(pdf_source) -> None:
    """
    מאמת קלט לפני העברה ל-fitz:
      • גודל קובץ ≤ MAX_PDF_MB (ברירת מחדל 50MB)
      • magic bytes נכונים (`%PDF-`) — מונע נסיון פרסור של קבצים אחרים
    בדיקת page_count מתבצעת אחרי פתיחה, ב-_render_pdf_to_pil.
    """
    if isinstance(pdf_source, (str, Path)):
        path = Path(pdf_source)
        if not path.exists():
            return  # יטופל ב-fitz.open עם הודעה ידידותית
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_PDF_MB:
            raise PDFError(
                f"PDF too large: {size_mb:.1f}MB > {MAX_PDF_MB}MB",
                user_message=f"הקובץ '{path.name}' גדול מדי ({size_mb:.1f}MB).",
                suggestion=(
                    f"מגבלה: {MAX_PDF_MB}MB. אפשר לשנות עם משתנה הסביבה "
                    f"MAX_PDF_MB. שרטוטים הנדסיים בדרך כלל מתחת ל-10MB."
                ),
                context={"size_mb": size_mb, "limit_mb": MAX_PDF_MB},
            )
        with path.open("rb") as f:
            header = f.read(5)
        if header != _PDF_MAGIC:
            raise PDFError(
                f"Not a valid PDF (bad magic bytes): {header!r}",
                user_message=f"הקובץ '{path.name}' אינו PDF תקני.",
                suggestion="ודאי שהסיומת תואמת לתוכן (לא קובץ ZIP/DOCX וכד').",
                context={"detected_magic": header.hex()},
            )
    elif isinstance(pdf_source, (bytes, bytearray)):
        size_mb = len(pdf_source) / (1024 * 1024)
        if size_mb > MAX_PDF_MB:
            raise PDFError(
                f"PDF stream too large: {size_mb:.1f}MB > {MAX_PDF_MB}MB",
                user_message=f"ה-PDF גדול מדי ({size_mb:.1f}MB).",
                suggestion=f"מגבלה: {MAX_PDF_MB}MB.",
                context={"size_mb": size_mb, "limit_mb": MAX_PDF_MB},
            )
        if not bytes(pdf_source[:5]) == _PDF_MAGIC:
            raise PDFError(
                "PDF stream has invalid magic bytes",
                user_message="הנתונים שהועלו אינם PDF תקני.",
                suggestion="ודאי שהקובץ במקור הוא PDF.",
                context={"detected_magic": bytes(pdf_source[:5]).hex()},
            )


def _render_pdf_to_pil(pdf_source, dpi: int = 200) -> list[Image.Image]:
    """ממיר PDF לרשימת תמונות PIL באמצעות pypdfium2."""
    _validate_pdf_source(pdf_source)
    try:
        if isinstance(pdf_source, (str, Path)):
            doc = pdfium.PdfDocument(str(pdf_source))
        else:
            doc = pdfium.PdfDocument(bytes(pdf_source))
    except PDFError:
        raise
    except Exception as exc:
        name = Path(pdf_source).name if isinstance(pdf_source, (str, Path)) else "PDF"
        raise PDFError(
            f"Failed to open PDF: {exc}",
            user_message=f"לא ניתן לפתוח את ה-PDF: {name}",
            suggestion="ייתכן שהקובץ פגום או מוגן בסיסמה. נסי קובץ אחר.",
            context={"source": str(pdf_source), "original_error": str(exc)},
        ) from exc

    # בדיקת page_count אחרי פתיחה — לפני שמתחילים render יקר.
    page_count = len(doc)
    if page_count > MAX_PDF_PAGES:
        doc.close()
        name = Path(pdf_source).name if isinstance(pdf_source, (str, Path)) else "PDF"
        raise PDFError(
            f"PDF has too many pages: {page_count} > {MAX_PDF_PAGES}",
            user_message=(
                f"הקובץ '{name}' מכיל {page_count} עמודים — חורג מהמגבלה "
                f"של {MAX_PDF_PAGES}."
            ),
            suggestion=(
                "שרטוטים הנדסיים בדרך כלל ≤ 10 עמודים. אם זה PDF מאוחד "
                "של מספר שרטוטים — פצלי אותו. ניתן להגדיל עם MAX_PDF_PAGES."
            ),
            context={"page_count": page_count, "limit": MAX_PDF_PAGES},
        )

    scale = dpi / 72.0

    images: list[Image.Image] = []
    try:
        for page in doc:
            bitmap = page.render(scale=scale, rotation=0)
            img = bitmap.to_pil()
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
    finally:
        doc.close()

    return images


def pdf_to_images(pdf_source, dpi: int = 400) -> list[str]:
    """
    ממיר PDF לרשימת תמונות base64.

    Args:
        pdf_source: נתיב לקובץ PDF או bytes
        dpi: רזולוציה (ברירת מחדל 400 — קריטי לקריאת ספרות קטנות
             ב-title block של שרטוטים הנדסיים)

    Returns:
        רשימה של תמונות base64 PNG (אחת לכל עמוד)
    """
    images = _render_pdf_to_pil(pdf_source, dpi=dpi)

    base64_images = []
    for img in images:
        if img.mode != "RGB":
            img = img.convert("RGB")

        # מגבלת GPT-4o היא 2048 על הצד הקצר ו-768 על הצד הארוך במצב "high".
        # אנחנו לא מקטינים מתחת ל-4000 — Vision מקטין בעצמו אך משמר את הרזולוציה
        # היחסית של אזור ה-title block. הקטנה מוקדמת מאבדת ספרות.
        max_dim = 4096
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # PNG חסר-אובדן — קריטי לטקסט קטן (JPEG מוסיף ארטיפקטים סביב ספרות).
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        base64_images.append(b64)

    return base64_images


def image_file_to_b64(image_path) -> list[str]:
    """ממיר קובץ תמונה (PNG/JPG/JPEG/WEBP) ל-base64 PNG בודד.

    משמש לטעינת תמונות תרשים-מכלול (Exploded View) במצב המכלולים.
    מחזיר רשימה בת איבר אחד כדי להתאים ל-API של ‎pdf_to_images‎.
    """
    try:
        img = Image.open(image_path)
    except Exception as exc:
        raise ImageError(
            f"Failed to open image: {exc}",
            user_message=f"לא ניתן לפתוח את התמונה: {Path(image_path).name}",
            suggestion="ודאי שהקובץ בפורמט PNG/JPG/WEBP ואינו פגום.",
            context={"path": str(image_path), "original_error": str(exc)},
        ) from exc
    rgb_img: Image.Image = img.convert("RGB") if img.mode != "RGB" else img

    max_dim = 4096
    if max(rgb_img.size) > max_dim:
        rgb_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    rgb_img.save(buffer, format="PNG", optimize=True)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return [b64]
