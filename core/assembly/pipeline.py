"""
ה-pipeline המרכזי של חילוץ שרטוט בודד במצב Assembly.

שתי נקודות entry:
    extract_assembly_drawing(pdf_path)        — שרטוט PDF רגיל (Stage 1+2 + post-process)
    extract_assembly_overview_image(img_path) — תרשים-מכלול גרפי (Stage יחיד, ללא OCR)

שניהם משתמשים ב-cache לפי MD5 של הקובץ, מתעדים עלות, ומוסיפים אזהרות
ולידציה לתוצאה ב-`_pn_warnings`.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from core.assembly.api import _call_vision
from core.assembly.material import (
    _extract_material_direct,
    _extract_material_from_text,
    is_material_instruction_only,
)
from core.assembly.post_process import (
    _default_role_if_missing,
    _detect_self_reference_bom,
    _infer_drawing_number_from_pn,
    _split_material_formerly,
    _validate_dwg_prefix,
    _validate_spec_prefixes,
    _validate_standards_against_ocr,
)
from core.assembly_prompts import (
    ASSEMBLY_OVERVIEW_IMAGE_PROMPT,
    ASSEMBLY_STAGE_1_PROMPT,
    ASSEMBLY_STAGE_2_PROMPT,
)
from core.azure_client import get_client, get_deployment
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.drawing_cache import get_cached_result, save_cached_result
from core.exceptions import ImageError, PDFError
from core.ocr_fallback import (
    build_enhanced_prompt,
    extract_text_from_pdf,
    is_ocr_available,
)
from core.pdf_utils import image_file_to_b64, pdf_to_images
from core.pn_utils import (
    combined_pn_distance,
    extract_pn_from_filename,
    reconcile_drawing_number,
    reconcile_part_number,
    reconcile_revision,
    salvage_revision,
)
from core.text_utils import (
    clean_bom_items_in_place,
    infer_cage_from_customer,
    infer_customer_from_cage,
    normalize_customer_in_place,
    normalize_known_phrases_in_place,
)
from core.validators import (
    validate_all_paint_brands,
    validate_coating_classification,
    validate_ral_codes,
    validate_standards,
    validate_surface_prep_and_post_process,
)

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────
# 1. חילוץ שרטוט בודד במצב Assembly
# ───────────────────────────────────────────────────────────────
def extract_assembly_drawing(
    pdf_path: str | Path,
    *,
    progress_callback=None,
) -> dict:
    """חילוץ מלא של שרטוט (כולל עיבוד שבבי) — ללא התאמת מאסטרים.

    מחזיר dict עם:
      part_number, revision, drawing_number, customer, material, quantity,
      assembly_role, bom_items,
      machining_processes, coating_processes, painting_processes,
      inspection_processes, final_approval, additional_processes,
      packaging_notes, standards, notes,
      source_filename, _cost_info, _ocr_used.

    ``progress_callback``: אופציונלי. callable(step_index, step_name) שייקרא
    בכל שלב מרכזי. מאפשר ל-UI להציג progress חי במקום spinner גלובלי. דוגמה::

        def on_step(i, name):
            print(f"  [{i}/7] {name}")
        extract_assembly_drawing(path, progress_callback=on_step)
    """
    def _step(i: int, name: str) -> None:
        if progress_callback is not None:
            try:
                progress_callback(i, name)
            except Exception:
                logger.debug("progress_callback failed", exc_info=True)

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise PDFError(
            f"File not found: {pdf_path}",
            user_message=f"קובץ ה-PDF לא נמצא: {pdf_path.name}",
            suggestion="ודאי שהקובץ קיים וההעלאה הושלמה.",
            context={"path": str(pdf_path)},
        )

    # ─── Step 1: Cache lookup ───
    _step(1, "🔍 בודק cache (אולי השרטוט כבר נותח)")
    cached = get_cached_result(pdf_path, extra="assembly")
    if cached:
        logger.info(f"[Assembly] 🎯 Cache HIT: {pdf_path.name}")
        _step(7, "🎯 Cache HIT — תוצאה ממטמון, ללא קריאה ל-Azure")
        return cached

    logger.info(f"[Assembly] מעבד שרטוט: {pdf_path.name}")

    # ─── Step 2: PDF → images ───
    _step(2, "🖼️ ממיר PDF לתמונות (DPI 300)")
    images = pdf_to_images(pdf_path, dpi=300)

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(pdf_path.name)

    # ─── Step 3: OCR (optional) ───
    _step(3, "🔤 מריץ OCR מקדים (Tesseract)" if is_ocr_available() else "🔤 OCR לא זמין — דילוג")
    ocr_text = ""
    ocr_used = False
    if is_ocr_available():
        try:
            ocr_text = extract_text_from_pdf(pdf_path)
            ocr_used = bool(ocr_text.strip())
        except Exception as exc:
            logger.warning("[Assembly] OCR נכשל: %s", exc)

    # ─── Step 4: Vision Stage 1 (basic info) ───
    _step(4, "🤖 Stage 1: Vision API — חילוץ פרטים בסיסיים (P/N, חומר, BOM)")
    s1_prompt = (
        build_enhanced_prompt(ASSEMBLY_STAGE_1_PROMPT, ocr_text)
        if ocr_text else ASSEMBLY_STAGE_1_PROMPT
    )
    stage1, usage1 = _call_vision(client, deployment, s1_prompt, images)
    tracker.add_stage("assembly_stage_1_basic", calculate_cost(usage1, deployment))

    # ─── Step 5: Vision Stage 2 (processes) ───
    _step(5, "🤖 Stage 2: Vision API — חילוץ תהליכי ייצור (ציפויים, צביעה, בדיקות)")
    s2_prompt = (
        build_enhanced_prompt(ASSEMBLY_STAGE_2_PROMPT, ocr_text)
        if ocr_text else ASSEMBLY_STAGE_2_PROMPT
    )
    stage2, usage2 = _call_vision(client, deployment, s2_prompt, images)
    tracker.add_stage("assembly_stage_2_full", calculate_cost(usage2, deployment))

    _step(6, "✨ Post-processing: ולידציות, נירמול, תיקוני OCR")

    # Reconcile ל-part_number: תיקון OCR confusion (B↔8) + השלמה מ-drawing/filename
    reconcile_part_number(stage1, pdf_path.name)

    # DWG=PN fallback (Mechanico-Shaftech / Elbit — אין שדה DWG נפרד)
    # + Rev salvage ("RC"→"C") + Rev fallback מטבלה/שם הקובץ
    reconcile_drawing_number(stage1)
    salvage_revision(stage1)
    reconcile_revision(stage1, pdf_path.name)

    # Customer enrichment: CAGE→Customer + normalization + reverse CAGE
    infer_customer_from_cage(stage1)
    normalize_customer_in_place(stage1)
    infer_cage_from_customer(stage1)

    # אם המודל החזיר הוראה ("USE X" / "PER X") במקום שם חומר — נקה ותן ל-OCR
    # fallback לנסות. תופס מקרים כמו "USE EXTRUSION MCM-MC-08028-01."
    raw_material = (stage1.get("material") or "").strip()
    if raw_material and is_material_instruction_only(raw_material):
        logger.info(
            "[Assembly] 🧹 material נראה כהוראה (%s) — מנקה לטובת OCR fallback",
            raw_material[:60],
        )
        stage1["material"] = ""

    # Fallback לחומר — אם המודל החזיר ריק אבל OCR הצליח לקרוא MATERIAL
    if not (stage1.get("material") or "").strip() and ocr_text:
        material_from_text = _extract_material_from_text(ocr_text)
        if material_from_text:
            stage1["material"] = material_from_text
            logger.info(
                f"[Assembly] 🧪 חומר הושלם מ-OCR (label-based): {material_from_text[:60]}"
            )
        else:
            # Fallback שני (חזק יותר): חיפוש ישיר של ביטויי חומר בכל הטקסט
            # משמש כשאין שדה 'MATERIAL' מסומן בבירור ב-title block
            direct_material = _extract_material_direct(ocr_text)
            if direct_material:
                stage1["material"] = direct_material
                logger.info(
                    f"[Assembly] 🧪 חומר הושלם מ-OCR (direct regex): {direct_material[:60]}"
                )

    # ניקוי BOM: OCR לפעמים קורא טקסט בלולאה וחוזר על "NOM. SIZE 0.250-0.218"
    # עשרות פעמים. ה-post-processing כאן משאיר את הביטוי פעם אחת.
    bom_fixed = clean_bom_items_in_place(stage1.get("bom_items") or [])
    if bom_fixed:
        logger.info(
            "[Assembly] 🧹 ניקוי BOM: %d תיאורים נוקו מזיהום OCR", bom_fixed
        )

    # נרמול ביטויים ידועים (Z0 SQUEGLIA, SAE-AMS-C-26074) — רקורסיבי על כל
    # המחרוזות ב-stage1/stage2, כולל פרטי שלבים, תקנים, והערות.
    phrase_corrections = normalize_known_phrases_in_place(stage1)
    phrase_corrections += normalize_known_phrases_in_place(stage2)
    if phrase_corrections:
        logger.info(
            "[Assembly] 🔧 נרמול ביטויים: %s", ", ".join(phrase_corrections)
        )

    # ולידציית חומר: תקני QQ- הם לרוב ישנים והוחלפו ב-AMS
    material = (stage1.get("material") or "").strip()
    material_warnings: list[str] = []
    if material and re.search(r"\bQQ-[A-Z]", material, re.IGNORECASE):
        msg = (
            f"[INFO][POSSIBLE_OBSOLETE_SPEC] חומר מכיל prefix 'QQ-' — "
            f"בדקי אם התקן נכון ("
            f"לרוב הוחלף ב-AMS/ASTM): {material}"
        )
        material_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # Self-reference BOM: אם ה-Parts List מצביע רק לעצמו — זה PART, לא ASSEMBLY
    validation_warnings: list[str] = []
    if _detect_self_reference_bom(stage1):
        msg = (
            f"[INFO][SELF_REF_BOM] BOM הכיל רק self-reference של "
            f"{stage1.get('part_number')} — סווג כ-PART ולא ASSEMBLY"
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # Role default: אם המודל החזיר assembly_role ריק — הסק לפי BOM
    if _default_role_if_missing(stage1):
        msg = (
            f"[INFO][ROLE_AUTODETECTED] assembly_role היה ריק — סווג אוטומטית "
            f"כ-'{stage1.get('assembly_role')}' לפי תוכן BOM"
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # DWG inference: אם אין drawing_number נפרד — השתמש ב-P/N (לקוחות קטנים)
    if _infer_drawing_number_from_pn(stage1):
        msg = (
            f"[INFO][DWG_INFERRED_FROM_PN] drawing_number היה ריק — הושלם "
            f"מ-P/N ('{stage1.get('drawing_number')}')"
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # Material formerly: אם החומר מכיל '(FORMERLY ...)' — הפרד ל-material_formerly
    if _split_material_formerly(stage1):
        msg = (
            f"[INFO][MATERIAL_FORMERLY_SPLIT] תקני חומר מבוטלים הועברו לשדה "
            f"material_formerly: {stage1.get('material_formerly', '')}"
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # DWG prefix: לבקוחות ידועים (BIRD=BAS, RAFAEL=BP/MMA/...) ה-DWG מתחיל בקידומת
    dwg_warning = _validate_dwg_prefix(stage1)
    if dwg_warning:
        validation_warnings.append(dwg_warning)
        logger.info("[Assembly] ℹ️ %s", dwg_warning)

    # Hallucination check: תקנים שלא מופיעים בטקסט ה-OCR — כנראה הזיה
    standards = stage2.get("standards") or []
    if standards and ocr_text:
        retained, flagged = _validate_standards_against_ocr(standards, ocr_text)
        if flagged:
            stage2["standards"] = retained
            for std in flagged:
                msg = (
                    f"[WARN][POSSIBLE_HALLUCINATION] תקן '{std}' לא נמצא "
                    f"בטקסט ה-OCR של השרטוט — ייתכן שהמודל ממציא"
                )
                validation_warnings.append(msg)
                logger.warning("[Assembly] ⚠️ %s", msg)

    # Spec prefix validation: מזהה prefix באותיות קטנות (sm111 → PS-111) ו-prefix
    # לא מוכר. רק warnings — לא משנה את התוכן.
    _, spec_warnings = _validate_spec_prefixes(stage2.get("standards") or [])
    for w in spec_warnings:
        validation_warnings.append(w)
        logger.info("[Assembly] ℹ️ %s", w)

    # PACKING missing: בשרטוטי PRC זה סעיף חובה (70.x / 80.x / 100.x).
    # אם המודל לא חילץ אותו, יתכן שהוא פספס — סמן לבדיקה ידנית.
    pkg = stage2.get("packaging_notes") or {}
    pkg_en = (pkg.get("en") or "").strip() if isinstance(pkg, dict) else ""
    pkg_he = (pkg.get("he") or "").strip() if isinstance(pkg, dict) else ""
    pkg_has_content = bool(pkg_en or pkg_he)
    pkg_explicit_none = (
        "NO_PACKING_REQUIREMENT" in pkg_en.upper()
        or "NO_PACKING_REQUIREMENT" in pkg_he.upper()
    )
    role = (stage1.get("assembly_role") or "").strip().upper()
    if role == "PART" and pkg_explicit_none:
        msg = (
            "[INFO][NO_PACKING_REQUIREMENT_IN_DRAWING] השרטוט אינו כולל "
            "דרישת אריזה — המודל סימן זאת במפורש."
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)
    elif role == "PART" and not pkg_has_content:
        # אריזה ריקה בלי סימון מפורש — כנראה המודל דילג
        msg = (
            "[INFO][MISSING_PACKING] סעיף PACKING לא חולץ לשרטוט PART — "
            "יתכן שהמודל דילג עליו (נפוץ בשרטוטי PRC עם סעיף אחרון 70.x/80.x/100.x)."
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # SERVICEABILITY TAG missing: בשרטוטי PRC סעיף FINAL APPROVAL מכיל בד"כ
    # שני שלבים: VISUAL INSPECTION + SERVICEABILITY TAG. המודל לעיתים שוכח
    # את השני — סמן לבדיקה.
    if role == "PART":
        final_list = stage2.get("final_approval") or []
        final_text = " ".join(
            str(s.get("name_en", "")) + " " + str(s.get("name_he", ""))
            for s in final_list if isinstance(s, dict)
        ).upper()
        if final_list and "SERVICEABILITY" not in final_text and "תקינות" not in final_text:
            msg = (
                "[INFO][MISSING_SERVICEABILITY_TAG] סעיף FINAL APPROVAL חסר "
                "שלב 'SERVICEABILITY TAG' — בשרטוטי PRC סעיף זה מכיל בד\"כ "
                "גם VISUAL INSPECTION וגם SERVICEABILITY TAG."
            )
            validation_warnings.append(msg)
            logger.info("[Assembly] ℹ️ %s", msg)

    # GENERAL INSTRUCTIONS missing: בשרטוטי PRC זה שדה שחולץ ב-stage1, אבל
    # המודל לעיתים מתעלם ממנו. סמן אם role=PART ואין הוראות.
    gen_instr = stage1.get("general_instructions") or []
    if role == "PART" and not gen_instr:
        msg = (
            "[INFO][MISSING_GENERAL_INSTRUCTIONS] שדה general_instructions ריק "
            "— בשרטוטי PRC לרוב יש הוראות בסעיף 10 או 20.x "
            "('THIS DRAWING SHALL BE USED WITH...', 'DIMENSIONAL LIMITS APPLY...')"
        )
        validation_warnings.append(msg)
        logger.info("[Assembly] ℹ️ %s", msg)

    # ─── ולידטורים כלליים מ-core/validators.py (משותפים למצב יחיד ולמכלולים) ───
    # מוסיפים כאן כדי שמצב מכלולים יקבל את אותן בדיקות הזיה שיש למצב יחיד:
    # SUSPICIOUS_STANDARD (קידומת גוף-תקינה), MISSING_SURFACE_PREP, MISSING_POST_PROCESS,
    # INVALID_RAL, UNKNOWN_PAINT_BRAND, MISCLASSIFIED_COATING.
    # ⚠️ validate_packing_note לא נכלל — למכלולים יש בדיקת packing ייעודית
    #    מוקדם יותר שמתחשבת ב-assembly_role == PART.
    _merged = {**stage1, **stage2}
    # רוב הולידטורים מקבלים את ה-report המלא; validate_coating_classification
    # מקבלת רשימה בלבד, לכן נקראת בנפרד עם coating_processes ישיר.
    from collections.abc import Callable
    from typing import Any
    _dict_validators = [
        validate_standards,
        validate_surface_prep_and_post_process,
        validate_ral_codes,
        validate_all_paint_brands,
    ]
    # רשימה של (validator, argument). argument יכול להיות dict (report) או list
    # (coating_processes) — אין ל-mypy דרך לעקוב, לכן Any.
    _validator_calls: list[tuple[Callable[[Any], list[dict]], Any]] = [
        (v, _merged) for v in _dict_validators
    ]
    _validator_calls.append(
        (validate_coating_classification, stage2.get("coating_processes", []))
    )
    for _validator, _arg in _validator_calls:
        try:
            for _w in _validator(_arg) or []:
                _sev = _w.get("severity", "INFO")
                _type = _w.get("type", "VALIDATION")
                _msg_text = _w.get("message", "")
                _composed = f"[{_sev}][{_type}] {_msg_text}"
                validation_warnings.append(_composed)
                logger.info("[Assembly] %s %s", "⚠️" if _sev == "HIGH" else "ℹ️", _composed)
        except Exception as exc:  # pragma: no cover — ולידטור אחד לא מפיל את האחרים
            logger.warning("Validator %s failed: %s", _validator.__name__, exc)

    # Warning: P/N שחולץ שונה מה-P/N שבשם הקובץ (לא OCR typo — מקרה ששווה דיגלי)
    pn_warnings: list[str] = []
    fname_pn = extract_pn_from_filename(pdf_path.name)
    final_pn = (stage1.get("part_number") or "").strip()
    if (
        fname_pn
        and final_pn
        and fname_pn.upper() != final_pn.upper()
        and combined_pn_distance(final_pn, fname_pn) > 2
    ):
        msg = (
            f"[WARN][FILENAME_PN_MISMATCH] filename contains '{fname_pn}' "
            f"but extracted P/N is '{final_pn}'"
        )
        pn_warnings.append(msg)
        logger.warning("[Assembly] ⚠️ %s", msg)

    result = {
        **stage1,
        **stage2,
        "source_filename": pdf_path.name,
        "_cost_info": tracker.summary(),
        "_ocr_used": ocr_used,
    }
    extra_warnings = list(pn_warnings) + material_warnings + validation_warnings
    if phrase_corrections:
        extra_warnings.append(
            f"[INFO][OCR_PHRASE_NORMALIZED] {', '.join(phrase_corrections)}"
        )
    if extra_warnings:
        result["_pn_warnings"] = extra_warnings
    tracker.save_to_log()
    logger.info(
        f"[Assembly] ✅ {pdf_path.name} | עלות: ${tracker.total_cost():.4f}"
    )

    save_cached_result(pdf_path, result, extra="assembly")
    _step(7, "✅ הניתוח הושלם · נשמר ל-cache")
    return result


# ───────────────────────────────────────────────────────────────
# 1b. חילוץ תמונת תרשים מכלול (Exploded View / Assembly Overview)
# ───────────────────────────────────────────────────────────────
def extract_assembly_overview_image(image_path: str | Path) -> dict:
    """מנתח תמונת תרשים מכלול (PNG/JPG) ומחזיר אותה כ"שרטוט" במבנה זהה
    ל-extract_assembly_drawing, עם assembly_role="Assembly Overview Image".

    התמונה משמשת כמפת-מבנה לניתוח קשרי אבא/בן — היא מכילה בועיות מספור
    (Find Numbers) שמחברות בין החלקים, גם אם ה-PN המדויק לא רשום בה.
    אין OCR (התמונה לרוב גרפית), אין Stage2 (אין title block ותהליכים).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise ImageError(
            f"Image not found: {image_path}",
            user_message=f"קובץ התמונה לא נמצא: {image_path.name}",
            suggestion="ודאי שהקובץ קיים וההעלאה הושלמה.",
            context={"path": str(image_path)},
        )

    cached = get_cached_result(image_path, extra="overview")
    if cached:
        logger.info(f"[Assembly] 🎯 Cache HIT: {image_path.name}")
        return cached

    logger.info(f"[Assembly] מעבד תרשים מכלול (תמונה): {image_path.name}")
    images = image_file_to_b64(image_path)

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(image_path.name)

    data, usage = _call_vision(client, deployment, ASSEMBLY_OVERVIEW_IMAGE_PROMPT, images)
    tracker.add_stage("assembly_overview_image", calculate_cost(usage, deployment))

    # נירמול שדות חסרים כדי להישאר תואם למבנה של שרטוט רגיל
    data.setdefault("part_number", "")
    data.setdefault("drawing_number", "")
    data.setdefault("revision", "")
    data.setdefault("customer", "")
    data.setdefault("material", "")
    data.setdefault("quantity", "")
    data.setdefault("catalog_number", "")
    data.setdefault("raw_weight", {"qty": "", "unit": ""})
    data.setdefault("alternative_material", "")
    data.setdefault("general_instructions", [])
    data.setdefault("os_level", "")
    data.setdefault("cage_code", "")
    data.setdefault("material_formerly", "")
    data.setdefault("environment_requirements", [])
    data.setdefault("title", "")
    data.setdefault("part_weight", {"qty": "", "unit": ""})
    data["assembly_role"] = "Assembly Overview Image"
    data.setdefault("bom_items", [])
    for k in ("machining_processes", "welding_processes", "heat_treatment_processes",
              "coating_processes", "painting_processes", "ndt_processes",
              "inspection_processes", "additional_processes", "standards"):
        data.setdefault(k, [])
    data.setdefault("final_approval", "")
    data.setdefault("packaging_notes", "")
    data.setdefault("notes", "")

    # אם לא הצלחנו לחלץ PN — נשתמש בשם הקובץ כמזהה
    if not (data.get("part_number") or "").strip():
        data["part_number"] = image_path.stem

    data["source_filename"] = image_path.name
    data["_cost_info"] = tracker.summary()
    data["_ocr_used"] = False
    data["_is_overview_image"] = True

    tracker.save_to_log()
    logger.info(
        f"[Assembly] ✅ תרשים מכלול {image_path.name} | "
        f"בועיות={len(data.get('bom_items') or [])} | "
        f"עלות: ${tracker.total_cost():.4f}"
    )

    save_cached_result(image_path, data, extra="overview")
    return data
