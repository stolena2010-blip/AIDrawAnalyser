"""
UI של מצב 'מכלולים מרובים'.

מודול נפרד מ-app.py כדי שהקוד של המצב הקיים (שרטוט בודד) לא ישתנה.
מופעל מ-app.py באמצעות render_assembly_mode() כשהמשתמש בוחר במצב הזה.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.assembly import (
    extract_assembly_drawing,
    extract_assembly_overview_image,
    analyze_relationships,
)
from core.pn_utils import cross_reference_part_numbers
from storage.save_handler import save_to_json
from storage.pdf_report import (
    build_assembly_pdf,
    build_tree_pdf,
    build_tree_excel,
    build_assembly_excel,
)
from core.exceptions import format_error_for_ui, get_streamlit_level

logger = logging.getLogger(__name__)


# מספר עובדים מקבילים לחילוץ שרטוטים. ערך גבוה מדי יחרוג מ-rate limit
# של Azure OpenAI (4-8 בטוח לרוב ה-tier-ים). ניתן לכוונן עם משתנה סביבה.
ASSEMBLY_PARALLELISM = max(1, int(os.environ.get("ASSEMBLY_PARALLELISM", "4")))


def _show_error(exc: Exception, *, prefix: str = "") -> None:
    """Displays error via Streamlit with user-friendly message and severity."""
    level = get_streamlit_level(exc)
    msg = format_error_for_ui(exc, include_technical=True)
    if prefix:
        msg = f"**{prefix}**\n\n{msg}"
    getattr(st, level)(msg)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _init_state():
    if "asm_results" not in st.session_state:
        st.session_state["asm_results"] = []  # list[dict]
    if "asm_index" not in st.session_state:
        st.session_state["asm_index"] = 0
    if "asm_relationships" not in st.session_state:
        st.session_state["asm_relationships"] = None


def _process_pdf(uploaded_file, output_dir: Path) -> dict | None:
    """מנתב כל קובץ שהועלה — PDF לחילוץ רגיל, תמונה לניתוח תרשים-מכלול."""
    suffix = Path(uploaded_file.name).suffix.lower()
    temp_path = output_dir / f"_asm_temp_{uploaded_file.name}"
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    try:
        if suffix in _IMAGE_SUFFIXES:
            return extract_assembly_overview_image(temp_path)
        return extract_assembly_drawing(temp_path)
    except Exception as exc:
        logger.exception("Assembly extract failed for %s", uploaded_file.name)
        _show_error(exc, prefix=f"שגיאה ב-{uploaded_file.name}")
        return None
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _render_drawing_card(d: dict):
    """תצוגה מלאה של שרטוט בודד במצב מכלולים."""
    pn = d.get("part_number") or "—"
    dn = d.get("drawing_number") or "—"
    rev = d.get("revision") or "—"
    cust = d.get("customer") or "—"
    mat = d.get("material") or "—"
    qty = d.get("quantity") or "—"
    role = d.get("assembly_role") or "—"
    cat = (d.get("catalog_number") or "").strip()
    rw = d.get("raw_weight") or {}
    rw_qty = (rw.get("qty") or "").strip() if isinstance(rw, dict) else ""
    rw_unit = (rw.get("unit") or "").strip() if isinstance(rw, dict) else ""
    raw_weight_text = (
        f"{rw_qty} {rw_unit}".strip() if rw_qty or rw_unit else ""
    )
    alt_mat = (d.get("alternative_material") or "").strip()
    os_lvl = (d.get("os_level") or "").strip()
    cage = (d.get("cage_code") or "").strip()
    mat_formerly = (d.get("material_formerly") or "").strip()
    title = (d.get("title") or "").strip()
    pw = d.get("part_weight") or {}
    pw_qty = (pw.get("qty") or "").strip() if isinstance(pw, dict) else ""
    pw_unit = (pw.get("unit") or "").strip() if isinstance(pw, dict) else ""
    part_weight_text = f"{pw_qty} {pw_unit}".strip() if pw_qty or pw_unit else ""

    extra_line = ""
    extras = []
    if title:
        extras.append(f'<span style="color:#6c757d;">כותרת:</span> <b>{title}</b>')
    if cat:
        extras.append(f'<span style="color:#6c757d;">CAT NO.:</span> <b>{cat}</b>')
    if cage:
        extras.append(f'<span style="color:#6c757d;">CAGE:</span> <b>{cage}</b>')
    if raw_weight_text:
        extras.append(
            f'<span style="color:#6c757d;">משקל חומר גלם:</span> '
            f'<b>{raw_weight_text}</b>'
        )
    if part_weight_text:
        extras.append(
            f'<span style="color:#6c757d;">משקל פריט:</span> '
            f'<b>{part_weight_text}</b>'
        )
    if os_lvl:
        extras.append(
            f'<span style="color:#6c757d;">OS Level:</span> '
            f'<b style="color:#b02a37;">{os_lvl}</b>'
        )
    if extras:
        extra_line = (
            '<div style="margin-top:0.4em;">' + ' &nbsp;·&nbsp; '.join(extras)
            + '</div>'
        )

    alt_line = ""
    if alt_mat:
        alt_line = (
            f'<div style="margin-top:0.4em; font-style:italic; color:#495057;">'
            f'🔄 חומר חלופי מורשה: {alt_mat}</div>'
        )
    if mat_formerly:
        alt_line += (
            f'<div style="margin-top:0.3em; font-style:italic; color:#6c757d;">'
            f'📜 תקנים מבוטלים (formerly): {mat_formerly}</div>'
        )

    st.markdown(
        f'<div dir="rtl" style="unicode-bidi:plaintext; text-align:right; '
        f'background:linear-gradient(135deg,#eef5ff 0%,#e8f5e9 100%); '
        f'border:2px solid #0d6efd; border-radius:0.7em; padding:1em 1.2em; '
        f'margin-bottom:1em; font-size:0.95em; line-height:1.7;">'
        f'<div style="font-size:1.1em; font-weight:700; color:#0d6efd; '
        f'margin-bottom:0.5em; border-bottom:1px solid #cfe2ff; padding-bottom:0.3em;">'
        f'🎯 פרטי השרטוט</div>'
        f'<div><span style="color:#6c757d;">פריט:</span> <b>{pn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">שרטוט:</span> <b>{dn}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">גרסה:</span> <b>{rev}</b> &nbsp;·&nbsp; '
        f'<span style="color:#6c757d;">לקוח:</span> <b>{cust}</b></div>'
        f'<div style="margin-top:0.4em;"><span style="color:#6c757d;">חומר:</span> <b>{mat}</b> '
        f'&nbsp;·&nbsp; <span style="color:#6c757d;">תפקיד:</span> <b>{role}</b> '
        f'&nbsp;·&nbsp; <span style="color:#6c757d;">כמות:</span> <b>{qty}</b></div>'
        f'{extra_line}'
        f'{alt_line}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ─── הוראות כלליות (סעיף 10) ───
    gen_instr = d.get("general_instructions") or []
    if gen_instr and isinstance(gen_instr, list):
        with st.expander("📜 הוראות כלליות", expanded=False):
            for item in gen_instr:
                if isinstance(item, str) and item.strip():
                    st.markdown(f"- {item.strip()}")

    # ─── תנאי סביבה (CLEAN ROOM / ESD / IPA) ───
    env_req = d.get("environment_requirements") or []
    if env_req and isinstance(env_req, list):
        with st.expander("🌡️ תנאי סביבה / Clean Room", expanded=True):
            for item in env_req:
                if isinstance(item, str) and item.strip():
                    st.markdown(f"- {item.strip()}")

    # ─── BOM (אם קיים) ───
    bom = d.get("bom_items") or []
    if bom:
        st.markdown("#### 📋 טבלת חלקים (BOM)")
        rows = []
        for it in bom:
            if isinstance(it, dict):
                rows.append({
                    "Item": it.get("item_no", ""),
                    "Part Number": it.get("part_number", ""),
                    "Description": it.get("description", ""),
                    "Qty": it.get("qty", ""),
                })
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)

    # ─── Helper להצגת שלב כללי ───
    def _render_step_block(title_he: str, icon: str, items: list,
                            keys=("step_no", "name_en", "name_he", "details")):
        if not items:
            return
        st.markdown(f"#### {icon} {title_he}")
        rows = []
        for it in items:
            if not isinstance(it, dict):
                rows.append({"שלב": "", "אנגלית": str(it), "עברית": "", "פרטים": ""})
                continue
            rows.append({
                "שלב": it.get(keys[0], ""),
                "אנגלית": it.get(keys[1], ""),
                "עברית": it.get(keys[2], ""),
                "פרטים": it.get(keys[3], ""),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    # ─── תהליכים בסדר העבודה ───
    _render_step_block("עיבוד שבבי", "🔧", d.get("machining_processes") or [])
    _render_step_block("ריתוך", "🔥", d.get("welding_processes") or [])
    _render_step_block("טיפול חום", "🌡️", d.get("heat_treatment_processes") or [])

    coatings = d.get("coating_processes") or []
    if coatings:
        st.markdown("#### 🎨 ציפויים / טיפול שטח")
        rows = []
        for c in coatings:
            if isinstance(c, dict):
                rows.append({
                    "שלב": c.get("step_no", ""),
                    "סוג (HE)": c.get("type_he", ""),
                    "סוג (EN)": c.get("type", ""),
                    "תיאור": c.get("name", ""),
                    "תקן": c.get("standard", ""),
                    "עובי": c.get("thickness", ""),
                    "RoHS": "✓" if c.get("rohs") else "",
                })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    paintings = d.get("painting_processes") or []
    if paintings:
        st.markdown("#### 🖌️ צביעות")
        rows = []
        for p in paintings:
            if isinstance(p, dict):
                rows.append({
                    "שלב": p.get("step_no", ""),
                    "סוג (HE)": p.get("type_he", ""),
                    "סוג (EN)": p.get("type", ""),
                    "תיאור": p.get("name", ""),
                    "תקן": p.get("standard", ""),
                    "עובי": p.get("thickness", ""),
                    "RoHS": "✓" if p.get("rohs") else "",
                })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    _render_step_block("בדיקות NDT", "🔬", d.get("ndt_processes") or [])
    _render_step_block("בדיקות", "🔍", d.get("inspection_processes") or [])
    _render_step_block("אישור סופי", "✅", d.get("final_approval") or [])

    add = d.get("additional_processes") or []
    if add:
        st.markdown("#### 🛠️ תהליכים מלווים")
        rows = []
        for a in add:
            if isinstance(a, dict):
                rows.append({
                    "שלב": a.get("step_no", ""),
                    "אנגלית": a.get("name_en", ""),
                    "עברית": a.get("name_he", ""),
                    "פרטים": a.get("details", ""),
                })
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)

    # ─── תקנים ───
    stds = d.get("standards") or []
    if stds:
        st.markdown("#### 📜 כל התקנים שמופיעים בשרטוט")
        st.markdown(" &nbsp;·&nbsp; ".join(f"`{s}`" for s in stds))

    # ─── אריזה ───
    pkg = d.get("packaging_notes") or {}
    if isinstance(pkg, dict) and (pkg.get("he") or pkg.get("en")):
        st.markdown("#### 📦 אריזה")
        if pkg.get("he"):
            st.markdown(
                f'<div dir="rtl" style="unicode-bidi:plaintext; background:#fff3cd; '
                f'color:#664d03; padding:0.6em 0.9em; border-radius:0.4em; margin-bottom:0.4em;">'
                f'🇮🇱 {pkg["he"]}</div>',
                unsafe_allow_html=True,
            )
        if pkg.get("en"):
            st.markdown(
                f'<div dir="ltr" style="background:#fff3cd; color:#664d03; '
                f'padding:0.6em 0.9em; border-radius:0.4em;">🇬🇧 {pkg["en"]}</div>',
                unsafe_allow_html=True,
            )

    # ─── הערות ───
    notes = (d.get("notes") or "").strip()
    if notes:
        with st.expander("📝 הערות השרטוט (NOTES)", expanded=False):
            st.info(notes)

    with st.expander("📄 JSON מלא"):
        st.json({k: v for k, v in d.items() if not k.startswith("_")})


_SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def _render_validation_warnings(result: dict) -> None:
    """מציג אזהרות ולידציה אם קיימות."""
    warnings = result.get("_validation_warnings") or []
    if not warnings:
        return
    critical = [w for w in warnings if w.get("severity") == "CRITICAL"]
    label = f"⚠️ {len(warnings)} אזהרות ולידציה"
    if critical:
        label += f" — {len(critical)} 🔴 קריטיות"
    with st.expander(label, expanded=bool(critical)):
        for w in warnings:
            icon = _SEVERITY_ICON.get(w.get("severity", ""), "⚪")
            st.markdown(
                f"{icon} **{w.get('type', '')}** | מקור: `{w.get('source', '')}` | "
                f"ערך: `{w.get('value', '')[:80]}`  \n"
                f"_{w.get('message', '')}_"
            )


def _render_stage_model_feedback(cost_info: dict,
                                 title: str = "🤖 מודל בפועל לכל שלב",
                                 expanded: bool = False):
    """מציג פירוט שלבים עם מודל, טוקנים ועלות."""
    stages = (cost_info or {}).get("stages") or []
    if not stages:
        return

    rows = []
    for s in stages:
        if not isinstance(s, dict):
            continue
        rows.append({
            "שלב": s.get("stage", ""),
            "מודל בפועל": s.get("model", ""),
            "Input": s.get("input_tokens", 0),
            "Output": s.get("output_tokens", 0),
            "עלות $": s.get("total_cost_usd", 0),
        })

    if not rows:
        return

    with st.expander(title, expanded=expanded):
        st.dataframe(rows, use_container_width=True, hide_index=True)
        models = sorted({r["מודל בפועל"] for r in rows if r["מודל בפועל"]})
        if models:
            st.caption("מודלים בשימוש: " + " | ".join(models))


def _render_export_pair(*, button_label: str, spinner_text: str,
                        build_fn, out_path: Path, state_key: str,
                        mime: str, btn_key: str, dl_key: str,
                        err_label: str):
    """מציג צמד "צור קובץ → הורד" בתוך טאב יחיד.

    מחזיק את נתיב הקובץ ב-`st.session_state[state_key]`, כך שכפתור
    ההורדה נשאר זמין גם אחרי rerun ללא ייצור מחדש.
    """
    if st.button(button_label, use_container_width=True,
                 type="primary", key=btn_key):
        try:
            with st.spinner(spinner_text):
                build_fn(out_path)
            st.session_state[state_key] = str(out_path)
            st.success(f"נוצר: `{out_path.name}`")
        except Exception as exc:
            logger.exception("%s export failed", err_label)
            _show_error(exc, prefix=f"שגיאה ביצירת {err_label}")

    saved = st.session_state.get(state_key)
    if saved and Path(saved).exists():
        with open(saved, "rb") as fh:
            st.download_button(
                label=f"⬇️ הורד {Path(saved).name}",
                data=fh.read(),
                file_name=Path(saved).name,
                mime=mime,
                use_container_width=True,
                key=dl_key,
            )


def _render_relationships(rel: dict):
    """תצוגת ניתוח קשרי אבא/בן בין השרטוטים."""
    st.markdown("## 🔗 ניתוח קשרי המכלול")

    summary = (rel.get("summary_he") or "").strip()
    if summary:
        st.markdown(
            f'<div dir="rtl" style="unicode-bidi:plaintext; background:#d4edda; '
            f'color:#155724; padding:0.7em 1em; border-radius:0.5em; '
            f'margin:0.5em 0 1em 0; line-height:1.7;">📋 <b>סיכום:</b><br>{summary}</div>',
            unsafe_allow_html=True,
        )

    asms = rel.get("assemblies") or []
    if asms:
        st.markdown("### 🧩 מכלולים שזוהו")
        for a in asms:
            ppn = a.get("parent_part_number") or "—"
            pdn = a.get("parent_drawing_number") or "—"
            kids = a.get("children") or []
            with st.expander(f"📦 מכלול: P/N={ppn}  ·  DWG={pdn}  ·  {len(kids)} חלקים",
                             expanded=True):
                if kids:
                    rows = []
                    for k in kids:
                        if isinstance(k, dict):
                            rows.append({
                                "P/N": k.get("part_number", ""),
                                "Drawing": k.get("drawing_number", ""),
                                "Description": k.get("description", ""),
                                "Qty": k.get("qty", ""),
                                "הועלה?": "✓" if k.get("found_in_uploaded_files") else "✗",
                            })
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                else:
                    st.caption("אין חלקים")

    orphans = rel.get("orphans") or []
    if orphans:
        st.markdown("### 🪙 שרטוטים ללא הורה")
        rows = []
        for o in orphans:
            if isinstance(o, dict):
                rows.append({
                    "P/N": o.get("part_number", ""),
                    "Drawing": o.get("drawing_number", ""),
                    "סיבה": o.get("reason_he", ""),
                })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    missing = rel.get("missing_children") or []
    if missing:
        st.markdown("### ⚠️ חלקים שמופיעים ב-BOM אך לא הועלו כשרטוט")
        rows = []
        for m in missing:
            if isinstance(m, dict):
                rows.append({
                    "P/N": m.get("part_number", ""),
                    "Description": m.get("description", ""),
                    "Qty": m.get("qty", ""),
                    "נדרש ע\"י": m.get("needed_by_he", ""),
                })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    warnings = rel.get("warnings_he") or []
    if warnings:
        st.markdown("### 💡 הערות / אזהרות")
        for w in warnings:
            st.warning(w)


# ═══════════════════════════════════════════════════════════════
# נקודת כניסה
# ═══════════════════════════════════════════════════════════════
def render_assembly_mode(output_dir: Path):
    """מצייר את כל מסך מצב המכלולים."""
    _init_state()

    st.caption("העלה מספר שרטוטים יחד · נתח כל אחד בנפרד · "
               "קבל ניתוח קשרי אבא/בן בסוף")

    # ─── 1. העלאת קבצים ───
    st.markdown("### 1️⃣ העלה שרטוטים PDF (ואופציונלית תרשים מכלול PNG/JPG)")
    files = st.file_uploader(
        "גרור שרטוטי PDF + תמונה אחת של תרשים-מכלול (Exploded View) — או לחץ לבחירה",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="asm_uploader",
    )

    col_a, col_b = st.columns([3, 1])
    with col_a:
        do_analyze = st.button(
            f"🔍 נתח {len(files) if files else 0} שרטוטים",
            type="primary",
            disabled=not files,
            use_container_width=True,
        )
    with col_b:
        if st.button("🗑️ נקה", use_container_width=True):
            st.session_state["asm_results"] = []
            st.session_state["asm_index"] = 0
            st.session_state["asm_relationships"] = None
            st.rerun()

    # ─── 2. ניתוח (מקבילי — ASSEMBLY_PARALLELISM workers) ───
    if do_analyze and files:
        total = len(files)
        progress = st.progress(0.0, text=f"מתחיל ניתוח של {total} קבצים...")
        # שמירה על סדר ההעלאה — כל future ממופה ל-index המקורי שלו
        ordered: list[dict | None] = [None] * total
        completed = 0
        workers = min(ASSEMBLY_PARALLELISM, total)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(_process_pdf, f, output_dir): (i, f.name)
                for i, f in enumerate(files)
            }
            for future in as_completed(future_to_idx):
                idx, fname = future_to_idx[future]
                completed += 1
                progress.progress(
                    completed / total,
                    text=f"✅ {completed}/{total} (האחרון: {fname})",
                )
                try:
                    res = future.result()
                except Exception:
                    logger.exception("Assembly extract worker failed for %s", fname)
                    res = None
                if res is not None:
                    ordered[idx] = res

        results = [r for r in ordered if r is not None]
        progress.progress(1.0, text=f"✅ ניתוח הסתיים — {len(results)}/{total} הצליחו")
        # תמונת מכלול (Overview Image) תמיד ראשונה — היא מייצגת את כל
        # השרטוטים יחד, לא משנה באיזה סדר הועלתה.
        results.sort(key=lambda r: 0 if r.get("_is_overview_image") else 1)
        # Cross-reference P/N של שרטוטים PART מול BOM של שרטוטי ASSEMBLY.
        # מתקן שגיאות OCR נפוצות (BNB0760B → BN80760B, BBJ10223A → BB1J0223A,
        # BP7053A → BP70534A) לפני הצגה למשתמש, כך שה-dropdown וכרטיסי השרטוטים
        # מציגים כבר את הערכים התקינים.
        pn_corrections = cross_reference_part_numbers(results)
        st.session_state["asm_pn_corrections"] = pn_corrections
        st.session_state["asm_results"] = results
        st.session_state["asm_index"] = 0
        st.session_state["asm_relationships"] = None  # נדרש מחדש
        st.success(f"✅ נותחו {len(results)} שרטוטים")
        if pn_corrections:
            st.info(
                "🔧 **תיקון P/N אוטומטי** (על סמך BOM של שרטוטים אחרים):\n\n"
                + "\n".join(f"- {msg}" for msg in pn_corrections)
            )

    results = st.session_state["asm_results"]
    if not results:
        st.info("📥 העלה שרטוטים ולחץ 'נתח' כדי להתחיל.")
        return

    # ─── 3. ניווט בין שרטוטים ───
    st.divider()
    st.markdown("### 2️⃣ דפדוף בין שרטוטים")

    n = len(results)
    idx = max(0, min(st.session_state["asm_index"], n - 1))

    def _goto(new_idx: int):
        """מעדכן את האינדקס. אסור לגעת ב-asm_jump כאן —
        ה-selectbox כבר נוצר באותה הרצה, וסנכרון מתבצע בראש ההרצה הבאה."""
        new_idx = max(0, min(new_idx, n - 1))
        st.session_state["asm_index"] = new_idx

    def _on_jump_change():
        st.session_state["asm_index"] = st.session_state["asm_jump"]

    # ודא שערך ה-selectbox מסונכרן עם asm_index לפני יצירת ה-widget
    if st.session_state.get("asm_jump") != idx:
        st.session_state["asm_jump"] = idx

    nav_a, nav_b, nav_c, nav_d, nav_e = st.columns([1, 1, 3, 1, 1])
    with nav_a:
        if st.button("⏮️ ראשון", use_container_width=True, disabled=idx == 0):
            _goto(0)
            st.rerun()
    with nav_b:
        if st.button("◀️ הקודם", use_container_width=True, disabled=idx == 0):
            _goto(idx - 1)
            st.rerun()
    with nav_c:
        labels = [
            f"{i+1}. {(r.get('part_number') or r.get('source_filename') or '?')[:40]}"
            for i, r in enumerate(results)
        ]
        st.selectbox(
            "קפוץ לשרטוט", options=list(range(n)),
            format_func=lambda i: labels[i],
            key="asm_jump",
            on_change=_on_jump_change,
            label_visibility="collapsed",
        )
    with nav_d:
        if st.button("▶️ הבא", use_container_width=True, disabled=idx == n - 1):
            _goto(idx + 1)
            st.rerun()
    with nav_e:
        if st.button("⏭️ אחרון", use_container_width=True, disabled=idx == n - 1):
            _goto(n - 1)
            st.rerun()

    st.caption(f"📄 מציג שרטוט **{idx + 1}** מתוך **{n}** · "
               f"`{results[idx].get('source_filename', '')}`")

    # ─── 4. תצוגה מלאה של השרטוט הנבחר ───
    _render_drawing_card(results[idx])
    _render_validation_warnings(results[idx])
    _render_stage_model_feedback(
        (results[idx].get("_cost_info") or {}),
        title="🤖 מודל בפועל בשלבי ניתוח השרטוט הזה",
        expanded=False,
    )

    # ─── 5. ניתוח קשרים ───
    st.divider()
    st.markdown("### 3️⃣ ניתוח קשרי המכלול")

    rel = st.session_state["asm_relationships"]

    # שורת פעולה עליונה — רק ניתוח ושמירת JSON גולמי
    col_r1, col_r2 = st.columns([3, 1])
    with col_r1:
        if st.button("🔗 נתח קשרי אבא/בן בין כל השרטוטים",
                     type="primary", use_container_width=True):
            with st.spinner("🔄 שולח את כל השרטוטים לניתוח..."):
                try:
                    rel = analyze_relationships(results)
                    st.session_state["asm_relationships"] = rel
                except Exception as exc:
                    logger.exception("Relationships analysis failed")
                    _show_error(exc, prefix="שגיאה בניתוח קשרים")
                    rel = None
    with col_r2:
        if rel and st.button("💾 שמור JSON גולמי",
                             use_container_width=True,
                             help="מבנה הנתונים המלא של כל השרטוטים + הקשרים"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            payload = {"drawings": results, "relationships": rel}
            path = save_to_json(payload, output_dir / f"_assembly_{ts}.json")
            st.success(f"נשמר: `{path.name}`")

    # ─── 6. הורדת קבצים — מאורגן ב-expander עם טאבים ───
    if rel is None:
        st.info("💡 לאחר ניתוח הקשרים, תוכל להוריד דוחות PDF ו-Excel "
                "מסעיף 'הורדת קבצים' שיופיע כאן.")

    with st.expander("📦 הורדת קבצים (PDF / Excel)",
                     expanded=bool(rel)):
        if rel is None:
            st.caption("ℹ️ ניתן להפיק קבצים גם ללא ניתוח קשרים, "
                       "אבל הם יוצגו כרשימה שטוחה במקום עץ מובנה.")

        tab_pdf_full, tab_pdf_tree, tab_xlsx_full, tab_xlsx_tree = st.tabs([
            "📕 PDF מלא",
            "🌳 PDF עץ מקוצר",
            "📊 Excel מלא",
            "📊 Excel עץ מקוצר",
        ])

        # ── טאב 1: דוח PDF מלא ──
        with tab_pdf_full:
            st.caption("דוח PDF מקיף לכל שרטוט: כותרת, חומר, תהליכים, "
                       "תקנים, NOTES, ובסוף ניתוח הקשרים בין השרטוטים.")
            _render_export_pair(
                button_label="📕 צור דוח PDF מלא",
                spinner_text="📄 מייצר דוח PDF...",
                build_fn=lambda p: build_assembly_pdf(results, rel, p),
                out_path=output_dir / f"_assembly_report_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}.pdf",
                state_key="asm_pdf_path",
                mime="application/pdf",
                btn_key="btn_pdf_full",
                dl_key="dl_pdf_full",
                err_label="PDF",
            )

        # ── טאב 2: דוח PDF עץ מקוצר ──
        with tab_pdf_tree:
            st.caption("דוח PDF קצר: טבלת עץ מוצר + סכמה גרפית של "
                       "המבנה ההיררכי. ללא פירוט תהליכים לכל שרטוט.")
            _render_export_pair(
                button_label="🌳 צור דוח עץ מוצר (PDF)",
                spinner_text="📄 מייצר דוח עץ...",
                build_fn=lambda p: build_tree_pdf(results, rel, p),
                out_path=output_dir / f"_assembly_tree_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}.pdf",
                state_key="asm_tree_pdf_path",
                mime="application/pdf",
                btn_key="btn_pdf_tree",
                dl_key="dl_pdf_tree",
                err_label="PDF עץ",
            )

        # ── טאב 3: Excel מלא ──
        with tab_xlsx_full:
            st.caption("Excel רב-גיליונות (12 sheets): כל הנתונים — "
                       "סקירה, BOM, חומרים, תהליכים, תקנים, ועוד, "
                       "כולל גיליון 'עץ מתמונה' עם קישור לשרטוטים. "
                       "מתאים לניתוח מעמיק.")
            _render_export_pair(
                button_label="📊 צור Excel מלא (11 גיליונות)",
                spinner_text="📄 מייצר Excel מקיף...",
                build_fn=lambda p: build_assembly_excel(results, rel, p),
                out_path=output_dir / f"_assembly_full_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                state_key="asm_full_xlsx_path",
                mime="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
                btn_key="btn_xlsx_full",
                dl_key="dl_xlsx_full",
                err_label="Excel מלא",
            )

        # ── טאב 4: Excel עץ מקוצר ──
        with tab_xlsx_tree:
            st.caption("Excel עם עץ המוצר האמיתי בגיליון Tree, "
                       "ובנפרד גיליון OverviewImage לעץ מהתמונה + "
                       "קישור בפועל ל-P/N/Drawing/חומר מה-BOM. "
                       "פורמט נוח לייבוא ל-ERP.")
            _render_export_pair(
                button_label="📊 צור עץ מוצר ל-Excel",
                spinner_text="📄 מייצר Excel של עץ המוצר...",
                build_fn=lambda p: build_tree_excel(results, rel, p),
                out_path=output_dir / f"_assembly_tree_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                state_key="asm_tree_xlsx_path",
                mime="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
                btn_key="btn_xlsx_tree",
                dl_key="dl_xlsx_tree",
                err_label="Excel עץ",
            )

    if rel:
        _render_stage_model_feedback(
            (rel.get("_cost_info") or {}),
            title="🤖 מודל בפועל בשלב ניתוח הקשרים",
            expanded=False,
        )
        _render_relationships(rel)
