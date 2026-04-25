"""
ניתוח קשרי אבא/בן בין כל השרטוטים שנותחו.

אינטרגציה רב-שרטוטית — לוקחת את הפלט של ``extract_assembly_drawing`` עבור
כמה שרטוטים, מבקשת מהמודל לזהות את היררכיית המכלול, ומריצה ולידציות עץ
(roots מקוננים, missing children, qty mismatch, סימוני PN צולבים).

נקודת ה-entry: ``analyze_relationships(results)``.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from core.assembly.api import _call_text_json
from core.assembly_prompts import ASSEMBLY_RELATIONSHIPS_PROMPT_TEMPLATE
from core.azure_client import get_client, get_deployment
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.pn_utils import cross_reference_part_numbers

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────
# OCR text fixes (post-analysis cleanup)
# ───────────────────────────────────────────────────────────────
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


# ───────────────────────────────────────────────────────────────
# Overview-image filtering
# ───────────────────────────────────────────────────────────────
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
        ppn = a.get("parent_part_number") or ""
        pdn = a.get("parent_drawing_number") or ""
        if (
            _is_overview_label(ppn, overview_ids)
            or _is_overview_label(pdn, overview_ids)
        ):
            removed += 1
            continue
        kept.append(a)
    if removed:
        analysis["assemblies"] = kept
    return removed


# ───────────────────────────────────────────────────────────────
# Marking PN cross-reference
# ───────────────────────────────────────────────────────────────
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


# ───────────────────────────────────────────────────────────────
# Tree-shape fixers
# ───────────────────────────────────────────────────────────────
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
# Drawing summarization for prompt
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


# ───────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────
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
