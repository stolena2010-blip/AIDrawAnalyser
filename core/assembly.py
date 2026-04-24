"""
Assembly Mode — חילוץ מלא של מספר שרטוטים וניתוח קשרים בין מכלולים.

מודול זה נפרד לחלוטין מ-core/extractor.py כדי לא להשפיע על המצב הקיים
של ניתוח שרטוט בודד. הוא משתמש ב-pipeline משלו עם prompts ייעודיים
מתוך core/assembly_prompts.py.

שלבים:
  1. extract_assembly_drawing(pdf_path) — חילוץ מלא של שרטוט בודד (ללא מאסטרים).
  2. analyze_relationships(results) — ניתוח קשרי אבא/בן בין כל השרטוטים שנותחו.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.azure_client import get_client, get_deployment, is_reasoning_model
from core.pdf_utils import pdf_to_images, image_file_to_b64
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.ocr_fallback import is_ocr_available, extract_text_from_pdf, build_enhanced_prompt
from core.assembly_prompts import (
    ASSEMBLY_STAGE_1_PROMPT,
    ASSEMBLY_STAGE_2_PROMPT,
    ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE,
    ASSEMBLY_OVERVIEW_IMAGE_PROMPT,
)
from core.exceptions import PDFError, ImageError
from core.drawing_cache import get_cached_result, save_cached_result
from core.pn_utils import (
    reconcile_part_number, cross_reference_part_numbers,
    extract_pn_from_filename, combined_pn_distance,
    reconcile_drawing_number, reconcile_revision,
)
from core.text_utils import (
    clean_bom_items_in_place, normalize_known_phrases_in_place,
)
from core.validators import (
    validate_standards,
    validate_surface_prep_and_post_process,
    validate_ral_codes,
    validate_all_paint_brands,
    validate_coating_classification,
)

logger = logging.getLogger(__name__)


_OCR_FIXES = {
    r"\b1SO(\d)": r"ISO\1",
    r"\bMIR-": "M1R-",
    r"\bBBO\b": "BB0",
    r"\b1SO11833\b": "ISO11833",
}


def _fix_ocr_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern, repl in _OCR_FIXES.items():
        out = re.sub(pattern, repl, out)
    return out


def _fix_ocr_in_relationships(analysis: dict) -> None:
    """מתקן שגיאות OCR ידועות בשדות רלוונטיים ל-P/N/DWG/טקסט."""
    for a in analysis.get("assemblies", []) or []:
        if not isinstance(a, dict):
            continue
        a["parent_part_number"] = _fix_ocr_text(a.get("parent_part_number", ""))
        a["parent_drawing_number"] = _fix_ocr_text(a.get("parent_drawing_number", ""))
        for k in a.get("children", []) or []:
            if not isinstance(k, dict):
                continue
            for fld in ("part_number", "drawing_number", "description"):
                if fld in k:
                    k[fld] = _fix_ocr_text(k.get(fld, ""))


def _collect_overview_ids(results: list[dict]) -> set[str]:
    """מזהים אפשריים של שרטוט Overview כדי לסנן אותו מהעץ."""
    ids: set[str] = set()
    for d in results or []:
        if not isinstance(d, dict):
            continue
        role = (d.get("assembly_role") or "").strip().lower()
        if role != "assembly overview image":
            continue
        for raw in (d.get("part_number"), d.get("drawing_number"), d.get("source_filename")):
            val = (raw or "").strip().lower()
            if val:
                ids.add(val)
                ids.add(Path(val).stem)
    return ids


def _is_overview_label(value: str, overview_ids: set[str]) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return False
    if v in overview_ids or Path(v).stem in overview_ids:
        return True
    return "asm_temp_image" in v or "overview image" in v or v.startswith("image")


def _filter_overview_assemblies(analysis: dict, results: list[dict]) -> int:
    """מסיר assemblies שמייצגים תמונת overview ומחזיר כמה הוסרו."""
    asms = analysis.get("assemblies") or []
    if not asms:
        return 0
    overview_ids = _collect_overview_ids(results)
    kept = []
    removed = 0
    for a in asms:
        if not isinstance(a, dict):
            continue
        parent_pn = a.get("parent_part_number") or ""
        parent_dwg = a.get("parent_drawing_number") or ""
        if _is_overview_label(parent_pn, overview_ids) or _is_overview_label(parent_dwg, overview_ids):
            removed += 1
            continue
        kept.append(a)
    analysis["assemblies"] = kept
    return removed


_MARKING_PN_PATTERNS = [
    re.compile(r"MARK\s+(?:PART\s+NUMBER|P/N|PN|PART\s*NO\.?)\s*[:\-]?\s*([A-Z0-9]+[A-Z0-9\-/\.]{3,})", re.IGNORECASE),
    re.compile(r"MARKING\s+(?:PART\s+NUMBER|P/N|PN)\s*[:\-]?\s*([A-Z0-9]+[A-Z0-9\-/\.]{3,})", re.IGNORECASE),
]


def _scan_marking_pn_mismatch(results: list[dict], analysis: dict) -> list[str]:
    """
    סורק בכל שרטוט אחרי שלבי סימון שמכילים 'MARK PART NUMBER X'.
    אם ה-P/N X לא תואם ל-P/N של השרטוט עצמו ולא ל-P/N של ההורה ברמת המכלול —
    מוציא אזהרה ב-INFO (כי ייתכן שזה מכוון).
    """
    if not results:
        return []

    # מיפוי שרטוט-לשרטוט-הורה על סמך הניתוח
    parent_by_child: dict[str, str] = {}
    for a in (analysis.get("assemblies") or []):
        if not isinstance(a, dict):
            continue
        ppn = (a.get("parent_part_number") or "").strip().upper()
        for c in a.get("children") or []:
            if isinstance(c, dict):
                cpn = (c.get("part_number") or "").strip().upper()
                if cpn and ppn:
                    parent_by_child[cpn] = ppn

    warnings: list[str] = []
    for d in results or []:
        if not isinstance(d, dict):
            continue
        own_pn = (d.get("part_number") or "").strip().upper()
        if not own_pn:
            continue
        parent_pn = parent_by_child.get(own_pn, "")

        # חיפוש phrase של "MARK PART NUMBER X" בתוך כל שלב מסוג סימון/הערות
        texts_to_scan: list[tuple[str, str]] = []
        for fld in ("machining_processes", "additional_processes",
                    "inspection_processes", "final_approval"):
            for step in d.get(fld) or []:
                if not isinstance(step, dict):
                    continue
                step_no = str(step.get("step_no") or "").strip()
                combined = " ".join(
                    str(step.get(k) or "")
                    for k in ("name_en", "name_he", "details")
                )
                if combined.strip():
                    texts_to_scan.append((step_no, combined))
        # גם בהערות הכלליות
        notes = str(d.get("notes") or "").strip()
        if notes:
            texts_to_scan.append(("notes", notes))

        for step_no, text in texts_to_scan:
            for pat in _MARKING_PN_PATTERNS:
                for match in pat.finditer(text):
                    marked_pn = match.group(1).strip().upper().rstrip(".,;:")
                    if len(marked_pn) < 5:
                        continue
                    if marked_pn == own_pn:
                        continue
                    if parent_pn and marked_pn == parent_pn:
                        continue
                    msg = (
                        f"[INFO][MARKING_PN_CROSS_REF] {d.get('part_number', '?')} "
                        f"שלב {step_no} מזכיר סימון P/N '{match.group(1)}' "
                        f"— שונה מ-P/N של השרטוט"
                        + (f" ומההורה '{parent_pn}'" if parent_pn else "")
                        + " — ודאי שזה מכוון."
                    )
                    warnings.append(msg)
                    logger.info("[Assembly] ℹ️ %s", msg)
    return warnings


def _demote_nested_roots(analysis: dict) -> int:
    """
    אם המודל החזיר מספר 'roots' (assemblies) — בודק אם אחד מהם מופיע כילד
    בתוך 'children' של אחר. במקרה כזה, מוריד את המקונן מהרמה העליונה
    (הוא אינו באמת root אלא sub-assembly).
    מחזיר את מספר ה-roots שהורדו מהרמה.
    """
    asms = [a for a in (analysis.get("assemblies") or []) if isinstance(a, dict)]
    if len(asms) <= 1:
        return 0

    # אוסף את כל ה-PNs שמופיעים כילדים בכל ה-roots.
    children_pns: set[str] = set()
    for a in asms:
        for c in a.get("children") or []:
            if isinstance(c, dict):
                cpn = (c.get("part_number") or "").strip().upper()
                if cpn:
                    children_pns.add(cpn)

    kept: list[dict] = []
    demoted = 0
    for a in asms:
        parent_pn = (a.get("parent_part_number") or "").strip().upper()
        if parent_pn and parent_pn in children_pns:
            demoted += 1
            logger.info(
                "🔧 הורדת root מקונן: %s מופיע כ-child של assembly אחר",
                parent_pn,
            )
            continue
        kept.append(a)

    if demoted:
        analysis["assemblies"] = kept
    return demoted


def _validate_product_tree(analysis: dict, results: list[dict]) -> list[str]:
    """ולידציית שלמות בסיסית לעץ מוצר מול BOM של שרטוט ההרכבה."""
    warnings: list[str] = []
    asms = [a for a in (analysis.get("assemblies") or []) if isinstance(a, dict)]

    if len(asms) != 1:
        roots = [a.get("parent_part_number", "?") for a in asms]
        warnings.append(
            f"[CRITICAL][TREE_STRUCTURE] expected 1 root assembly, got {len(asms)}: {roots}"
        )
        return warnings

    root = asms[0]
    root_pn = (root.get("parent_part_number") or "").strip().upper()
    children = [c for c in (root.get("children") or []) if isinstance(c, dict)]
    tree_pns = {
        (c.get("part_number") or "").strip().upper()
        for c in children if (c.get("part_number") or "").strip()
    }

    asm_doc = None
    for d in results or []:
        if not isinstance(d, dict):
            continue
        if (d.get("assembly_role") or "").strip() != "ASSEMBLY":
            continue
        pn = (d.get("part_number") or "").strip().upper()
        if pn == root_pn or (not asm_doc and d.get("bom_items")):
            asm_doc = d
            if pn == root_pn:
                break

    if not asm_doc:
        warnings.append("[HIGH][TREE_BOM_SOURCE] no ASSEMBLY drawing with BOM found for validation")
        return warnings

    bom_items = [it for it in (asm_doc.get("bom_items") or []) if isinstance(it, dict)]
    bom_pns = {
        (it.get("part_number") or "").strip().upper()
        for it in bom_items if (it.get("part_number") or "").strip()
    }

    missing = sorted(bom_pns - tree_pns)
    if missing:
        warnings.append(
            f"[CRITICAL][MISSING_BOM_ITEMS] missing in tree: {missing}"
        )

    bom_qty = {
        (it.get("part_number") or "").strip().upper(): str(it.get("qty") or "").strip()
        for it in bom_items if (it.get("part_number") or "").strip()
    }
    for c in children:
        cpn = (c.get("part_number") or "").strip().upper()
        if not cpn or cpn not in bom_qty:
            continue
        tree_qty = str(c.get("qty") or "").strip()
        if tree_qty and bom_qty[cpn] and tree_qty != bom_qty[cpn]:
            warnings.append(
                f"[CRITICAL][QTY_MISMATCH] {cpn}: tree={tree_qty}, bom={bom_qty[cpn]}"
            )

    for c in children:
        pn = (c.get("part_number") or "").strip().upper()
        dwg = (c.get("drawing_number") or "").strip().upper()
        if pn and dwg and pn != dwg and pn.startswith("BP") and dwg.startswith("BP"):
            warnings.append(
                f"[HIGH][PN_DWG_MISMATCH] child pn={pn} differs from dwg={dwg}"
            )

    return warnings


# ───────────────────────────────────────────────────────────────
# עזרי קריאה למודל (עצמאיים — לא נשענים על הפרטיים של extractor.py)
# ───────────────────────────────────────────────────────────────
def _build_kwargs(max_tokens: int, temperature: float, json_mode: bool) -> dict:
    kwargs: dict = {}
    if is_reasoning_model():
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def _strip_json_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return raw


def _call_vision(client, deployment: str, prompt: str, images_b64: list[str]):
    content = [{"type": "text", "text": prompt}]
    for img_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high",
            },
        })
    budget = 16000 if is_reasoning_model() else 6000
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        **_build_kwargs(max_tokens=budget, temperature=0.1, json_mode=True),
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    if not raw:
        return {}, response.usage
    try:
        return json.loads(raw), response.usage
    except json.JSONDecodeError as exc:
        logger.warning("Assembly JSON parse failed: %s — head: %s", exc, raw[:200])
        return {}, response.usage


def _call_text_json(client, deployment: str, prompt: str):
    """קריאה טקסטואלית שמחזירה JSON (לשלב ניתוח הקשרים)."""
    budget = 8000 if is_reasoning_model() else 3000
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        **_build_kwargs(max_tokens=budget, temperature=0.2, json_mode=True),
    )
    raw = _strip_json_fences(response.choices[0].message.content or "")
    if not raw:
        return {}, response.usage
    try:
        return json.loads(raw), response.usage
    except json.JSONDecodeError as exc:
        logger.warning("Relationships JSON parse failed: %s — head: %s", exc, raw[:200])
        return {"summary_he": raw, "assemblies": [], "orphans": [],
                "missing_children": [], "warnings_he": []}, response.usage


# ───────────────────────────────────────────────────────────────
# Helper: חילוץ MATERIAL מ-OCR text (fallback לחילוץ ויז'ואלי שנכשל)
# ───────────────────────────────────────────────────────────────
_MATERIAL_NOISE_PHRASES = (
    "OTHER SIZE",
    "SIMILAR MATERIAL",
    "RAW MATERIAL IDENTIFICATION",
    "SAME MATERIAL",
    "MATERIAL AND THERMAL",
    "MATERIAL ACC",
    "MATERIAL IS OPTIONAL",
)


def _extract_material_from_text(text: str) -> str:
    """חיפוש שדה MATERIAL בטקסט OCR. מחזיר ערך נקי או "" אם לא נמצא ברור.

    מחפש את התבנית "MATERIAL <ערך>" או שדה ייעודי, ומסנן הערות/disclaimers.
    """
    if not text:
        return ""

    # פיצול לשורות
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # נסה לחפש בלוק MATERIAL <ערך בשורה הבאה>
    for i, line in enumerate(lines):
        upper = line.upper()
        # התעלם משורות שהן הערות/disclaimers
        if any(noise in upper for noise in _MATERIAL_NOISE_PHRASES):
            continue
        # שורה שמורכבת מהמילה MATERIAL בלבד (label של title block)
        if upper in ("MATERIAL", "MATERIAL:", "MATL", "MATL:", "MAT'L", "MAT'L:"):
            # נסה לקחת את 1-3 השורות הבאות
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                cu = candidate.upper()
                if any(noise in cu for noise in _MATERIAL_NOISE_PHRASES):
                    continue
                # פסיכת תוויות לא רלוונטיות
                if cu in ("MATERIAL", "MATL", "QTY", "DATE", "REV", "SIZE",
                          "SCALE", "SHEET", "TITLE", "DRAWING", "DWG"):
                    continue
                # חייב להכיל לפחות אות אחת ומעל 4 תווים
                if len(candidate) < 4 or not any(c.isalpha() for c in candidate):
                    continue
                # סינון: צריך להראות כמו חומר (אלומיניום/פלדה/וכו')
                if _looks_like_material(candidate):
                    return candidate[:200]
            continue

        # תבנית בשורה אחת: "MATERIAL: <ערך>" או "MATL <ערך>"
        m = re.match(r"^\s*(?:MATERIAL|MATL|MAT'L)\s*[:\-]?\s*(.+)$", line, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            cu = candidate.upper()
            if any(noise in cu for noise in _MATERIAL_NOISE_PHRASES):
                continue
            if _looks_like_material(candidate):
                return candidate[:200]

    return ""


_MATERIAL_KEYWORDS = (
    "ALUMIN", "ALLOY", "STEEL", "STAINLESS", "BRASS", "BRONZE",
    "TITANIUM", "COPPER", "PLATE", "BAR", "ROD", "TUBE", "SHEET",
    "AL ", "SS ", "CRES", "INCONEL", "MONEL", "PLASTIC", "NYLON",
    "DELRIN", "PEEK", "ABS ", "POLYCARBONATE", "POM", "PTFE",
    "6061", "7075", "2024", "5052", "303", "304", "316", "321",
    "17-4", "17-7", "15-5", "C36", "Ti-6", "PEEK",
)


def _looks_like_material(text: str) -> bool:
    """heuristic: האם המחרוזת נראית כמו חומר גלם תקין."""
    if not text:
        return False
    upper = text.upper()
    return any(kw in upper for kw in _MATERIAL_KEYWORDS)


# ───────────────────────────────────────────────────────────────
# Post-extraction validators (hallucination / self-ref BOM / DWG prefix)
# ───────────────────────────────────────────────────────────────
# לקוחות ידועים → קידומות P/N ו-DRAWING שחובה שיופיעו בתחילת המחרוזת
_CUSTOMER_PREFIXES: dict[str, tuple[str, ...]] = {
    "BIRD AEROSYSTEMS": ("BAS",),
    "BIRD": ("BAS",),
    "RAFAEL": ("BP", "BB", "BN", "BO", "BG", "RF", "PWRL", "BBLE", "HLTA",
               "FTLS", "FTL", "MMA", "M1R", "8H-", "22H-", "R0", "R1"),
}


def _normalize_for_grep(text: str) -> str:
    """הסרת רווחים/מקפים/נקודות לצורך השוואת substring גמישה."""
    return re.sub(r"[\s\-\._/]+", "", (text or "").upper())


def _validate_standards_against_ocr(
    standards: list, ocr_text: str
) -> tuple[list[str], list[str]]:
    """
    מחזיר (standards_retained, flagged_hallucinations).
    תקן מאומת אם הוא מופיע (נורמליזציה של רווחים/מקפים) בטקסט ה-OCR.
    אם OCR ריק — לא נוכל לאמת, מחזירים הכל כמות שהוא.
    """
    if not standards:
        return [], []
    ocr_norm = _normalize_for_grep(ocr_text)
    if not ocr_norm:
        return list(standards), []
    kept: list[str] = []
    flagged: list[str] = []
    for std in standards:
        std_text = str(std or "").strip()
        if not std_text:
            continue
        std_norm = _normalize_for_grep(std_text)
        if std_norm and std_norm in ocr_norm:
            kept.append(std_text)
        else:
            # גם בדיקה על prefix קצר (לפחות 6 תווים משמעותיים) למקרה של
            # Class/Type סופי שנמחק
            core = re.split(r"\s+(?:TYPE|CLASS|GRADE|METHOD)\b", std_text,
                            maxsplit=1, flags=re.IGNORECASE)[0]
            core_norm = _normalize_for_grep(core)
            if len(core_norm) >= 6 and core_norm in ocr_norm:
                kept.append(std_text)
            else:
                flagged.append(std_text)
    return kept, flagged


_FORMERLY_RE = re.compile(
    r"\(\s*FORM(?:ERLY|ALY)[:\s]+(.+?)\)", re.IGNORECASE | re.DOTALL
)


def _split_material_formerly(stage1: dict) -> bool:
    """
    אם `material` מכיל ביטוי '(FORMERLY ...)' — מעביר את התוכן ל-material_formerly
    ומנקה אותו מה-material. מחזיר True אם בוצע תיקון.

    דוגמה (מ-Elbit 8554-3672-00):
      material = "AL 5052-H32 PER SAE-AMS-4016 (FORMERLY AMS QQ-A-250/8 OR AMS QQ-A-225/7)"
      → material = "AL 5052-H32 PER SAE-AMS-4016"
      → material_formerly = "AMS QQ-A-250/8 OR AMS QQ-A-225/7"
    """
    if not isinstance(stage1, dict):
        return False
    mat = (stage1.get("material") or "").strip()
    if not mat:
        return False
    # אם כבר יש material_formerly מפורש מהמודל — אל תדרוס
    existing_formerly = (stage1.get("material_formerly") or "").strip()
    if existing_formerly:
        return False
    m = _FORMERLY_RE.search(mat)
    if not m:
        return False
    formerly_content = m.group(1).strip().rstrip(".,; ")
    primary = _FORMERLY_RE.sub("", mat).strip()
    # נקי רווחים מרובים וסימני פיסוק תלויים
    primary = re.sub(r"\s{2,}", " ", primary).strip().rstrip(".,;")
    stage1["material"] = primary
    stage1["material_formerly"] = formerly_content
    return True


def _infer_drawing_number_from_pn(stage1: dict) -> bool:
    """
    אם drawing_number ריק/פסול אבל יש part_number — הנח ש-drawing_number = P/N.
    זו מוסכמה נפוצה בלקוחות קטנים (למשל Mechanico-Shaftech, Elbit) שאין להם
    שדה DWG נפרד. מחזיר True אם בוצע תיקון.
    """
    if not isinstance(stage1, dict):
        return False
    dwg = (stage1.get("drawing_number") or "").strip()
    pn = (stage1.get("part_number") or "").strip()
    if not pn:
        return False
    if dwg and dwg not in ("-", "—", "N/A", "n/a", "NA"):
        return False
    stage1["drawing_number"] = pn
    return True


def _default_role_if_missing(stage1: dict) -> bool:
    """
    אם assembly_role ריק — הסק אוטומטית:
    - אין BOM → PART
    - BOM קיים עם פריטים ≥ 1 שונים מה-P/N העצמי → ASSEMBLY
    - הכל self-reference → PART (נידון ב-_detect_self_reference_bom)
    מחזיר True אם עדכן.
    """
    if not isinstance(stage1, dict):
        return False
    role = (stage1.get("assembly_role") or "").strip()
    if role:
        return False
    bom = stage1.get("bom_items") or []
    pn = (stage1.get("part_number") or "").strip().upper()
    other_pns = [
        (it.get("part_number") or "").strip().upper()
        for it in bom if isinstance(it, dict)
    ]
    other_pns = [p for p in other_pns if p and p != pn]
    if other_pns:
        stage1["assembly_role"] = "ASSEMBLY"
    else:
        stage1["assembly_role"] = "PART"
    return True


def _detect_self_reference_bom(stage1: dict) -> bool:
    """
    אם ה-BOM מכיל רק שורות ש-P/N שלהן זהה ל-P/N של השרטוט עצמו —
    זה Parts List סטנדרטי, לא מכלול אמיתי. מנקה את ה-bom_items ומסמן
    role=PART. מחזיר True אם בוצע תיקון.
    """
    pn = (stage1.get("part_number") or "").strip().upper()
    items = stage1.get("bom_items") or []
    if not pn or not items:
        return False
    item_pns = [
        (it.get("part_number") or "").strip().upper()
        for it in items if isinstance(it, dict)
    ]
    non_empty = [p for p in item_pns if p]
    if not non_empty:
        return False
    # כל ה-items מצביעים לעצמו?
    if all(p == pn for p in non_empty):
        stage1["bom_items"] = []
        stage1["assembly_role"] = "PART"
        return True
    return False


_SUSPECT_SPEC_LOWERCASE_RE = re.compile(r"\b(sm|ps|rafdocs|gen)[\s.-]?\d", re.ASCII)
_KNOWN_SPEC_PREFIXES = ("PS-", "PS ", "SM-", "SM ", "RAFDOCS-", "GEN.", "GEN-",
                       "MIL-", "AMS-", "AMS ", "ASTM ", "ISO ", "FED-", "NAS",
                       "AS9100", "SAE-", "EN ISO", "EN-ISO", "AWS ", "QQ-",
                       "ASME ")


def _validate_spec_prefixes(standards: list) -> tuple[list[str], list[str]]:
    """
    מחזיר (standards_kept, warnings).
    מזהה שני דפוסים חשודים:
    1. prefix באותיות קטנות (sm/ps/rafdocs/gen) → כנראה שגיאת OCR, סמן warning.
    2. prefix לא מוכר (לא ברשימת הפרפיקסים המוכרים) → warning חזק יותר.

    אנחנו לא מוחקים תקנים — רק מדווחים כדי שהמשתמש יבחן.
    """
    if not standards:
        return [], []
    warnings: list[str] = []
    kept: list[str] = []
    for std in standards:
        std_text = str(std or "").strip()
        if not std_text:
            continue
        kept.append(std_text)
        # אותיות קטנות?
        if _SUSPECT_SPEC_LOWERCASE_RE.match(std_text):
            warnings.append(
                f"[WARN][LOWERCASE_SPEC_PREFIX] תקן '{std_text}' באותיות קטנות — "
                f"בד\"כ שגיאת OCR. הצורה הנכונה באות גדולה (PS-/SM-/RAFDOCS-)."
            )
            continue
        # prefix ידוע?
        std_upper = std_text.upper()
        if not any(std_upper.startswith(p) for p in _KNOWN_SPEC_PREFIXES):
            # נבדוק גם prefixes של 2-3 אותיות שלא שמנו מפורשות
            head = re.match(r"^([A-Z]{2,6})[\s\-.]?\d", std_upper)
            if head:
                prefix = head.group(1)
                # אם prefix קצר מדי או לא נראה סטנדרטי
                if len(prefix) < 2:
                    warnings.append(
                        f"[WARN][UNKNOWN_SPEC_PREFIX] תקן '{std_text}' עם prefix "
                        f"לא מוכר — אמתי ידנית."
                    )
    return kept, warnings


def _validate_dwg_prefix(stage1: dict) -> str:
    """
    בודק שה-DRAWING NUMBER מתחיל בקידומת ידועה של הלקוח. אם לא — מנסה
    לתקן אם המחרוזת מכילה את הקידומת במקום אחר (OCR סידר אחרת).
    מחזיר הודעת אזהרה אם לא ניתן היה לתקן בביטחון.
    """
    dwg = (stage1.get("drawing_number") or "").strip()
    customer = (stage1.get("customer") or "").strip().upper()
    if not dwg:
        return ""
    prefixes = _CUSTOMER_PREFIXES.get(customer, ())
    if not prefixes:
        # אפשר להסיק לקוח גם מהקידומת של ה-P/N
        pn_upper = (stage1.get("part_number") or "").strip().upper()
        for key, vals in _CUSTOMER_PREFIXES.items():
            if any(pn_upper.startswith(p) for p in vals):
                prefixes = vals
                break
    if not prefixes:
        return ""
    dwg_upper = dwg.upper()
    if any(dwg_upper.startswith(p.upper()) for p in prefixes):
        return ""
    # ניסיון תיקון: אם הקידומת מופיעה בסוף, הסר אותה ושים בתחילה
    for p in prefixes:
        pu = p.upper()
        if dwg_upper.endswith(pu):
            corrected = p + dwg[:-len(p)]
            stage1["drawing_number"] = corrected
            return (
                f"[INFO][DWG_PREFIX_REORDERED] DWG '{dwg}' תוקן ל-'{corrected}' "
                f"(הקידומת '{p}' היתה בסוף)"
            )
        if pu in dwg_upper and not dwg_upper.startswith(pu):
            # קידומת באמצע — סמן כ-warning אבל אל תתקן אוטומטית
            return (
                f"[WARN][DWG_PREFIX_MISMATCH] DWG '{dwg}' אמור להתחיל ב-'{p}' "
                f"עבור לקוח {customer or 'לא ידוע'} אבל הקידומת נמצאת באמצע."
            )
    return (
        f"[WARN][DWG_PREFIX_MISSING] DWG '{dwg}' לא מתחיל בקידומת ידועה "
        f"({'/'.join(prefixes)}) עבור לקוח {customer or 'לא ידוע'}."
    )


# ───────────────────────────────────────────────────────────────
# 1. חילוץ שרטוט בודד במצב Assembly
# ───────────────────────────────────────────────────────────────
def extract_assembly_drawing(pdf_path: str | Path) -> dict:
    """חילוץ מלא של שרטוט (כולל עיבוד שבבי) — ללא התאמת מאסטרים.

    מחזיר dict עם:
      part_number, revision, drawing_number, customer, material, quantity,
      assembly_role, bom_items,
      machining_processes, coating_processes, painting_processes,
      inspection_processes, final_approval, additional_processes,
      packaging_notes, standards, notes,
      source_filename, _cost_info, _ocr_used.
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
    cached = get_cached_result(pdf_path, extra="assembly")
    if cached:
        logger.info(f"[Assembly] 🎯 Cache HIT: {pdf_path.name}")
        return cached

    logger.info(f"[Assembly] מעבד שרטוט: {pdf_path.name}")
    images = pdf_to_images(pdf_path, dpi=300)

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(pdf_path.name)

    # OCR מוקדם
    ocr_text = ""
    ocr_used = False
    if is_ocr_available():
        try:
            ocr_text = extract_text_from_pdf(pdf_path)
            ocr_used = bool(ocr_text.strip())
        except Exception as exc:
            logger.warning("[Assembly] OCR נכשל: %s", exc)

    # Stage 1
    s1_prompt = (
        build_enhanced_prompt(ASSEMBLY_STAGE_1_PROMPT, ocr_text)
        if ocr_text else ASSEMBLY_STAGE_1_PROMPT
    )
    stage1, usage1 = _call_vision(client, deployment, s1_prompt, images)
    tracker.add_stage("assembly_stage_1_basic", calculate_cost(usage1, deployment))

    # Stage 2 — תכולה מלאה
    s2_prompt = (
        build_enhanced_prompt(ASSEMBLY_STAGE_2_PROMPT, ocr_text)
        if ocr_text else ASSEMBLY_STAGE_2_PROMPT
    )
    stage2, usage2 = _call_vision(client, deployment, s2_prompt, images)
    tracker.add_stage("assembly_stage_2_full", calculate_cost(usage2, deployment))

    # Reconcile ל-part_number: תיקון OCR confusion (B↔8) + השלמה מ-drawing/filename
    reconcile_part_number(stage1, pdf_path.name)

    # DWG=PN fallback (Mechanico-Shaftech / Elbit — אין שדה DWG נפרד)
    # + Rev fallback מטבלת REVISIONS או מהסיומת בשם הקובץ
    reconcile_drawing_number(stage1)
    reconcile_revision(stage1, pdf_path.name)

    # Fallback לחומר — אם המודל החזיר ריק אבל OCR הצליח לקרוא MATERIAL
    if not (stage1.get("material") or "").strip() and ocr_text:
        material_from_text = _extract_material_from_text(ocr_text)
        if material_from_text:
            stage1["material"] = material_from_text
            logger.info(
                f"[Assembly] 🧪 חומר הושלם מ-OCR: {material_from_text[:60]}"
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
            f"[INFO][MISSING_PACKING] סעיף PACKING לא חולץ לשרטוט PART — "
            f"יתכן שהמודל דילג עליו (נפוץ בשרטוטי PRC עם סעיף אחרון 70.x/80.x/100.x)."
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
    _dict_validators = [
        validate_standards,
        validate_surface_prep_and_post_process,
        validate_ral_codes,
        validate_all_paint_brands,
    ]
    _validator_calls = [(v, _merged) for v in _dict_validators]
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


# ───────────────────────────────────────────────────────────────
# 2. ניתוח קשרי אבא/בן בין שרטוטים שנותחו
# ───────────────────────────────────────────────────────────────
def _summarize_drawing_for_prompt(d: dict, idx: int) -> str:
    """דוחס שרטוט לטקסט קצר בשביל ה-prompt של ניתוח הקשרים."""
    pn = d.get("part_number") or "?"
    dn = d.get("drawing_number") or "?"
    rev = d.get("revision") or "?"
    cust = d.get("customer") or "?"
    mat = d.get("material") or "?"
    role = d.get("assembly_role") or "?"
    qty = d.get("quantity") or ""
    src = d.get("source_filename") or ""

    # תהליכים מרוכזים
    procs = []
    if d.get("welding_processes"):
        procs.append(f"ריתוך×{len(d['welding_processes'])}")
    if d.get("heat_treatment_processes"):
        procs.append(f"טיפול חום×{len(d['heat_treatment_processes'])}")
    for c in d.get("coating_processes", []) or []:
        if isinstance(c, dict):
            t = c.get("type_he") or c.get("type") or c.get("name") or ""
            s = c.get("standard") or ""
            procs.append(f"{t} ({s})".strip())
    for p in d.get("painting_processes", []) or []:
        if isinstance(p, dict):
            t = p.get("type_he") or p.get("type") or p.get("name") or ""
            s = p.get("standard") or ""
            procs.append(f"{t} ({s})".strip())
    if d.get("ndt_processes"):
        procs.append(f"NDT×{len(d['ndt_processes'])}")

    bom_items = d.get("bom_items") or []
    bom_text = ""
    if bom_items:
        lines = []
        for it in bom_items:
            if isinstance(it, dict):
                lines.append(
                    f"      - item {it.get('item_no','?')}: "
                    f"P/N={it.get('part_number','?')} | "
                    f"qty={it.get('qty','?')} | desc={it.get('description','')}"
                )
        bom_text = "\n   BOM:\n" + "\n".join(lines)

    return (
        f"#{idx}  file={src}\n"
        f"   part_number={pn} | drawing_number={dn} | rev={rev} | customer={cust}\n"
        f"   material={mat}\n"
        f"   role={role} | quantity={qty}\n"
        f"   processes={'; '.join(procs) if procs else '—'}"
        f"{bom_text}"
    )


def analyze_relationships(results: list[dict]) -> dict:
    """מריץ AI על כל השרטוטים יחד ומחזיר ניתוח קשרי אבא/בן.

    מחזיר dict:
      {
        "summary_he": str,
        "assemblies": [{parent_part_number, parent_drawing_number, children:[...]}],
        "orphans": [...],
        "missing_children": [...],
        "warnings_he": [...],
        "_cost_info": {...}
      }
    """
    if not results:
        return {
            "summary_he": "לא הועלו שרטוטים.",
            "assemblies": [], "orphans": [],
            "missing_children": [], "warnings_he": [],
            "_cost_info": {},
        }

    # Cross-reference P/N של שרטוטים PART מול BOM של שרטוטי ASSEMBLY.
    # מתקן אוטומטית טעויות OCR כמו BBJ10223A → BB1J0223A (סדר ספרות)
    # או BNB0760B → BN80760B (8↔B).
    pn_corrections = cross_reference_part_numbers(results)

    drawings_text = "\n\n".join(
        _summarize_drawing_for_prompt(d, i + 1) for i, d in enumerate(results)
    )
    prompt = ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE.format(
        drawings_data=drawings_text
    )

    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker("__assembly_relationships__")
    analysis, usage = _call_text_json(client, deployment, prompt)
    tracker.add_stage("assembly_relationships", calculate_cost(usage, deployment))

    # ודא מבנה תקין
    analysis.setdefault("summary_he", "")
    analysis.setdefault("assemblies", [])
    analysis.setdefault("orphans", [])
    analysis.setdefault("missing_children", [])
    analysis.setdefault("warnings_he", [])

    _fix_ocr_in_relationships(analysis)
    removed = _filter_overview_assemblies(analysis, results)
    if removed:
        analysis["warnings_he"].append(
            f"[HIGH][IMAGE_FILTERED] {removed} overview image node(s) removed from assemblies tree"
        )

    # אם המודל החזיר מספר roots אבל אחד מהם נמצא כ-child של אחר — הורד אותו מה-top level.
    demoted = _demote_nested_roots(analysis)
    if demoted:
        analysis["warnings_he"].append(
            f"[INFO][ROOT_DEMOTED] {demoted} nested root(s) moved to children level"
        )

    if pn_corrections:
        analysis["warnings_he"].extend(
            f"[INFO][PN_AUTOCORRECT] {msg}" for msg in pn_corrections
        )

    # הפץ אזהרות ברמת השרטוט הבודד (למשל FILENAME_PN_MISMATCH) לאזהרות הכלליות
    for d in results or []:
        if not isinstance(d, dict):
            continue
        for w in d.get("_pn_warnings") or []:
            analysis["warnings_he"].append(
                f"{w} (קובץ: {d.get('source_filename', '?')})"
            )

    # Cross-reference של P/N בהוראות סימון — דגל כשמסמנים P/N אחר מהחלק עצמו
    analysis["warnings_he"].extend(_scan_marking_pn_mismatch(results, analysis))

    tree_warnings = _validate_product_tree(analysis, results)
    analysis["warnings_he"].extend(tree_warnings)

    analysis["_cost_info"] = tracker.summary()
    tracker.save_to_log()
    logger.info(
        f"[Assembly] ניתוח קשרים הושלם | עלות: ${tracker.total_cost():.4f}"
    )
    return analysis
