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
# v19: Easy Wins from 20-drawing batch analysis — (a) CAGE→Customer map + customer name normalization, (b) validate_standards ignore-list (ISO STANDARDS, RoHS, VT/PT/GTAW, etc.) + normalize PS-/Y14. spacing + added prefixes (RAFDOCS/TILDOCS/PS/SM/FED.STD./A-A-/ANSI-slash), (c) prompt fix: explicit ban on generic "ISO STANDARDS" and test-method/color entries in standards list
# v20: Medium Effort fixes — (a) prefer_filename_pn_if_substring: filename-level P/N override for non-RAFAEL formats (330-53-14-J8409 → 330-... not 53-...-R), (b) extract_generic_pn_from_filename: 4 new patterns for non-alpha P/N formats, (c) prompt strengthening for multi-sheet BOM extraction (Elbit/IAI/ALEXANDER SCHNEIDER), (d) prompt strengthening for full revisions_history table (all rows, not just latest), (e) _extract_material_direct: regex-based material search across OCR text (fallback when label-based search misses)
# v21: Batch-2 findings fixes — (a) J↔U OCR confusion pair added (BJ14981A/BU14981A), (b) filename_override_if_suspicious_pn: aggressive override when extracted P/N is "ITEM X" / header / has <0.15 digit similarity to filename (catches UCP-280-89981-602 → "ITEM 602", 1028287A → "AZO-34008-DD"), (c) PS-TILDOCS/PS-DOC prefixes whitelisted in validate_standards, (d) expanded CAGE extraction prompt with per-customer CAGE codes (RAFAEL=1931, IAI=1933A, Elbit=0772A/1410A)
# v22: Batch-3 findings fixes — (a) filename_override enhanced with _char_jaccard + _sequences_compatible + truncation-detection (catches NV03-58-28 vs 893-65503682-55 and TH15012 vs THR1510712), (b) PS-prefix OCR normalization (PSSOO100 → PS500100, PS_O_digit → PS_0_digit), (c) CAGE_TO_CUSTOMER expanded (1931A/1910A/1937A/2198A), (d) clean_cage_code() rejects invalid CAGE with special chars ("1!1")
# v23: Easy Wins follow-up — (a) infer_cage_from_customer: reverse lookup (RAFAEL→1931, IAI→1910A) when customer known but CAGE empty, (b) salvage_revision: fix mangled "RC"→"C"/"REV C"→"C" from OCR merging Rev prefix with value, (c) validate_customer_prefix_consistency: flag P/N BAS→not-BIRD, BP→not-RAFAEL mismatches (hallucinated customer detection), (d) customer-internal SPEC whitelist in validate_standards (KRETOS I-*, IAI 5902*, APPLIED MATERIALS 0023-/0250-*, Laor W*, RAFAEL GEN_*) — these no longer flagged as SUSPICIOUS
# v24: Batch-4 fine-tuning — (a) L↔I OCR confusion pair (EL0498↔EI0498), (b) IAI whitelist extended to 1092[A-Z]\d{3} + DOC\d{7,}, ELTA customer mapped to same patterns, (c) new prefixes in validate_standards whitelist (TT-[A-Z], AISI, UNS, RAFAEL PROCEDURE, P.S.), (d) regex-based ignore-list for RoHS-family variants (RoHS DIRECTIVE, RoHS II/III, REACH COMPLIANCE)
# v25: Refactor + bug fix — (a) CAGE/customer/PN-prefix mappings extracted to data/customer_mappings.json (loaded by core/_customer_data.py) — non-developers can now add a customer without touching code, (b) bug fix in extract_generic_pn_from_filename: _FILENAME_CORE_RE path now strips trailing dash (e.g., "30-168217-E-PDM-..." → "30-168217-E" instead of "30-168217-E-")
# v26: PN-mismatch findings from new7/ batch — (a) _strip_file_decorations now handles "_asm_temp_" prefix (assembly mode upload prefix) — fixes 4 cases where extract_generic_pn_from_filename returned "" because of the prefix (DD345326, ETN1110422, HSA00756-1M004, ...), (b) _is_suspicious_pn now flags PNs with internal whitespace ("YT35 MD FTG1242544") and pure-digits-shorter-than-7 ("11042" fragment of "ETN1110422") — both trigger filename_override, (c) new override path: same-length + single digit-position diff + narrow filename extract succeeded → prefer filename — catches BO27303A→BO27304A (4↔3 not in OCR pairs)
CACHE_VERSION = "v26"

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


def cleanup_stale_cache(keep_versions: int = 1) -> int:
    """
    מוחק קבצי cache מגרסאות ישנות. ה-cache key מתחיל ב-`vNN_` —
    אוסף את כל הגרסאות הקיימות ושומר רק את ``keep_versions`` החדשות
    (ברירת מחדל: רק הנוכחית).

    שימושי כש-CACHE_VERSION עולה (v25 → v26 וכד') ויש המון קבצים
    מגרסאות ישנות שלא ייקראו יותר אבל תופסים מקום.

    מחזיר מספר קבצים שנמחקו.
    """
    if not _CACHE_DIR.exists():
        return 0
    import re
    version_re = re.compile(r"^(v\d+)_")
    by_version: dict[str, list[Path]] = {}
    for f in _CACHE_DIR.glob("*.json"):
        m = version_re.match(f.stem)
        if not m:
            continue
        by_version.setdefault(m.group(1), []).append(f)
    if not by_version:
        return 0
    # מיון לפי מספר גרסה (v6 < v7 < v25 < v26)
    sorted_versions = sorted(
        by_version.keys(), key=lambda v: int(v[1:]), reverse=True
    )
    keep = set(sorted_versions[:keep_versions])
    removed = 0
    for ver, files in by_version.items():
        if ver in keep:
            continue
        for f in files:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        logger.info(
            "Cache cleanup: %d files from %d stale version(s) removed (kept: %s)",
            removed, len(by_version) - len(keep), ",".join(sorted(keep)),
        )
    return removed


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
