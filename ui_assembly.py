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

from core import audit, notifications
from core.assembly import (
    analyze_relationships,
    extract_assembly_drawing,
    extract_assembly_overview_image,
)
from core.exceptions import format_error_for_ui, get_streamlit_level
from core.history import append_history
from core.pn_utils import cross_reference_part_numbers
from storage.pdf_report import (
    build_assembly_excel,
    build_assembly_html,
    build_tree_excel,
    build_tree_html,
)
from storage.save_handler import save_to_json

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


_SUMMARY_PILL_STYLE = (
    "display:inline-flex; flex-direction:column; align-items:flex-start; "
    "background:white; border:1px solid #dee2e6; border-radius:0.45em; "
    "padding:0.5em 0.85em; margin:0 0.4em 0.4em 0; min-width:140px;"
)
_SUMMARY_PILL_STYLE_EDITED = (
    "display:inline-flex; flex-direction:column; align-items:flex-start; "
    "background:#fffbe6; border:1px solid #ffd666; border-radius:0.45em; "
    "padding:0.5em 0.85em; margin:0 0.4em 0.4em 0; min-width:140px;"
)
_SUMMARY_PILL_LABEL_STYLE = (
    "font-size:0.72em; color:#6c757d; text-transform:uppercase; "
    "letter-spacing:0.04em; margin-bottom:0.15em;"
)
_SUMMARY_PILL_VALUE_STYLE = (
    "font-size:1.0em; font-weight:600; color:#212529; "
    "unicode-bidi:plaintext; line-height:1.25;"
)


def _summary_pill(label: str, value: str, *, edited: bool = False) -> str:
    safe_value = value or "—"
    style = _SUMMARY_PILL_STYLE_EDITED if edited else _SUMMARY_PILL_STYLE
    edit_mark = ' <span style="color:#d48806;" title="נערך ידנית">✏️</span>' if edited else ""
    return (
        f'<div style="{style}">'
        f'<div style="{_SUMMARY_PILL_LABEL_STYLE}">{label}{edit_mark}</div>'
        f'<div style="{_SUMMARY_PILL_VALUE_STYLE}">{safe_value}</div>'
        f'</div>'
    )


def _get_review_status(result: dict) -> str:
    """מחזיר סטטוס review: pending | edited | reviewed."""
    return (result.get("_review_status") or "pending").lower()


def _review_badge_html(status: str, ts: str = "") -> str:
    """באנר קטן לסטטוס review (להצגה בכותרת summary card)."""
    if status == "reviewed":
        when = ts[:19].replace("T", " ") if ts else ""
        suffix = f" · {when}" if when else ""
        return (
            f'<span style="background:#d1e7dd; color:#0f5132; '
            f'padding:0.18em 0.65em; border-radius:1em; font-size:0.82em; '
            f'font-weight:600; margin-right:0.5em;">'
            f'✅ אושר ע"י משתמש{suffix}</span>'
        )
    if status == "edited":
        return (
            '<span style="background:#fff3cd; color:#664d03; '
            'padding:0.18em 0.65em; border-radius:1em; font-size:0.82em; '
            'font-weight:600; margin-right:0.5em;">'
            '✏️ נערך · ממתין לאישור</span>'
        )
    return (
        '<span style="background:#e2e3e5; color:#41464b; '
        'padding:0.18em 0.65em; border-radius:1em; font-size:0.82em; '
        'font-weight:600; margin-right:0.5em;">'
        '⏳ ממתין ל-review</span>'
    )


def render_summary_card(d: dict, *, demo: bool = False) -> None:
    """תקציר החלטה בראש מסך התוצאות — לפני כל הפירוט.

    מציג את השדות המרכזיים, פירוט אזהרות לפי חומרה, וקיצור דרך לסעיף הייצוא.
    מיועד למשתמש עסקי שצריך תשובה מהירה לפני שצולל לפרטים.
    """
    pn = (d.get("part_number") or "").strip()
    dn = (d.get("drawing_number") or "").strip()
    rev = (d.get("revision") or "").strip()
    cust = (d.get("customer") or "").strip()
    mat = (d.get("material") or "").strip()
    role = (d.get("assembly_role") or "").strip()

    edits = d.get("_user_edits") or {}
    review_status = _get_review_status(d)
    review_ts = d.get("_review_timestamp") or ""

    warnings = d.get("_validation_warnings") or []
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for w in warnings:
        sev = (w.get("severity") or "LOW").upper()
        if sev not in sev_counts:
            sev = "LOW"
        sev_counts[sev] += 1

    sev_chips = []
    for sev, label, color in [
        ("CRITICAL", "קריטיות", "#dc3545"),
        ("HIGH", "גבוהות", "#fd7e14"),
        ("MEDIUM", "בינוניות", "#ffc107"),
        ("LOW", "מידע", "#198754"),
    ]:
        n = sev_counts[sev]
        if n == 0:
            continue
        sev_chips.append(
            f'<span style="background:{color}; color:white; padding:0.18em 0.65em; '
            f'border-radius:1em; font-size:0.85em; font-weight:600; margin:0 0.25em;">'
            f'{n} {label}</span>'
        )

    if not warnings:
        warning_html = (
            '<span style="color:#198754; font-weight:600;">'
            '✅ אין אזהרות ולידציה</span>'
        )
    else:
        warning_html = (
            f'<span style="color:#495057; font-weight:600; margin-left:0.4em;">'
            f'⚠️ {len(warnings)} אזהרות:</span>' + "".join(sev_chips)
        )

    demo_banner = ""
    if demo:
        demo_banner = (
            '<div style="background:#fff3cd; color:#664d03; padding:0.35em 0.7em; '
            'border-radius:0.4em; margin-bottom:0.7em; font-size:0.88em; '
            'font-weight:600;">'
            '🎬 מצב דמו — תוצאה זו נטענה מקובץ דוגמה (לא נקראה ל-Azure).'
            '</div>'
        )

    pills_html = "".join([
        _summary_pill("Part Number", pn, edited="part_number" in edits),
        _summary_pill("Drawing Number", dn, edited="drawing_number" in edits),
        _summary_pill("Revision", rev, edited="revision" in edits),
        _summary_pill("Customer", cust, edited="customer" in edits),
        _summary_pill("Role", role),
    ])
    material_pill = _summary_pill("Material", mat, edited="material" in edits)

    st.markdown(
        f'<div dir="rtl" style="background:#f8f9fa; border:1px solid #dee2e6; '
        f'border-right:5px solid #0d6efd; border-radius:0.6em; '
        f'padding:1em 1.2em; margin-bottom:1em;">'
        f'{demo_banner}'
        f'<div style="display:flex; align-items:center; '
        f'margin-bottom:0.7em; flex-wrap:wrap;">'
        f'<div style="font-size:1.05em; font-weight:700; color:#0d6efd; '
        f'margin-left:0.5em;">📋 תקציר ניתוח</div>'
        f'{_review_badge_html(review_status, review_ts)}'
        f'</div>'
        f'<div style="display:flex; flex-wrap:wrap;">{pills_html}</div>'
        f'<div style="margin-top:0.5em;">{material_pill}</div>'
        f'<div style="margin-top:0.6em; padding-top:0.6em; '
        f'border-top:1px solid #dee2e6;">{warning_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


_EDITABLE_SCALAR_FIELDS: list[tuple[str, str, str]] = [
    ("part_number", "P/N", "Part Number"),
    ("drawing_number", "DWG", "Drawing Number"),
    ("revision", "Rev", "Revision"),
    ("customer", "לקוח", "Customer"),
    ("material", "חומר", "Material"),
    ("quantity", "כמות", "Quantity"),
]


def _strip(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def render_review_edit_form(result: dict, *, key_prefix: str = "review") -> bool:
    """טופס לעריכת שדות מרכזיים + אישור התוצאה לפני export.

    מעדכן את ``result`` במקום (in-place mutation):
      - ערכי השדות הנערכים מוחלפים.
      - ``_user_edits[field] = original_value`` — נשמר רק בעריכה הראשונה.
      - ``_review_status`` = ``edited`` כשנעשו שינויים, ``reviewed`` אחרי אישור.
      - ``_review_timestamp`` נכתב באישור.

    מחזיר ``True`` אם המשתמש אישר את התוצאה (להפעלת UI אחר אם רוצים).
    """
    from datetime import datetime as _dt

    status = _get_review_status(result)
    user_edits: dict = result.get("_user_edits") or {}

    # ─── אם כבר אושר — מציגים סטטוס + כפתור עריכה מחדש ───
    if status == "reviewed":
        ts = result.get("_review_timestamp", "")
        when = ts[:19].replace("T", " ") if ts else ""
        st.success(
            f"✅ התוצאה אושרה ע\"י המשתמש{' ב-' + when if when else ''}. "
            f"הדוחות יסומנו כעבר review ידני."
        )
        if st.button(
            "✏️ ערוך מחדש",
            key=f"{key_prefix}_edit_again",
            help="חזרה למצב עריכה — האישור הקודם יימחק",
        ):
            result["_review_status"] = "edited" if user_edits else "pending"
            result.pop("_review_timestamp", None)
            st.rerun()
        return True

    # ─── הודעה מנחה ───
    nudge_text = (
        "💡 **לפני יצירת דוח:** עברי על השדות המרכזיים, תקני אם צריך, "
        "ולחצי 'אשר תוצאה'. אם הכל נראה תקין — לחצי ישר אישור."
    )
    if user_edits:
        nudge_text += f"\n\n📝 ערכת עד עתה {len(user_edits)} שדות."
    st.info(nudge_text)

    # ─── הטופס עצמו ───
    with st.form(key=f"{key_prefix}_form", border=True):
        st.markdown("#### ✏️ עריכת שדות מרכזיים")

        cols = st.columns(2)
        new_scalars: dict[str, str] = {}
        for i, (key, label_he, label_en) in enumerate(_EDITABLE_SCALAR_FIELDS):
            with cols[i % 2]:
                current = _strip(result.get(key))
                marker = " ✏️" if key in user_edits else ""
                new_scalars[key] = st.text_input(
                    f"{label_he} ({label_en}){marker}",
                    value=current,
                    key=f"{key_prefix}_{key}",
                )

        # תקנים — רשימה כמחרוזת מופרדת בפסיק
        stds_list = result.get("standards") or []
        if not isinstance(stds_list, list):
            stds_list = []
        stds_str = ", ".join(_strip(s) for s in stds_list)
        marker = " ✏️" if "standards" in user_edits else ""
        new_stds_str = st.text_area(
            f"תקנים (Standards) — מופרדים בפסיק{marker}",
            value=stds_str,
            key=f"{key_prefix}_standards",
            height=70,
        )

        # אריזה — he + en
        pkg = result.get("packaging_notes") or {}
        if not isinstance(pkg, dict):
            pkg = {}
        pkg_cols = st.columns(2)
        with pkg_cols[0]:
            marker = " ✏️" if "packaging_notes.he" in user_edits else ""
            new_pkg_he = st.text_area(
                f"הוראת אריזה (עברית){marker}",
                value=_strip(pkg.get("he", "")),
                key=f"{key_prefix}_pkg_he",
                height=70,
            )
        with pkg_cols[1]:
            marker = " ✏️" if "packaging_notes.en" in user_edits else ""
            new_pkg_en = st.text_area(
                f"הוראת אריזה (English){marker}",
                value=_strip(pkg.get("en", "")),
                key=f"{key_prefix}_pkg_en",
                height=70,
            )

        submitted = st.form_submit_button(
            "💾 שמור שינויים",
            use_container_width=True,
        )

        if submitted:
            changes_count = 0

            # שדות סקלריים
            for key, _label_he, _label_en in _EDITABLE_SCALAR_FIELDS:
                old = _strip(result.get(key))
                new = new_scalars[key].strip()
                if new != old:
                    if key not in user_edits:
                        user_edits[key] = old
                    result[key] = new
                    changes_count += 1

            # תקנים
            new_stds = [s.strip() for s in new_stds_str.split(",") if s.strip()]
            if new_stds != [_strip(s) for s in stds_list]:
                if "standards" not in user_edits:
                    user_edits["standards"] = list(stds_list)
                result["standards"] = new_stds
                changes_count += 1

            # אריזה
            for sub_key, new_val, old_val in [
                ("he", new_pkg_he.strip(), _strip(pkg.get("he", ""))),
                ("en", new_pkg_en.strip(), _strip(pkg.get("en", ""))),
            ]:
                if new_val != old_val:
                    edit_key = f"packaging_notes.{sub_key}"
                    if edit_key not in user_edits:
                        user_edits[edit_key] = old_val
                    if not isinstance(result.get("packaging_notes"), dict):
                        result["packaging_notes"] = {"he": "", "en": ""}
                    result["packaging_notes"][sub_key] = new_val
                    changes_count += 1

            if changes_count:
                result["_user_edits"] = user_edits
                result["_review_status"] = "edited"
                # אישור קודם בטל אם היה
                result.pop("_review_timestamp", None)
                st.success(f"✅ נשמרו {changes_count} שינויים")
                st.rerun()
            else:
                st.caption("אין שינויים לשמירה")

    # ─── כפתור אישור (מחוץ לטופס כדי שלא יוגש יחד עם 'שמור שינויים') ───
    approve_cols = st.columns([1, 2])
    with approve_cols[0]:
        if st.button(
            "✅ אשר תוצאה לייצוא",
            type="primary",
            use_container_width=True,
            key=f"{key_prefix}_approve",
        ):
            result["_review_status"] = "reviewed"
            result["_review_timestamp"] = _dt.now().isoformat()
            audit.log_approve(
                result.get("part_number") or "?",
                has_edits=bool(result.get("_user_edits")),
            )
            st.rerun()
    with approve_cols[1]:
        st.caption(
            "אישור התוצאה יסמן את הדוחות שייוצאו כעבר review ידני "
            "ויפתח את כפתורי הייצוא."
        )
    return False


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


# ═══════════════════════════════════════════════════════════════════
# Tabbed view of drawing details — splits the same content into 5 tabs
# for less cognitive load. Used by app.py + ui_assembly.py.
# ═══════════════════════════════════════════════════════════════════

def _step_table(items: list, headers=("שלב", "אנגלית", "עברית", "פרטים"),
                keys=("step_no", "name_en", "name_he", "details")) -> None:
    if not items:
        return
    rows = []
    for it in items:
        if isinstance(it, dict):
            rows.append({h: it.get(k, "") for h, k in zip(headers, keys, strict=True)})
        else:
            rows.append({headers[0]: "", headers[1]: str(it), headers[2]: "", headers[3]: ""})
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_drawing_tabs(d: dict) -> None:
    """תצוגה מאורגנת בטאבים — אלטרנטיבה ל-_render_drawing_card הישן.

    5 טאבים מארגנים את אותו התוכן לפי קונטקסט קוגניטיבי:
        🎯 סקירה  ·  📋 BOM  ·  🔧 תהליכים  ·  📜 תקנים  ·  📦 אריזה+הערות

    מקטין עומס ויזואלי במסך תוצאות. ה-_render_drawing_card הישן נשאר
    זמין למודולים שעדיין משתמשים בו.
    """
    bom_items = d.get("bom_items") or []
    has_bom = bool(bom_items)
    standards = d.get("standards") or []
    pkg = d.get("packaging_notes") or {}
    notes = (d.get("notes") or "").strip()

    has_processes = any([
        d.get("machining_processes"), d.get("welding_processes"),
        d.get("heat_treatment_processes"), d.get("coating_processes"),
        d.get("painting_processes"), d.get("ndt_processes"),
        d.get("inspection_processes"), d.get("final_approval"),
        d.get("additional_processes"),
    ])

    tab_overview, tab_bom, tab_proc, tab_std, tab_pack = st.tabs([
        "🎯 סקירה",
        f"📋 BOM ({len(bom_items)})" if has_bom else "📋 BOM",
        "🔧 תהליכים" if has_processes else "🔧 תהליכים (ריק)",
        f"📜 תקנים ({len(standards)})" if standards else "📜 תקנים",
        "📦 אריזה והערות",
    ])

    # ─── Tab 1: Overview (header card + general instructions + environment) ───
    with tab_overview:
        pn = d.get("part_number") or "—"
        dn = d.get("drawing_number") or "—"
        rev = d.get("revision") or "—"
        cust = d.get("customer") or "—"
        mat = d.get("material") or "—"
        qty = d.get("quantity") or "—"
        role = d.get("assembly_role") or "—"
        st.markdown(
            f'<div dir="rtl" style="unicode-bidi:plaintext; '
            f'background:linear-gradient(135deg,#eef5ff 0%,#e8f5e9 100%); '
            f'border:2px solid #0d6efd; border-radius:0.7em; padding:1em 1.2em; '
            f'margin-bottom:0.8em; font-size:0.95em; line-height:1.7;">'
            f'<div style="font-size:1.05em; font-weight:700; color:#0d6efd; '
            f'margin-bottom:0.4em;">🎯 פרטי השרטוט</div>'
            f'<div><span style="color:#6c757d;">פריט:</span> <b>{pn}</b> &nbsp;·&nbsp; '
            f'<span style="color:#6c757d;">שרטוט:</span> <b>{dn}</b> &nbsp;·&nbsp; '
            f'<span style="color:#6c757d;">גרסה:</span> <b>{rev}</b> &nbsp;·&nbsp; '
            f'<span style="color:#6c757d;">לקוח:</span> <b>{cust}</b></div>'
            f'<div style="margin-top:0.4em;"><span style="color:#6c757d;">חומר:</span> <b>{mat}</b> '
            f'&nbsp;·&nbsp; <span style="color:#6c757d;">תפקיד:</span> <b>{role}</b> '
            f'&nbsp;·&nbsp; <span style="color:#6c757d;">כמות:</span> <b>{qty}</b></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        gen_instr = d.get("general_instructions") or []
        if gen_instr and isinstance(gen_instr, list):
            with st.expander("📜 הוראות כלליות", expanded=False):
                for item in gen_instr:
                    if isinstance(item, str) and item.strip():
                        st.markdown(f"- {item.strip()}")
        env_req = d.get("environment_requirements") or []
        if env_req and isinstance(env_req, list):
            with st.expander("🌡️ תנאי סביבה / Clean Room", expanded=True):
                for item in env_req:
                    if isinstance(item, str) and item.strip():
                        st.markdown(f"- {item.strip()}")

    # ─── Tab 2: BOM ───
    with tab_bom:
        if not has_bom:
            st.caption("אין פריטי BOM בשרטוט הזה (לרוב = שרטוט PART בודד).")
        else:
            rows = []
            for it in bom_items:
                if isinstance(it, dict):
                    rows.append({
                        "Item": it.get("item_no", ""),
                        "Part Number": it.get("part_number", ""),
                        "Description": it.get("description", ""),
                        "Qty": it.get("qty", ""),
                    })
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)

    # ─── Tab 3: Processes (machining/welding/heat/coating/painting/NDT/inspection/final/additional) ───
    with tab_proc:
        if not has_processes:
            st.caption("לא נמצאו תהליכי ייצור בשרטוט.")
        if d.get("machining_processes"):
            st.markdown("##### 🔧 עיבוד שבבי")
            _step_table(d["machining_processes"])
        if d.get("welding_processes"):
            st.markdown("##### 🔥 ריתוך")
            _step_table(d["welding_processes"])
        if d.get("heat_treatment_processes"):
            st.markdown("##### 🌡️ טיפול חום")
            _step_table(d["heat_treatment_processes"])
        coatings = d.get("coating_processes") or []
        if coatings:
            st.markdown("##### 🎨 ציפויים / טיפול שטח")
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
            st.markdown("##### 🖌️ צביעות")
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
        if d.get("ndt_processes"):
            st.markdown("##### 🔬 בדיקות NDT")
            _step_table(d["ndt_processes"])
        if d.get("inspection_processes"):
            st.markdown("##### 🔍 בדיקות")
            _step_table(d["inspection_processes"])
        if d.get("final_approval"):
            st.markdown("##### ✅ אישור סופי")
            _step_table(d["final_approval"])
        if d.get("additional_processes"):
            st.markdown("##### 🛠️ תהליכים מלווים")
            _step_table(d["additional_processes"])

    # ─── Tab 4: Standards ───
    with tab_std:
        if not standards:
            st.caption("לא נמצאו תקנים בשרטוט.")
        else:
            st.markdown("##### 📜 כל התקנים שמופיעים בשרטוט")
            st.markdown(" &nbsp;·&nbsp; ".join(f"`{s}`" for s in standards))

    # ─── Tab 5: Packaging + Notes + JSON ───
    with tab_pack:
        if isinstance(pkg, dict) and (pkg.get("he") or pkg.get("en")):
            st.markdown("##### 📦 אריזה")
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
        else:
            st.caption("לא נמצאה דרישת אריזה.")
        if notes:
            st.markdown("##### 📝 הערות (NOTES)")
            st.info(notes)
        with st.expander("📄 JSON מלא (admin/debug)", expanded=False):
            st.json({k: v for k, v in d.items() if not k.startswith("_")})


_SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
_SEVERITY_LABEL_HE = {
    "CRITICAL": "קריטי — דורש בדיקה לפני export",
    "HIGH": "גבוה — מומלץ לבדוק",
    "MEDIUM": "בינוני — שווה תשומת לב",
    "LOW": "מידע בלבד",
}

# הצעות גנריות "מה לבדוק" לפי סוג ה-warning. מאפשר ל-UI להראות actionable
# advice בלי להוסיף שדה למודל הוולידציה עצמו.
_WARNING_ACTION_HINTS = {
    "RAL_INVALID":          "השוו לקוד RAL הנכון מטבלת RAL הרשמית.",
    "RAL_NONSTANDARD":      "ייתכן שהמודל קרא קוד שגוי — אמתו מול ה-NOTES.",
    "BRAND_INVALID":        "בדקו אם שם המותג נכתב נכון בשרטוט.",
    "COATING_TYPE":         "ודאו שסיווג הציפוי תואם לתקן בשרטוט.",
    "PACKING_NOTE":         "ודאו שצוות האריזה מעודכן לדרישות.",
    "MISSING_PACKING":      "בדקו ידנית את סעיף PACKING בשרטוט.",
    "POSSIBLE_OBSOLETE_SPEC": "התקן עלול להיות מוחלף — אמתו מול הלקוח.",
    "STANDARD_HALLUCINATION": "התקן לא נמצא ב-OCR — בדקו ידנית בשרטוט.",
    "STANDARD_MISMATCH":    "השוו את התקן לטקסט מקור (OCR/PDF).",
    "DWG_PREFIX":           "בדקו שמספר השרטוט תואם לקידומת לקוח.",
    "PN_MISMATCH":          "השוו את ה-P/N לתוכן השרטוט ולשם הקובץ.",
    "NO_PACKING_REQUIREMENT_IN_DRAWING": "המודל סימן שאין דרישת אריזה — בדקו לוודא.",
}


def _action_hint_for_warning(w: dict) -> str:
    """מחזיר רמז 'מה לבדוק' לפי סוג ה-warning, או ברירת מחדל גנרית."""
    wtype = (w.get("type") or "").strip().upper()
    if wtype in _WARNING_ACTION_HINTS:
        return _WARNING_ACTION_HINTS[wtype]
    # מנסים match חלקי
    for key, hint in _WARNING_ACTION_HINTS.items():
        if key in wtype:
            return hint
    return "בדקו את השדה ידנית בשרטוט המקורי."


def _render_validation_warnings(result: dict) -> None:
    """מציג אזהרות ולידציה אם קיימות, עם 'מה לבדוק' לכל אזהרה."""
    warnings = result.get("_validation_warnings") or []
    if not warnings:
        return
    critical = [w for w in warnings if w.get("severity") == "CRITICAL"]
    label = f"⚠️ {len(warnings)} אזהרות ולידציה"
    if critical:
        label += f" — {len(critical)} 🔴 קריטיות"
    with st.expander(label, expanded=bool(critical)):
        for w in warnings:
            sev = (w.get("severity") or "").upper()
            icon = _SEVERITY_ICON.get(sev, "⚪")
            sev_label = _SEVERITY_LABEL_HE.get(sev, sev or "")
            value_str = str(w.get("value", ""))[:80]
            st.markdown(
                f"{icon} **{w.get('type', '')}** · _{sev_label}_  \n"
                f"מקור: `{w.get('source', '')}` · ערך: `{value_str}`  \n"
                f"_{w.get('message', '')}_  \n"
                f"💡 **מה לבדוק:** {_action_hint_for_warning(w)}"
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
        # log to history (best-effort)
        try:
            total_cost = sum(
                (r.get("_cost_info") or {}).get("total_cost_usd", 0)
                for r in results
            )
            total_warnings = sum(
                len(r.get("_validation_warnings") or []) for r in results
            )
            asm_pn = next(
                (r.get("part_number", "") for r in results
                 if r.get("assembly_role", "").upper() == "ASSEMBLY"),
                results[0].get("part_number", "") if results else "",
            )
            append_history(
                filename=f"{len(results)} drawings",
                mode="assembly",
                part_number=asm_pn,
                drawing_count=len(results),
                warning_count=total_warnings,
                cost_usd=total_cost,
                cache_hit=(total_cost == 0),
            )
            for r in results:
                audit.log_extract(
                    r.get("source_filename", "?"),
                    cost_usd=(r.get("_cost_info") or {}).get("total_cost_usd", 0),
                    cache_hit=(r.get("_cost_info") or {}).get("total_cost_usd", 0) == 0,
                    mode="assembly",
                )
            # Send batch completion notification (only if any channel configured)
            if notifications.is_any_channel_configured():
                notification_results = notifications.notify_batch_complete(
                    drawing_count=total,
                    success_count=len(results),
                    failed_count=total - len(results),
                    total_cost_usd=total_cost,
                    total_warnings=total_warnings,
                )
                channels_sent = [k for k, v in notification_results.items()
                                 if v and k != "disabled"]
                if channels_sent:
                    st.caption(f"📬 התראת batch נשלחה ל: {', '.join(channels_sent)}")
        except Exception:
            logger.warning("history logging failed", exc_info=True)
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
    render_summary_card(results[idx])
    render_drawing_tabs(results[idx])
    _render_validation_warnings(results[idx])

    # ─── 4.5 Review של השרטוט הנוכחי ───
    pn_for_key = (results[idx].get("part_number") or f"idx{idx}").replace(" ", "_")
    with st.expander("✏️ Review השרטוט הזה", expanded=False):
        render_review_edit_form(
            results[idx],
            key_prefix=f"asm_review_{idx}_{pn_for_key}",
        )
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

    # ─── סיכום review לכל השרטוטים ───
    _reviewed_count = sum(
        1 for r in results if _get_review_status(r) == "reviewed"
    )
    _total_count = len(results)
    if _reviewed_count < _total_count:
        _pending_pns = [
            (r.get("part_number") or r.get("source_filename") or "?")
            for r in results
            if _get_review_status(r) != "reviewed"
        ]
        st.warning(
            f"⚠️ **Review:** {_reviewed_count}/{_total_count} שרטוטים אושרו. "
            f"הדוחות יכללו גם שרטוטים שלא עברו review. ממליצים לעבור ב-expander "
            f"'✏️ Review השרטוט הזה' תחת כל שרטוט. ממתינים: "
            + ", ".join(f"`{pn}`" for pn in _pending_pns[:5])
            + (" ועוד..." if len(_pending_pns) > 5 else "")
        )
    else:
        st.success(f"✅ כל {_total_count} השרטוטים אושרו ע\"י המשתמש.")

    with st.expander("📦 הורדת קבצים (HTML / Excel)",
                     expanded=bool(rel)):
        if rel is None:
            st.caption("ℹ️ ניתן להפיק קבצים גם ללא ניתוח קשרים, "
                       "אבל הם יוצגו כרשימה שטוחה במקום עץ מובנה.")

        st.caption(
            "💡 הדוחות הם **HTML** — נפתחים בכל דפדפן. "
            "ל-PDF: לחצי בדפדפן Ctrl+P → 'Save as PDF'."
        )

        tab_html_full, tab_html_tree, tab_xlsx_full, tab_xlsx_tree = st.tabs([
            "📄 HTML מלא",
            "🌳 HTML עץ מקוצר",
            "📊 Excel מלא",
            "📊 Excel עץ מקוצר",
        ])

        # ── טאב 1: דוח HTML מלא ──
        with tab_html_full:
            st.caption("דוח HTML מקיף לכל שרטוט: כותרת, חומר, תהליכים, "
                       "תקנים, NOTES, ובסוף ניתוח הקשרים בין השרטוטים.")
            _render_export_pair(
                button_label="📄 צור דוח HTML מלא",
                spinner_text="📄 מייצר דוח HTML...",
                build_fn=lambda p: build_assembly_html(results, rel, p),
                out_path=output_dir / f"_assembly_report_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}.html",
                state_key="asm_html_path",
                mime="text/html",
                btn_key="btn_html_full",
                dl_key="dl_html_full",
                err_label="HTML",
            )

        # ── טאב 2: דוח עץ מקוצר ──
        with tab_html_tree:
            st.caption("דוח HTML קצר: טבלת עץ מוצר + סכמה גרפית של "
                       "המבנה ההיררכי. ללא פירוט תהליכים לכל שרטוט.")
            _render_export_pair(
                button_label="🌳 צור דוח עץ מוצר (HTML)",
                spinner_text="📄 מייצר דוח עץ...",
                build_fn=lambda p: build_tree_html(results, rel, p),
                out_path=output_dir / f"_assembly_tree_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}.html",
                state_key="asm_tree_html_path",
                mime="text/html",
                btn_key="btn_html_tree",
                dl_key="dl_html_tree",
                err_label="HTML עץ",
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
