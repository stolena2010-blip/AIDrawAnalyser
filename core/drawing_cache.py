"""
Drawing Cache — שומר תוצאות חילוץ לפי MD5 של קובץ ה-PDF.

מטרה: חסוך כסף ב-API בעת עיבוד חוזר של אותו שרטוט (בדיקות, שרטוטים
חוזרים במכלולים, debugging).

מבנה:
  output/.cache/<md5>.json — תוצאת החילוץ השלמה
  Cache key = MD5 של תוכן הקובץ + גרסת המודל + version pipeline

ניתן לכבות דרך environment variable:
  DRAWING_CACHE_DISABLED=true
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from core.azure_client import _active_model  # noqa — internal use

logger = logging.getLogger(__name__)

# העלאה כשמשנים את pipeline — מבטל cache ישן
# v2: החזרת OCR-always-on ב-Stage 1 (תיקון regression: material wrong)
# v3: שדרוג stage_2 prompts (סיווג SURFACE TREATMENT, הטמעת תקנים, additional step_no+details)
# v4: שדרוג stage_1 (תיקון OCR 8↔B ברפאל) + stage_2 (marking method / packaging מפורט / multi-page)
# v5: stage_1 (P/N transposition + OCOLONE) + relationships (hierarchy) + BOM cross-ref + nested-root demote
# v6: הוספת insertion/deletion distance ב-P/N (BP7053A ↔ BP70534A) + קריאת cross-ref מוקדמת ב-UI
# v7: 7↔T OCR pair + pn/dwg normalization + purchased-parts בעץ + OCR_UNREADABLE BOM flag
# v8: ניקוי כפילויות OCR בתיאורי BOM + FILENAME_PN_MISMATCH warning + MARKING_PN_CROSS_REF scan
# v9: קטגוריות חדשות (welding/heat_treatment/NDT) + עיקרון content>step_no + MATERIAL rule + ENGRAVING rule
# v10: PAINTING section (TEXT COLOR) + ENGRAVING full content + 100% prefix + Z0 SQUEGLIA/AMSC normalization + QQ- obsolete spec warning
# v11: hallucination check (standards vs OCR) + self-ref BOM → PART + DWG prefix validator (BIRD=BAS) + hierarchical classification + UOS block
# v12: PRC fields (catalog_number/raw_weight/alternative_material/general_instructions) + PACKING mandatory + compound-step split + lowercase-spec warning
# v13: content-first classification + SERVICEABILITY TAG rule + TO-PS-DOC OCR normalization + os_level field + GENERAL INSTRUCTIONS also in section 20
# v14: Elbit customer profile + cage_code/material_formerly/environment_requirements fields + auto role=PART + FILLETS keyword + UOS ASME hints
# v15: DWG=P/N inference + REVISIONS table Rev fallback + Pickling/H-Embrittlement keywords + [NO_PACKING_REQUIREMENT_IN_DRAWING] + title/part_weight + Mechanico-Shaftech profile
# v16: code-level fallbacks (reconcile_drawing_number + reconcile_revision) + new validators (SUSPICIOUS_STANDARD + MISSING_SURFACE_PREP + MISSING_POST_PROCESS + MISSING_PACKING empty flag) + REMOVE BURRS prompt fix + revisions_history field
# v17: Tesseract OCR binary installed + ocr_fallback.py reads TESSERACT_PATH from env → OCR now actually runs (was silently disabled before), feeding OCR text to Stage 1/2 prompts and enabling material/standards cross-validation
# v18: assembly.py now runs generic validators (SUSPICIOUS_STANDARD / MISSING_SURFACE_PREP / MISSING_POST_PROCESS / INVALID_RAL / UNKNOWN_PAINT_BRAND / MISCLASSIFIED_COATING) — previously these fired only in single mode
CACHE_VERSION = "v18"

_CACHE_DIR = Path("output/.cache")


def is_cache_enabled() -> bool:
    return os.getenv("DRAWING_CACHE_DISABLED", "").lower() != "true"


def _compute_file_hash(file_path: Path) -> str:
    """MD5 של תוכן הקובץ (לא של השם — כדי שאותו קובץ עם שם אחר יזוהה)."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_key(file_path: Path, extra: str = "") -> str:
    """
    מפתח cache = md5(file) + model + version + extra.
    שינוי במודל/pipeline → cache miss → הרצה טרייה.
    """
    file_hash = _compute_file_hash(file_path)
    model = _active_model()
    return f"{CACHE_VERSION}_{model}_{file_hash}_{extra}".replace("/", "_")


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def get_cached_result(file_path: str | Path, extra: str = "") -> dict | None:
    """מחזיר תוצאה שמורה אם קיימת, אחרת None."""
    if not is_cache_enabled():
        return None

    file_path = Path(file_path)
    if not file_path.exists():
        return None

    try:
        key = _cache_key(file_path, extra)
        path = _cache_path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("🎯 Cache HIT: %s (key=%s)", file_path.name, key[:40])
        # סמן שזו תוצאה cached
        data["_cache_hit"] = True
        return data
    except Exception as exc:
        logger.warning("Cache read failed: %s", exc)
        return None


def save_cached_result(file_path: str | Path, result: dict, extra: str = "") -> None:
    """שומר תוצאה ל-cache. שקט במקרה של כישלון (cache הוא בונוס, לא חובה)."""
    if not is_cache_enabled():
        return
    if not result:
        return

    file_path = Path(file_path)
    if not file_path.exists():
        return

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key = _cache_key(file_path, extra)
        path = _cache_path(key)
        # אל תשמור את דגל ה-cache עצמו
        clean = {k: v for k, v in result.items() if k != "_cache_hit"}
        path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("💾 Cache SAVED: %s (key=%s)", file_path.name, key[:40])
    except Exception as exc:
        logger.warning("Cache write failed: %s", exc)


def clear_cache() -> int:
    """מוחק את כל ה-cache. מחזיר מספר קבצים שנמחקו."""
    if not _CACHE_DIR.exists():
        return 0
    count = 0
    for f in _CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    logger.info("Cache cleared: %d files removed", count)
    return count


def cache_stats() -> dict:
    """מחזיר סטטיסטיקות על ה-cache: # קבצים, נפח כולל."""
    if not _CACHE_DIR.exists():
        return {"count": 0, "size_mb": 0.0, "enabled": is_cache_enabled()}
    files = list(_CACHE_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in files)
    return {
        "count": len(files),
        "size_mb": round(total_size / 1024 / 1024, 2),
        "enabled": is_cache_enabled(),
    }
