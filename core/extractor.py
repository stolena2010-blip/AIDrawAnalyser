"""
חילוץ נתונים משרטוט PDF — מודול ראשי של AIDrawAnalyser.
עם Cost Tracking + OCR Fallback + Drawing Cache.
"""
import logging
import re
from pathlib import Path

from core.azure_client import get_client, get_deployment
from core.pdf_utils import pdf_to_images
from core.prompts import STAGE_1_PROMPT, STAGE_2_PROMPT, STAGE_3_PROMPT_TEMPLATE
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.master_matcher import match_all_coatings
from core.validators import run_all_validators
from core.two_pass import compare_and_merge, should_run_two_pass
from core.ocr_fallback import (
    is_ocr_available,
    extract_text_from_pdf,
    should_use_fallback,
    build_enhanced_prompt,
)
from core.ai_helpers import call_vision as _call_vision
from core.ai_helpers import call_text as _call_text
from core.ai_helpers import safe_call as _safe_call
from core.drawing_cache import get_cached_result, save_cached_result
from core.pn_utils import (
    reconcile_part_number as _reconcile_part_number,
    reconcile_drawing_number as _reconcile_drawing_number,
    reconcile_revision as _reconcile_revision,
)
from core.exceptions import (
    PDFError,
    StageFailedError,
    MasterMatchingError,
)

logger = logging.getLogger(__name__)


_MATERIAL_RE = re.compile(
    r"MATERIAL[:\s]+([A-Z0-9][A-Z0-9 \-./]*?)(?=[.\n]|$)",
    re.IGNORECASE,
)


def _extract_material_from_notes(notes: str) -> str:
    """Fallback — מוצא 'MATERIAL ...' בתוך טקסט ה-NOTES."""
    if not notes:
        return ""
    m = _MATERIAL_RE.search(notes)
    if not m:
        return ""
    return m.group(1).strip(" .,-")


# מילות מפתח לזיהוי שציפוי צריך להיות מזוהה אבל Stage 2 פספס
_COATING_KEYWORDS_RE = re.compile(
    r"\b(CONVERSION COATING|ALODINE|IRIDITE|CHEM FILM|CHROMATE|"
    r"ANODIZE|ANODIZING|ANODIC|"
    r"PASSIVAT|ELECTROLESS|NICKEL PLAT|ZINC PLAT|CADMIUM|CHROME PLAT|"
    r"TIN PLAT|SILVER PLAT|GOLD PLAT|COPPER PLAT|"
    r"BLACK OXIDE|PHOSPHAT|"
    r"MIL-?C-?5541|MIL-?DTL-?5541|MIL-?A-?8625|MIL-?C-?26074|"
    r"ASTM B633|ASTM B733|QQ-?N-?290|QQ-?P-?416|QQ-?Z-?325)\b",
    re.IGNORECASE,
)


def _notes_hint_coating(stage1: dict, stage2: dict) -> bool:
    """האם ב-NOTES של stage1/stage2 מופיעות מילות מפתח של ציפוי?"""
    text = " ".join([
        str(stage1.get("notes") or ""),
        str(stage2.get("notes") or ""),
    ])
    return bool(_COATING_KEYWORDS_RE.search(text))


def _proc_to_str(p) -> str:
    """ממיר תהליך (str או dict) למחרוזת אחת לתצוגה / סיכום."""
    if isinstance(p, dict):
        type_he = (p.get("type_he") or "").strip()
        type_en = (p.get("type") or "").strip()
        head = type_he or type_en or (p.get("name") or "").strip()
        thickness = (p.get("thickness") or "").strip()
        std = (p.get("standard") or "").strip()
        rohs = " (RoHS)" if p.get("rohs") is True else ""
        parts = [x for x in [head, thickness, std] if x]
        return " — ".join(parts) + rohs
    return str(p or "").strip()


def extract_drawing(pdf_path: str | Path, use_ocr_fallback: bool = True) -> dict:
    """
    חילוץ מלא של שרטוט PDF עם cost tracking ו-OCR fallback.

    Args:
        pdf_path: נתיב לקובץ PDF
        use_ocr_fallback: האם להפעיל OCR fallback אם Stage 1 חלש

    Returns:
        dict עם כל השדות + _cost_info עם פירוט עלויות
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise PDFError(
            f"File not found: {pdf_path}",
            user_message=f"קובץ ה-PDF לא נמצא: {pdf_path.name}",
            suggestion="ודאי שהקובץ קיים וההעלאה הושלמה.",
            context={"path": str(pdf_path)},
        )

    # ─── בדיקת Cache ───
    cached = get_cached_result(pdf_path, extra=f"ocr={use_ocr_fallback}")
    if cached:
        logger.info(f"🎯 Cache HIT: {pdf_path.name} — מדלג על עיבוד AI")
        return cached

    logger.info(f"מעבד שרטוט: {pdf_path.name}")

    images = pdf_to_images(pdf_path, dpi=300)
    logger.info(f"PDF הומר ל-{len(images)} עמודים")

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(pdf_path.name)

    # ─── OCR מוקדם (פעם אחת) — עוזר עם NOTES בעברית RTL וקריאת ספרות ───
    # הערה: OCR רץ תמיד (אם זמין) כי הוא עוזר לקריאת חומר, תקנים וכו'.
    # גם אם Stage 1 מחזיר ערך — ייתכן שהוא שגוי ו-OCR היה מונע את זה.
    ocr_text = ""
    ocr_used = False
    if is_ocr_available():
        try:
            ocr_text = extract_text_from_pdf(pdf_path)
            ocr_used = bool(ocr_text.strip())
        except Exception as exc:
            logger.warning("OCR נכשל: %s", exc)

    # ─── Stage 1 — מידע בסיסי (עם OCR אם זמין) ───
    logger.info("Stage 1: חילוץ מידע בסיסי...")
    stage1_prompt = (
        build_enhanced_prompt(STAGE_1_PROMPT, ocr_text) if ocr_text else STAGE_1_PROMPT
    )
    stage1, usage1 = _safe_call(
        _call_vision, client, deployment, stage1_prompt, images,
        stage="stage_1_basic_info",
    )
    tracker.add_stage("stage_1_basic_info", calculate_cost(usage1, deployment))

    # Retry נוסף רק אם Stage 1 עדיין חלש (2+ שדות קריטיים ריקים)
    if use_ocr_fallback and should_use_fallback(stage1) and ocr_text:
        logger.info("⚠️ Stage 1 חלש גם עם OCR — מנסה שוב...")
        try:
            stage1_retry, usage_retry = _safe_call(
                _call_vision, client, deployment, stage1_prompt, images
            )
            tracker.add_stage(
                "stage_1_ocr_retry", calculate_cost(usage_retry, deployment)
            )
            for key, value in stage1_retry.items():
                if value and not stage1.get(key):
                    stage1[key] = value
        except Exception as exc:
            logger.warning("Stage 1 retry נכשל: %s", exc)

    # ─── Stage 2 — תהליכים ───
    logger.info("Stage 2: חילוץ תהליכים...")
    stage2_prompt = (
        build_enhanced_prompt(STAGE_2_PROMPT, ocr_text) if ocr_text else STAGE_2_PROMPT
    )
    stage2, usage2 = _safe_call(
        _call_vision, client, deployment, stage2_prompt, images,
        stage="stage_2_processes",
    )
    tracker.add_stage("stage_2_processes", calculate_cost(usage2, deployment))

    # ─── Retry חכם לציפוי: אם ציפוי ריק אבל הטקסט מזכיר ציפוי — נסה שוב ───
    coatings_empty = not (stage2.get("coating_processes") or stage2.get("painting_processes"))
    if coatings_empty:
        hint_text = " ".join([
            str(stage1.get("notes") or ""),
            str(stage2.get("notes") or ""),
            ocr_text,
        ])
        if _COATING_KEYWORDS_RE.search(hint_text):
            logger.warning(
                "Stage 2 החזיר ציפוי ריק אך הטקסט מזכיר ציפוי — מבצע retry..."
            )
            retry_prompt = (
                stage2_prompt
                + "\n\n⚠️ שים לב! בשרטוט מופיעות מילות מפתח של ציפוי/תקן "
                "(למשל CONVERSION COATING, MIL-DTL-5541, ANODIZE, "
                "ELECTROLESS NICKEL, ASTM B633 וכו'). חובה לחלץ את כל "
                "הציפויים המוזכרים בשרטוט למערך coating_processes או "
                "painting_processes, עם פרטי התקן המלאים (TYPE/CLASS/GRADE)."
            )
            try:
                stage2_retry, usage_retry = _safe_call(
                    _call_vision, client, deployment, retry_prompt, images
                )
                tracker.add_stage(
                    "stage_2_retry", calculate_cost(usage_retry, deployment)
                )
                for key, value in (stage2_retry or {}).items():
                    if value and not stage2.get(key):
                        stage2[key] = value
                if stage2.get("coating_processes") or stage2.get("painting_processes"):
                    logger.info("✅ Retry הצליח: נמצאו תהליכים")
                else:
                    logger.warning("⚠️ Retry לא מצא תהליכים גם עם OCR")
            except Exception as exc:
                logger.warning("Stage 2 retry נכשל: %s", exc)

    # ─── Two-Pass: השוואת Stage 2 פעמיים לשדות קריטיים (RAL / מותגים) ───
    two_pass_warnings: list[dict] = []
    if should_run_two_pass(stage2):
        logger.info("Stage 2 Two-Pass: מריץ הרצה שנייה לאימות RAL ומותגים...")
        try:
            stage2_pass2, usage_pass2 = _safe_call(
                _call_vision, client, deployment, stage2_prompt, images
            )
            tracker.add_stage("stage_2_two_pass", calculate_cost(usage_pass2, deployment))
            stage2, two_pass_warnings = compare_and_merge(stage2, stage2_pass2)
            if two_pass_warnings:
                logger.warning(
                    "⚠️ Two-Pass: נמצאו %d אי-התאמות", len(two_pass_warnings)
                )
        except Exception as exc:
            logger.warning("Two-Pass נכשל: %s", exc)

    # ─── Post-processing: חילוץ material מתוך NOTES אם חסר ───
    if not (stage1.get("material") or "").strip():
        material_from_notes = _extract_material_from_notes(stage2.get("notes", ""))
        if material_from_notes:
            stage1["material"] = material_from_notes
            logger.info(f"📝 חומר חולץ מ-NOTES: {material_from_notes}")

    # ─── Post-processing: השלמה / תיקון part_number ───
    _reconcile_part_number(stage1, pdf_path.name)

    # ─── Post-processing: DWG=PN fallback + Rev fallback (נפוץ בלקוחות קטנים) ───
    _reconcile_drawing_number(stage1)
    _reconcile_revision(stage1, pdf_path.name)

    # ─── Stage 3 — סיכום עברי ───
    logger.info("Stage 3: יצירת סיכום עברי...")
    coatings_str = ", ".join(_proc_to_str(c) for c in stage2.get("coating_processes", []) if _proc_to_str(c))
    paintings_str = ", ".join(_proc_to_str(p) for p in stage2.get("painting_processes", []) if _proc_to_str(p))
    stage3_prompt = STAGE_3_PROMPT_TEMPLATE.format(
        material=stage1.get("material", ""),
        coatings=coatings_str,
        paintings=paintings_str,
    )
    # Stage 3 הוא cosmetic — אם נכשל, נמשיך בלי סיכום עברי
    try:
        hebrew_summary, usage3 = _safe_call(
            _call_text, client, deployment, stage3_prompt,
            stage="stage_3_hebrew_summary",
        )
        tracker.add_stage("stage_3_hebrew_summary", calculate_cost(usage3, deployment))
    except StageFailedError as exc:
        logger.warning("Stage 3 נכשל — מדלג על סיכום עברי: %s", exc)
        hebrew_summary = ""

    # ─── ולידציה — RAL, מותגים, סיווג ציפויים, אריזה ───
    validation_warnings = run_all_validators({**stage1, **stage2})
    all_warnings = two_pass_warnings + validation_warnings
    if all_warnings:
        logger.warning(
            "⚠️ ולידציה: %d אזהרות נמצאו (%d קריטיות)",
            len(all_warnings),
            sum(1 for w in all_warnings if w.get("severity") == "CRITICAL"),
        )

    # ─── איחוד תוצאות ───
    result = {
        **stage1,
        **stage2,
        "process_summary_hebrew": hebrew_summary,
        "source_filename": pdf_path.name,
        "_cost_info": tracker.summary(),
        "_ocr_used": ocr_used,
        "_validation_warnings": all_warnings,
    }

    # ─── התאמת מאסטרים ───
    try:
        result["master_matches"] = match_all_coatings(
            stage2.get("coating_processes", []),
            stage2.get("painting_processes", []),
            top_n=3,
        )
    except Exception as exc:  # pragma: no cover
        # Master matching הוא best-effort — נכשל לא עוצר את החילוץ
        mm_err = MasterMatchingError(
            f"Master matching failed: {exc}",
            context={"original_error": str(exc)},
        )
        logger.warning("%s (%s)", mm_err.user_message, exc)
        result["master_matches"] = []
        result.setdefault("_validation_warnings", []).append({
            "severity": "warning",
            "message": mm_err.user_message,
            "suggestion": mm_err.suggestion,
        })

    tracker.save_to_log()

    logger.info(
        f"✅ חילוץ הושלם | עלות: ${tracker.total_cost():.4f} "
        f"(~₪{tracker.total_cost() * 3.7:.3f})"
    )

    # ─── שמירה ל-cache ל-runs עתידיים ───
    save_cached_result(pdf_path, result, extra=f"ocr={use_ocr_fallback}")

    return result
