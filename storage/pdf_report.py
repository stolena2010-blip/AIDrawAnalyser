"""
יצירת דוח PDF למצב 'מכלולים מרובים'.

משתמש ב-PyMuPDF (fitz) ובפונקציה insert_htmlbox התומכת ב-HTML/CSS
ובכיווניות RTL — מאפשרת רינדור עברית באופן אמין.

הדוח כולל:
  • שער עם תאריך + מספר שרטוטים
  • סיכום עברי של ניתוח הקשרים
  • טבלת מכלולים (אבא/בן/כמויות) + יתומים + חלקים חסרים
  • כרטיס מפורט לכל שרטוט: מזהים, BOM, עיבוד שבבי, ציפויים, צביעות,
    בדיקות, אישורים, אריזה, תקנים, הערות.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF


# ─── עזרים ───
def _h(s) -> str:
    """Escape בטוח ל-HTML."""
    return html.escape(str(s if s is not None else ""), quote=True)


def _ltr(s) -> str:
    """עוטף ערך אנגלי/מספרי ב-bdi כדי שיוצג LTR בתוך פסקה RTL.

    מונע 'התהפכויות' של PN/Drawing No./תקנים/כמויות בתוך עברית.
    """
    if s is None or s == "":
        return ""
    return f'<bdi dir="ltr">{_h(s)}</bdi>'


def _join_chip(items: list[str]) -> str:
    if not items:
        return "—"
    return " · ".join(items)


# ─── רכיבי HTML ───
_BASE_CSS = """
<style>
  * { font-family: 'Arial', 'Segoe UI', sans-serif; }
  body { color: #212529; }
  h1 { color: #0d6efd; font-size: 22pt; margin: 0 0 8pt 0; }
  h2 { color: #0d6efd; font-size: 14pt; margin: 10pt 0 4pt 0;
       border-bottom: 1px solid #cfe2ff; padding-bottom: 2pt;
       page-break-after: avoid; }
  h3 { color: #495057; font-size: 11pt; margin: 8pt 0 2pt 0;
       page-break-after: avoid; }
  p, div, td, th { font-size: 9.5pt; line-height: 1.5; }
  table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt 0;
          table-layout: fixed; }
  thead { display: table-header-group; }   /* חזרה אוטומטית של כותרות */
  tr    { page-break-inside: avoid; }      /* לא לחתוך שורה באמצע */
  th { background: #e9ecef; color: #212529; padding: 4pt 6pt;
       border: 1px solid #adb5bd; text-align: right; font-size: 9pt;
       word-wrap: break-word; }
  td { padding: 3pt 6pt; border: 1px solid #ced4da; font-size: 9pt;
       vertical-align: top; word-wrap: break-word; overflow-wrap: anywhere; }
  .meta-card { background: #eef5ff; border: 1pt solid #0d6efd;
               border-radius: 6pt; padding: 8pt 10pt; margin: 4pt 0 8pt 0;
               page-break-inside: avoid; }
  .summary { background: #d4edda; color: #155724; padding: 8pt 10pt;
             border-radius: 5pt; margin: 4pt 0 8pt 0; line-height: 1.7;
             page-break-inside: avoid; }
  .pkg-he { background: #fff3cd; color: #664d03; padding: 6pt 9pt;
            border-radius: 5pt; margin: 3pt 0;
            page-break-inside: avoid; }
  .notes { background: #f8f9fa; border-right: 3pt solid #6c757d;
           padding: 6pt 10pt; margin: 4pt 0; white-space: pre-wrap;
           page-break-inside: avoid; }
  code { font-family: Consolas, monospace; background: #f1f3f5;
         padding: 1pt 4pt; border-radius: 3pt; font-size: 8.5pt;
         direction: ltr; unicode-bidi: bidi-override; }
  bdi  { unicode-bidi: isolate; }
  .muted { color: #6c757d; }
  .badge-ok { background: #198754; color: white; padding: 1pt 5pt;
              border-radius: 3pt; font-size: 8pt; }
  .badge-no { background: #dc3545; color: white; padding: 1pt 5pt;
              border-radius: 3pt; font-size: 8pt; }
  .stds code { display: inline-block; margin: 1pt 2pt; }
  /* רוחבי עמודות קבועים לטבלאות עיקריות */
  table.tbl-bom    col.c-item   { width: 10%; }
  table.tbl-bom    col.c-pn     { width: 22%; }
  table.tbl-bom    col.c-desc   { width: 53%; }
  table.tbl-bom    col.c-qty    { width: 15%; }
  table.tbl-coat   col.c-step   { width: 7%; }
  table.tbl-coat   col.c-typeh  { width: 14%; }
  table.tbl-coat   col.c-typee  { width: 12%; }
  table.tbl-coat   col.c-name   { width: 24%; }
  table.tbl-coat   col.c-std    { width: 19%; }
  table.tbl-coat   col.c-thick  { width: 16%; }
  table.tbl-coat   col.c-rohs   { width: 8%; }
  table.tbl-step   col.c-step   { width: 8%; }
  table.tbl-step   col.c-en     { width: 22%; }
  table.tbl-step   col.c-he     { width: 22%; }
  table.tbl-step   col.c-det    { width: 48%; }
  table.tbl-rel    col.c-pn     { width: 20%; }
  table.tbl-rel    col.c-dwg    { width: 20%; }
  table.tbl-rel    col.c-desc   { width: 38%; }
  table.tbl-rel    col.c-qty    { width: 12%; }
  table.tbl-rel    col.c-flag   { width: 10%; }
</style>
"""


def _wrap_rtl(inner_html: str) -> str:
    """עוטף תוכן ב-HTML מלא עם CSS, כיוון RTL ועברית."""
    return (
        '<html dir="rtl" lang="he"><head><meta charset="utf-8">'
        + _BASE_CSS
        + '</head><body dir="rtl" style="text-align:right; '
        + 'unicode-bidi:plaintext;">'
        + inner_html
        + "</body></html>"
    )


# ─── בלוקי תוכן ───
def _cover_html(n_drawings: int) -> str:
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        f"<h1>📐 דוח ניתוח מכלול</h1>"
        f'<div class="meta-card">'
        f'<p><span class="muted">📅 תאריך הפקה:</span> <b>{ts}</b></p>'
        f'<p><span class="muted">📄 מספר שרטוטים בניתוח:</span> '
        f'<b>{n_drawings}</b></p>'
        f"</div>"
    )


def _cover_html_single(d: dict) -> str:
    """כותרת דוח עבור שרטוט בודד — ללא טרמינולוגיה של מכלול."""
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    pn = d.get("part_number") or "—"
    dn = d.get("drawing_number") or "—"
    rev = d.get("revision") or "—"
    cust = d.get("customer") or "—"
    return (
        f"<h1>📐 דוח ניתוח שרטוט</h1>"
        f'<div class="meta-card">'
        f'<p><span class="muted">📅 תאריך הפקה:</span> <b>{ts}</b></p>'
        f'<p><span class="muted">🔢 מספר פריט:</span> <b>{_ltr(pn)}</b></p>'
        f'<p><span class="muted">📐 מספר שרטוט:</span> <b>{_ltr(dn)}</b></p>'
        f'<p><span class="muted">🔁 גרסה:</span> <b>{_ltr(rev)}</b></p>'
        f'<p><span class="muted">🏢 לקוח:</span> <b>{_h(cust)}</b></p>'
        f"</div>"
    )


def _relationships_html(rel: dict | None) -> str:
    if not rel:
        return ""
    parts = ["<h2>🔗 ניתוח קשרי המכלול</h2>"]

    summary = (rel.get("summary_he") or "").strip()
    if summary:
        parts.append(f'<div class="summary">📋 <b>סיכום:</b><br>{_h(summary)}</div>')

    asms = rel.get("assemblies") or []
    if asms:
        parts.append("<h3>🧩 מכלולים שזוהו</h3>")
        for a in asms:
            ppn = _ltr(a.get("parent_part_number") or "—")
            pdn = _ltr(a.get("parent_drawing_number") or "—")
            kids = a.get("children") or []
            parts.append(
                f'<p><b>📦 מכלול:</b> P/N={ppn} · '
                f'DWG={pdn} · {len(kids)} חלקים</p>'
            )
            if kids:
                head = (
                    "<thead><tr>"
                    "<th>P/N</th><th>Drawing</th><th>תיאור</th>"
                    "<th>כמות</th><th>הועלה?</th>"
                    "</tr></thead>"
                )
                rows = ""
                for k in kids:
                    if not isinstance(k, dict):
                        continue
                    in_files = k.get("found_in_uploaded_files")
                    badge = ('<span class="badge-ok">✓</span>' if in_files
                             else '<span class="badge-no">✗</span>')
                    rows += (
                        f"<tr>"
                        f"<td>{_ltr(k.get('part_number',''))}</td>"
                        f"<td>{_ltr(k.get('drawing_number',''))}</td>"
                        f"<td>{_h(k.get('description',''))}</td>"
                        f"<td>{_ltr(k.get('qty',''))}</td>"
                        f"<td>{badge}</td>"
                        f"</tr>"
                    )
                parts.append(
                    '<table class="tbl-rel">'
                    '<colgroup>'
                    '<col class="c-pn"><col class="c-dwg">'
                    '<col class="c-desc"><col class="c-qty">'
                    '<col class="c-flag">'
                    '</colgroup>'
                    f'{head}<tbody>{rows}</tbody></table>'
                )

    orphans = rel.get("orphans") or []
    if orphans:
        parts.append("<h3>🪙 שרטוטים ללא הורה</h3>")
        head = "<thead><tr><th>P/N</th><th>Drawing</th><th>סיבה</th></tr></thead>"
        rows = ""
        for o in orphans:
            if not isinstance(o, dict):
                continue
            rows += (
                f"<tr><td>{_ltr(o.get('part_number',''))}</td>"
                f"<td>{_ltr(o.get('drawing_number',''))}</td>"
                f"<td>{_h(o.get('reason_he',''))}</td></tr>"
            )
        parts.append(f"<table>{head}<tbody>{rows}</tbody></table>")

    missing = rel.get("missing_children") or []
    if missing:
        parts.append("<h3>⚠️ חלקים שמופיעים ב-BOM אך לא הועלו</h3>")
        head = (
            "<thead><tr><th>P/N</th><th>תיאור</th>"
            "<th>כמות</th><th>נדרש ע\"י</th></tr></thead>"
        )
        rows = ""
        for m in missing:
            if not isinstance(m, dict):
                continue
            rows += (
                f"<tr><td>{_ltr(m.get('part_number',''))}</td>"
                f"<td>{_h(m.get('description',''))}</td>"
                f"<td>{_ltr(m.get('qty',''))}</td>"
                f"<td>{_h(m.get('needed_by_he',''))}</td></tr>"
            )
        parts.append(f"<table>{head}<tbody>{rows}</tbody></table>")

    warnings = rel.get("warnings_he") or []
    if warnings:
        parts.append("<h3>💡 הערות / אזהרות</h3>")
        for w in warnings:
            parts.append(f'<div class="notes">⚠️ {_h(w)}</div>')

    return "".join(parts)


def _step_table(items: list, headers: list[tuple[str, str]],
                table_class: str = "tbl-step",
                col_classes: list[str] | None = None,
                ltr_keys: tuple[str, ...] = ()) -> str:
    """בונה טבלה כללית.
    headers     = [(label_he, key), ...]
    table_class = שם המחלקה ב-CSS (קובע רוחבי עמודות).
    col_classes = רשימת c-* מהמחלקות ב-CSS, באותו אורך כמו headers.
    ltr_keys    = keys שערכם לועזי וצריך להישאר LTR (PN, Drawing וכד').
    """
    if not items:
        return ""
    head = "".join(f"<th>{_h(label)}</th>" for label, _ in headers)
    rows = ""
    for it in items:
        if not isinstance(it, dict):
            it = {"name": str(it)}
        cells = ""
        for _, k in headers:
            val = it.get(k, "")
            cells += f"<td>{_ltr(val) if k in ltr_keys else _h(val)}</td>"
        rows += f"<tr>{cells}</tr>"

    colgroup = ""
    if col_classes and len(col_classes) == len(headers):
        cols = "".join(f'<col class="{c}">' for c in col_classes)
        colgroup = f"<colgroup>{cols}</colgroup>"

    return (
        f'<table class="{table_class}">{colgroup}'
        f'<thead><tr>{head}</tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _drawing_html(d: dict, idx: int, total: int) -> str:
    pn = _ltr(d.get("part_number") or "—")
    dn = _ltr(d.get("drawing_number") or "—")
    rev = _ltr(d.get("revision") or "—")
    cust = _h(d.get("customer") or "—")
    mat = _h(d.get("material") or "—")
    qty = _ltr(d.get("quantity") or "—")
    role = _h(d.get("assembly_role") or "—")
    src = _ltr(d.get("source_filename") or "")
    cat = (d.get("catalog_number") or "").strip()
    rw = d.get("raw_weight") or {}
    rw_qty = (rw.get("qty") or "").strip() if isinstance(rw, dict) else ""
    rw_unit = (rw.get("unit") or "").strip() if isinstance(rw, dict) else ""
    raw_weight_text = f"{rw_qty} {rw_unit}".strip()
    alt_mat = (d.get("alternative_material") or "").strip()
    os_lvl = (d.get("os_level") or "").strip()
    cage = (d.get("cage_code") or "").strip()
    mat_formerly = (d.get("material_formerly") or "").strip()
    title = (d.get("title") or "").strip()
    pw = d.get("part_weight") or {}
    pw_qty = (pw.get("qty") or "").strip() if isinstance(pw, dict) else ""
    pw_unit = (pw.get("unit") or "").strip() if isinstance(pw, dict) else ""
    part_weight_text = f"{pw_qty} {pw_unit}".strip() if pw_qty or pw_unit else ""

    extras_html = ""
    bits = []
    if title:
        bits.append(f'<span class="muted">כותרת:</span> <b>{_h(title)}</b>')
    if cat:
        bits.append(f'<span class="muted">CAT NO.:</span> <b>{_ltr(cat)}</b>')
    if cage:
        bits.append(f'<span class="muted">CAGE:</span> <b>{_ltr(cage)}</b>')
    if raw_weight_text:
        bits.append(
            f'<span class="muted">משקל חומר גלם:</span> <b>{_ltr(raw_weight_text)}</b>'
        )
    if part_weight_text:
        bits.append(
            f'<span class="muted">משקל פריט:</span> <b>{_ltr(part_weight_text)}</b>'
        )
    if os_lvl:
        bits.append(
            f'<span class="muted">OS Level:</span> '
            f'<b style="color:#b02a37;">{_h(os_lvl)}</b>'
        )
    if bits:
        extras_html = "<p>" + " · ".join(bits) + "</p>"

    alt_html = ""
    if alt_mat:
        alt_html = (
            f'<p style="font-style:italic; color:#495057;">'
            f'🔄 <span class="muted">חומר חלופי מורשה:</span> '
            f'{_h(alt_mat)}</p>'
        )
    if mat_formerly:
        alt_html += (
            f'<p style="font-style:italic; color:#6c757d;">'
            f'📜 <span class="muted">תקנים מבוטלים (formerly):</span> '
            f'{_h(mat_formerly)}</p>'
        )

    parts = [
        f"<h2>📄 שרטוט {idx}/{total} — {pn}</h2>",
        '<div class="meta-card">',
        f'<p><span class="muted">קובץ:</span> {src}</p>',
        f'<p><span class="muted">פריט:</span> <b>{pn}</b> · '
        f'<span class="muted">שרטוט:</span> <b>{dn}</b> · '
        f'<span class="muted">גרסה:</span> <b>{rev}</b> · '
        f'<span class="muted">לקוח:</span> <b>{cust}</b></p>'
        f'<p><span class="muted">חומר:</span> <b>{mat}</b> · '
        f'<span class="muted">תפקיד:</span> <b>{role}</b> · '
        f'<span class="muted">כמות:</span> <b>{qty}</b></p>'
        f'{extras_html}'
        f'{alt_html}'
        "</div>",
    ]

    # הוראות כלליות (סעיף 10)
    gen_instr = d.get("general_instructions") or []
    if gen_instr and isinstance(gen_instr, list):
        rows_html = "".join(
            f"<li>{_h(item)}</li>"
            for item in gen_instr
            if isinstance(item, str) and item.strip()
        )
        if rows_html:
            parts.append(
                f"<h3>📜 הוראות כלליות</h3><ul>{rows_html}</ul>"
            )

    # תנאי סביבה (CLEAN ROOM / ESD / IPA)
    env_req = d.get("environment_requirements") or []
    if env_req and isinstance(env_req, list):
        env_rows = "".join(
            f"<li>{_h(item)}</li>"
            for item in env_req
            if isinstance(item, str) and item.strip()
        )
        if env_rows:
            parts.append(
                f"<h3>🌡️ תנאי סביבה / Clean Room</h3><ul>{env_rows}</ul>"
            )

    # BOM
    bom = d.get("bom_items") or []
    if bom:
        parts.append("<h3>📋 טבלת חלקים (BOM)</h3>")
        parts.append(_step_table(
            bom,
            [("Item", "item_no"), ("Part Number", "part_number"),
             ("תיאור", "description"), ("כמות", "qty")],
            table_class="tbl-bom",
            col_classes=["c-item", "c-pn", "c-desc", "c-qty"],
            ltr_keys=("item_no", "part_number", "qty"),
        ))

    # עיבוד שבבי
    machining = d.get("machining_processes") or []
    if machining:
        parts.append("<h3>🔧 עיבוד שבבי</h3>")
        parts.append(_step_table(
            machining,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # ריתוך
    welding = d.get("welding_processes") or []
    if welding:
        parts.append("<h3>🔥 ריתוך</h3>")
        parts.append(_step_table(
            welding,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # טיפול חום
    heat_treat = d.get("heat_treatment_processes") or []
    if heat_treat:
        parts.append("<h3>🌡️ טיפול חום</h3>")
        parts.append(_step_table(
            heat_treat,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # ציפויים
    coatings = d.get("coating_processes") or []
    if coatings:
        parts.append("<h3>🎨 ציפויים / טיפול שטח</h3>")
        head = (
            "<thead><tr><th>שלב</th><th>סוג (HE)</th><th>סוג (EN)</th>"
            "<th>תיאור</th><th>תקן</th><th>עובי</th><th>RoHS</th></tr></thead>"
        )
        rows = ""
        for c in coatings:
            if not isinstance(c, dict):
                continue
            rohs = '<span class="badge-ok">✓</span>' if c.get("rohs") else ""
            rows += (
                f"<tr>"
                f"<td>{_ltr(c.get('step_no',''))}</td>"
                f"<td>{_h(c.get('type_he',''))}</td>"
                f"<td>{_ltr(c.get('type',''))}</td>"
                f"<td>{_h(c.get('name',''))}</td>"
                f"<td>{_ltr(c.get('standard',''))}</td>"
                f"<td>{_ltr(c.get('thickness',''))}</td>"
                f"<td>{rohs}</td>"
                f"</tr>"
            )
        parts.append(
            '<table class="tbl-coat">'
            '<colgroup>'
            '<col class="c-step"><col class="c-typeh"><col class="c-typee">'
            '<col class="c-name"><col class="c-std"><col class="c-thick">'
            '<col class="c-rohs">'
            '</colgroup>'
            f"{head}<tbody>{rows}</tbody></table>"
        )

    # צביעות
    paintings = d.get("painting_processes") or []
    if paintings:
        parts.append("<h3>🖌️ צביעות</h3>")
        head = (
            "<thead><tr><th>שלב</th><th>סוג (HE)</th><th>סוג (EN)</th>"
            "<th>תיאור</th><th>תקן</th><th>עובי</th><th>RoHS</th></tr></thead>"
        )
        rows = ""
        for p in paintings:
            if not isinstance(p, dict):
                continue
            rohs = '<span class="badge-ok">✓</span>' if p.get("rohs") else ""
            rows += (
                f"<tr>"
                f"<td>{_ltr(p.get('step_no',''))}</td>"
                f"<td>{_h(p.get('type_he',''))}</td>"
                f"<td>{_ltr(p.get('type',''))}</td>"
                f"<td>{_h(p.get('name',''))}</td>"
                f"<td>{_ltr(p.get('standard',''))}</td>"
                f"<td>{_ltr(p.get('thickness',''))}</td>"
                f"<td>{rohs}</td>"
                f"</tr>"
            )
        parts.append(
            '<table class="tbl-coat">'
            '<colgroup>'
            '<col class="c-step"><col class="c-typeh"><col class="c-typee">'
            '<col class="c-name"><col class="c-std"><col class="c-thick">'
            '<col class="c-rohs">'
            '</colgroup>'
            f"{head}<tbody>{rows}</tbody></table>"
        )

    # בדיקות NDT
    ndt = d.get("ndt_processes") or []
    if ndt:
        parts.append("<h3>🔬 בדיקות NDT</h3>")
        parts.append(_step_table(
            ndt,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # בדיקות
    inspect = d.get("inspection_processes") or []
    if inspect:
        parts.append("<h3>🔍 בדיקות</h3>")
        parts.append(_step_table(
            inspect,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # אישור סופי
    final = d.get("final_approval") or []
    if final:
        parts.append("<h3>✅ אישור סופי</h3>")
        parts.append(_step_table(
            final,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # תהליכים מלווים
    additional = d.get("additional_processes") or []
    if additional:
        parts.append("<h3>🛠️ תהליכים מלווים</h3>")
        parts.append(_step_table(
            additional,
            [("שלב", "step_no"), ("אנגלית", "name_en"),
             ("עברית", "name_he"), ("פרטים", "details")],
            table_class="tbl-step",
            col_classes=["c-step", "c-en", "c-he", "c-det"],
            ltr_keys=("step_no", "name_en"),
        ))

    # תקנים
    stds = d.get("standards") or []
    if stds:
        parts.append("<h3>📜 כל התקנים שמופיעים בשרטוט</h3>")
        chips = " ".join(f"<code>{_h(s)}</code>" for s in stds)
        parts.append(f'<p class="stds">{chips}</p>')

    # אריזה
    pkg = d.get("packaging_notes") or {}
    if isinstance(pkg, dict) and (pkg.get("he") or pkg.get("en")):
        parts.append("<h3>📦 אריזה</h3>")
        if pkg.get("he"):
            parts.append(f'<div class="pkg-he">🇮🇱 {_h(pkg["he"])}</div>')
        if pkg.get("en"):
            parts.append(
                f'<div class="pkg-he" dir="ltr" style="text-align:left;">'
                f'🇬🇧 {_h(pkg["en"])}</div>'
            )

    # הערות
    notes = (d.get("notes") or "").strip()
    if notes:
        parts.append("<h3>📝 הערות השרטוט</h3>")
        parts.append(f'<div class="notes">{_h(notes)}</div>')

    return "".join(parts)


# ─── מנוע יצירת ה-PDF ───
def build_assembly_pdf(
    drawings: list[dict],
    relationships: dict | None,
    out_path: Path,
    *,
    single_mode: bool = False,
) -> Path:
    """בונה דוח PDF מלא ושומר אותו ל-out_path.

    משתמש ב-DocumentWriter + Story של PyMuPDF — מטפל אוטומטית
    בגלישת תוכן בין עמודים, כולל RTL לעברית.

    single_mode=True → כותרת "דוח ניתוח שרטוט" (יחיד), ללא סעיף קשרים.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = fitz.paper_size("a4")
    margin = 36
    mediabox = fitz.Rect(0, 0, page_w, page_h)
    where = fitz.Rect(margin, margin, page_w - margin, page_h - margin)

    # אוסף את כל ה-HTML לחלקים — כל חלק יתחיל בעמוד חדש
    sections: list[str] = []
    if single_mode and drawings:
        cover = _cover_html_single(drawings[0])
    else:
        cover = _cover_html(len(drawings)) + _relationships_html(relationships)
    sections.append(_wrap_rtl(cover))
    total = len(drawings)
    for i, d in enumerate(drawings, 1):
        sections.append(_wrap_rtl(_drawing_html(d, i, total)))

    writer = fitz.DocumentWriter(str(out_path))
    try:
        for html_content in sections:
            story = fitz.Story(html=html_content)
            more = 1
            while more:
                dev = writer.begin_page(mediabox)
                more, _filled = story.place(where)
                story.draw(dev)
                writer.end_page()
    finally:
        writer.close()

    return out_path


# ═══════════════════════════════════════════════════════════════
#  דוח עץ מוצר מקוצר — טבלה + סכמה
# ═══════════════════════════════════════════════════════════════

_TREE_CSS_EXTRA = """
<style>
  table.tbl-tree col.c-lvl   { width: 8%; }
  table.tbl-tree col.c-pn    { width: 20%; }
  table.tbl-tree col.c-dwg   { width: 16%; }
  table.tbl-tree col.c-desc  { width: 28%; }
  table.tbl-tree col.c-qty   { width: 8%; }
  table.tbl-tree col.c-mat   { width: 20%; }
  ul.tree { list-style: none; padding-right: 14pt; margin: 2pt 0; }
  ul.tree li { margin: 2pt 0; padding: 3pt 6pt;
               border-right: 2pt solid #0d6efd;
               background: #f8fbff; border-radius: 3pt;
               page-break-inside: avoid; }
  ul.tree li.lvl-0 { border-right-color: #0d6efd; background: #e7f1ff; }
  ul.tree li.lvl-1 { border-right-color: #6610f2; background: #f3ecff; }
  ul.tree li.lvl-2 { border-right-color: #20c997; background: #e7faf3; }
  ul.tree li.lvl-3 { border-right-color: #fd7e14; background: #fff1e6; }
  .tree-pn   { font-weight: bold; }
  .tree-meta { color: #495057; font-size: 9pt; }
  .tree-qty  { color: #198754; font-weight: bold; }
  .tree-mat  { color: #6c757d; font-style: italic; }
</style>
"""


def _wrap_rtl_tree(inner_html: str) -> str:
    return (
        '<html dir="rtl" lang="he"><head><meta charset="utf-8">'
        + _BASE_CSS + _TREE_CSS_EXTRA
        + '</head><body dir="rtl" style="text-align:right; '
        + 'unicode-bidi:plaintext;">'
        + inner_html + "</body></html>"
    )


def _build_drawing_index(drawings: list[dict]) -> dict:
    """ממפה PN → drawing dict לחיפוש מהיר של חומר/תיאור."""
    idx = {}
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        pn = (d.get("part_number") or "").strip().upper()
        if pn:
            idx[pn] = d
    return idx


# ─── חילוץ חומר/ציפוי מתוך טקסט תיאור (fallback) ───
_MATERIAL_PHRASE_PATTERNS = [
    # סגסוגות אלומיניום/פלדה ספציפיות
    r"\b(?:AL|ALUMINUM|ALUMINIUM)[\s\-]?(?:6061|7075|2024|5052|5083|6063)(?:[\s\-]?T\d{1,4})?\b",
    r"\b(?:6061|7075|2024|5052|5083|6063)[\s\-]?T\d{1,4}\b",
    r"\b(?:17[\s\-]?4|17[\s\-]?7|15[\s\-]?5)\s?PH\b(?:\s?H?\d{3,4})?",
    r"\b(?:303|304|316|321|410|416|420|440)\s?(?:STAINLESS|SS|CRES|L)?\b",
    r"\bC36000\b|\bC360\b",
    r"\bTi[\s\-]?6Al[\s\-]?4V\b",
    # תיאורים כלליים — חומר + GRADE
    r"\b(?:STEEL|STAINLESS|CRES|BRASS|BRONZE|TITANIUM|COPPER|INCONEL|MONEL|NYLON|DELRIN|PEEK|ABS|POLYCARBONATE|POM|PTFE|TEFLON)(?:\s+GRADE\s+[A-Z0-9]+)?\b",
    r"\b(?:ALUMINUM|ALUMINIUM|ALLOY|ALUM)\b",
    # ציפויים נפוצים שמופיעים בתיאור
    r"\bZINC\s+PLATED(?:\s+(?:YELLOW|BLUE|WHITE|CLEAR|BLACK))?(?:\s+CHROMATE)?\b",
    r"\b(?:YELLOW|BLUE|WHITE|CLEAR|BLACK)\s+CHROMATE\b",
    r"\b(?:HARD\s+)?ANODIZ(?:E|ED|ING)(?:\s+TYPE\s+[IVX]+)?\b",
    r"\bELECTROLESS\s+NICKEL\b",
    r"\bCAD(?:MIUM)?\s+PLATED\b",
    r"\bPASSIVATE[D]?\b",
    r"\bBLACK\s+OXIDE\b",
]
_MATERIAL_PHRASE_RE = re.compile("|".join(_MATERIAL_PHRASE_PATTERNS), re.IGNORECASE)


def _extract_material_from_description(text: str) -> str:
    """מחלץ ביטויי חומר/ציפוי שמופיעים בתוך תיאור פריט BOM.

    מחזיר את הביטויים שנמצאו מופרדים בפסיק, או מחרוזת ריקה אם לא נמצא דבר.
    """
    if not text:
        return ""
    matches = _MATERIAL_PHRASE_RE.findall(text)
    if not matches:
        return ""
    # נירמול: רווחים בודדים, ייחודיות תוך שמירת סדר
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        norm = re.sub(r"\s+", " ", m.strip()).upper()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return ", ".join(out)


def _resolve_material(node: dict, idx: dict) -> str:
    """מחזיר חומר מהשרטוט שהועלה לפי PN; אחרת מנסה לחלץ מתוך התיאור."""
    pn = (node.get("part_number") or "").strip().upper()
    if pn and pn in idx:
        mat = (idx[pn].get("material") or "").strip()
        if mat:
            return mat
    # Fallback — חלץ מתוך description של הפריט עצמו
    desc = (node.get("description") or "").strip()
    return _extract_material_from_description(desc)


def _resolve_description(node: dict, idx: dict) -> str:
    """תיאור מהקשר אם קיים, אחרת מהשרטוט שהועלה."""
    desc = (node.get("description") or "").strip()
    if desc:
        return desc
    pn = (node.get("part_number") or "").strip().upper()
    if pn and pn in idx:
        d = idx[pn]
        return (d.get("description") or d.get("title")
                or d.get("name") or "").strip()
    return ""


def _flatten_tree_rows(
    drawings: list[dict],
    relationships: dict | None,
) -> list[dict]:
    """בונה רשימת שורות שטוחה עם רמה (level) לעץ המוצר.

    כל שורה: {level, part_number, drawing_number, description, qty, material,
             parent_part_number, root_part_number, hierarchy_path}
    """
    idx = _build_drawing_index(drawings)
    rows: list[dict] = []
    seen_as_child: set[str] = set()
    bom_parent_map: dict[str, dict] = {}

    overview_ids: set[str] = set()
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        role = (d.get("assembly_role") or "").strip().lower()
        if role != "assembly overview image":
            continue
        for raw in (d.get("part_number"), d.get("drawing_number"), d.get("source_filename")):
            val = (raw or "").strip().lower()
            if not val:
                continue
            overview_ids.add(val)
            overview_ids.add(Path(val).stem)

    def _is_overview_value(val: str) -> bool:
        x = (val or "").strip().lower()
        if not x:
            return False
        return (
            x in overview_ids
            or Path(x).stem in overview_ids
            or "asm_temp_image" in x
            or x.startswith("image")
            or "overview image" in x
        )

    asms = (relationships or {}).get("assemblies") or []
    if asms:
        for a in asms:
            if not isinstance(a, dict):
                continue
            ppn = (a.get("parent_part_number") or "").strip()
            pdn = (a.get("parent_drawing_number") or "").strip()
            if _is_overview_value(ppn) or _is_overview_value(pdn):
                continue
            parent_drawing = idx.get(ppn.upper(), {})
            rows.append({
                "level": 0,
                "part_number": ppn or "—",
                "drawing_number": pdn or parent_drawing.get("drawing_number", ""),
                "description": (parent_drawing.get("description")
                                or a.get("parent_description") or ""),
                "qty": "1",
                "material": parent_drawing.get("material", ""),
                "parent_part_number": "",
                "root_part_number": ppn or "—",
                "hierarchy_path": ppn or "—",
            })
            for k in (a.get("children") or []):
                if not isinstance(k, dict):
                    continue
                cpn = (k.get("part_number") or "").strip()
                if cpn:
                    seen_as_child.add(cpn.upper())
                rows.append({
                    "level": 1,
                    "part_number": cpn or "—",
                    "drawing_number": (k.get("drawing_number") or "").strip(),
                    "description": _resolve_description(k, idx),
                    "qty": (k.get("qty") or "").strip() or "1",
                    "material": _resolve_material(k, idx),
                    "parent_part_number": ppn or "—",
                    "root_part_number": ppn or "—",
                    "hierarchy_path": f"{ppn or '—'} > {cpn or '—'}",
                })

    # מפת אב->בן מגיבוי BOM של שרטוטי ASSEMBLY (למקרה שאין קשרים טובים מה-AI)
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        role = (d.get("assembly_role") or "").strip().upper()
        parent = (d.get("part_number") or "").strip()
        if role != "ASSEMBLY" or not parent or _is_overview_value(parent):
            continue
        for it in (d.get("bom_items") or []):
            if not isinstance(it, dict):
                continue
            cpn = (it.get("part_number") or "").strip()
            if not cpn:
                continue
            key = cpn.upper()
            if key not in bom_parent_map:
                bom_parent_map[key] = {
                    "parent": parent,
                    "qty": (it.get("qty") or "").strip(),
                    "description": (it.get("description") or "").strip(),
                }

    # שרטוטים שהועלו ולא הופיעו כילדים — נוסיף כשורות עצמאיות
    extras = []
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        pn = (d.get("part_number") or "").strip()
        if _is_overview_value(pn):
            continue
        if not pn or pn.upper() in seen_as_child:
            continue
        # אם כבר הוצג כהורה — דלג
        if any(r["level"] == 0 and r["part_number"].upper() == pn.upper()
               for r in rows):
            continue
        bom_info = bom_parent_map.get(pn.upper(), {})
        parent = (bom_info.get("parent") or "").strip()

        # אם מזוהה כהבן של מכלול דרך BOM — שים אותו ברמה 1 עם אב ישיר
        if parent and not _is_overview_value(parent):
            if not any(r["level"] == 0 and r["part_number"].upper() == parent.upper()
                       for r in rows + extras):
                pd = idx.get(parent.upper(), {})
                extras.append({
                    "level": 0,
                    "part_number": parent,
                    "drawing_number": (pd.get("drawing_number") or "").strip(),
                    "description": (pd.get("description") or "").strip(),
                    "qty": "1",
                    "material": (pd.get("material") or "").strip(),
                    "parent_part_number": "",
                    "root_part_number": parent,
                    "hierarchy_path": parent,
                })

            extras.append({
                "level": 1,
                "part_number": pn,
                "drawing_number": (d.get("drawing_number") or "").strip(),
                "description": (bom_info.get("description")
                                or (d.get("description") or "").strip()),
                "qty": (bom_info.get("qty")
                       or (d.get("quantity") or "1").strip() or "1"),
                "material": (d.get("material") or "").strip(),
                "parent_part_number": parent,
                "root_part_number": parent,
                "hierarchy_path": f"{parent} > {pn}",
            })
            seen_as_child.add(pn.upper())
            continue

        extras.append({
            "level": 0,
            "part_number": pn,
            "drawing_number": (d.get("drawing_number") or "").strip(),
            "description": (d.get("description") or "").strip(),
            "qty": (d.get("quantity") or "1").strip() or "1",
            "material": (d.get("material") or "").strip(),
            "parent_part_number": "",
            "root_part_number": pn,
            "hierarchy_path": pn,
        })

    if extras and not rows:
        # אין relationships בכלל — הצג רשימה שטוחה
        return extras
    rows.extend(extras)

    # ─── פריטי קנייה (Purchased Parts): פריטי BOM שאין להם שרטוט מועלה ───
    # ברגים, ואשרים, פינים, קאסטורים וכד' מטבעם אין להם שרטוט, והם חלק
    # לגיטימי מהמכלול. אסור להשמיט אותם מעץ המוצר.
    seen_pns: set[str] = {
        (r.get("part_number") or "").strip().upper()
        for r in rows
        if (r.get("part_number") or "").strip() and r.get("part_number") != "—"
    }

    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        role = (d.get("assembly_role") or "").strip().upper()
        parent = (d.get("part_number") or "").strip()
        if role != "ASSEMBLY" or not parent or _is_overview_value(parent):
            continue
        parent_u = parent.upper()
        # ודא שה-parent נמצא בעץ ברמה כלשהי
        if not any(
            (r.get("part_number") or "").strip().upper() == parent_u
            for r in rows
        ):
            continue

        for it in (d.get("bom_items") or []):
            if not isinstance(it, dict):
                continue
            cpn = (it.get("part_number") or "").strip()
            if not cpn:
                continue
            cpn_u = cpn.upper()
            if cpn_u in seen_pns:
                continue  # כבר בעץ (כ-child של LLM או שרטוט הועלה)

            raw_desc = (it.get("description") or "").strip()
            raw_qty = (it.get("qty") or "").strip()
            # זיהוי OCR_UNREADABLE: שני השדות ריקים
            is_unreadable = not raw_desc and not raw_qty
            desc = (
                "[OCR_UNREADABLE] פרטים לא קריאים"
                if is_unreadable
                else (raw_desc or "[PURCHASED PART / NO DRAWING]")
            )
            qty = raw_qty or "—"

            rows.append({
                "level": 1,
                "part_number": cpn,
                "drawing_number": "",
                "description": desc,
                "qty": qty,
                "material": "",
                "parent_part_number": parent,
                "root_part_number": parent,
                "hierarchy_path": f"{parent} > {cpn}",
            })
            seen_pns.add(cpn_u)

    return rows


def _flatten_overview_image_rows(
    drawings: list[dict],
    relationships: dict | None = None,
) -> list[dict]:
    """בונה רשימת שורות נפרדת של פריטי תרשים מכלול מהתמונה בלבד.

    המטרה: לשמור את נתוני הבועיות (Find Numbers) בגיליון נפרד,
    מבלי לערבב אותם בעץ המוצר האמיתי.
    """
    rows: list[dict] = []
    idx = _build_drawing_index(drawings)

    # בנה מפת BOM לפי item_no ממכלול האב (עדיפות לאב שזוהה בניתוח הקשרים)
    root_pn = ""
    asms = (relationships or {}).get("assemblies") or []
    if asms and isinstance(asms[0], dict):
        root_pn = (asms[0].get("parent_part_number") or "").strip().upper()

    selected_asm = None
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        if (d.get("assembly_role") or "").strip().upper() != "ASSEMBLY":
            continue
        if root_pn and (d.get("part_number") or "").strip().upper() == root_pn:
            selected_asm = d
            break
        if selected_asm is None and (d.get("bom_items") or []):
            selected_asm = d

    bom_by_item: dict[str, dict] = {}
    bom_by_pn: dict[str, dict] = {}
    if selected_asm:
        for it in (selected_asm.get("bom_items") or []):
            if not isinstance(it, dict):
                continue
            item_no = str(it.get("item_no") or "").strip()
            pn = (it.get("part_number") or "").strip().upper()
            if item_no and item_no not in bom_by_item:
                bom_by_item[item_no] = it
            if pn and pn not in bom_by_pn:
                bom_by_pn[pn] = it

    for d in drawings or []:
        if not isinstance(d, dict):
            continue

        role = (d.get("assembly_role") or "").strip().lower()
        if role != "assembly overview image":
            continue

        src = d.get("source_filename", "")
        ov_pn = d.get("part_number", "")
        ov_dwg = d.get("drawing_number", "")
        for item in (d.get("bom_items") or []):
            if not isinstance(item, dict):
                continue

            item_no = str(item.get("item_no") or "").strip()
            pn_from_img = (item.get("part_number") or "").strip()

            matched = None
            match_method = ""
            if item_no and item_no in bom_by_item:
                matched = bom_by_item[item_no]
                match_method = "item_no"
            elif pn_from_img and pn_from_img.upper() in bom_by_pn:
                matched = bom_by_pn[pn_from_img.upper()]
                match_method = "part_number"

            matched_pn = (matched.get("part_number") or "") if matched else ""
            display_pn_from_img = pn_from_img
            if matched_pn and (not display_pn_from_img or match_method == "item_no"):
                display_pn_from_img = matched_pn
            linked_pn = ""
            matched_draw = ""
            matched_material = ""
            file_presence = "לא"
            if matched_pn:
                md = idx.get(str(matched_pn).strip().upper(), {})
                if md:
                    linked_pn = matched_pn
                    matched_draw = md.get("drawing_number", "")
                    matched_material = md.get("material", "")
                    file_presence = "כן"

            rows.append({
                "קובץ תמונה": src,
                "P/N תמונה": ov_pn,
                "Drawing תמונה": ov_dwg,
                "Item No.": item_no,
                "P/N מהתמונה": display_pn_from_img,
                "תיאור ויזואלי": item.get("description", ""),
                "כמות מהתמונה": item.get("qty", ""),
                "קושר ל-P/N": linked_pn,
                "קושר ל-Drawing": matched_draw,
                "כמות לפי BOM": (matched.get("qty", "") if matched else ""),
                "חומר מקושר": matched_material,
                "תיאור BOM": (matched.get("description", "") if matched else ""),
                "שיטת קישור": match_method,
                "נמצא בקבצים?": file_presence,
            })
    return rows


def _tree_table_html(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">אין נתוני עץ להצגה.</p>'
    head = (
        "<thead><tr>"
        "<th>רמה</th><th>P/N</th><th>Drawing</th>"
        "<th>תיאור</th><th>כמות</th><th>חומר</th>"
        "</tr></thead>"
    )
    body = ""
    for r in rows:
        lvl = r.get("level", 0)
        indent = "·&nbsp;" * lvl
        body += (
            f"<tr>"
            f"<td>{lvl}</td>"
            f"<td>{indent}{_ltr(r.get('part_number',''))}</td>"
            f"<td>{_ltr(r.get('drawing_number',''))}</td>"
            f"<td>{_h(r.get('description',''))}</td>"
            f"<td>{_ltr(r.get('qty',''))}</td>"
            f"<td>{_h(r.get('material',''))}</td>"
            f"</tr>"
        )
    return (
        '<table class="tbl-tree">'
        '<colgroup>'
        '<col class="c-lvl"><col class="c-pn"><col class="c-dwg">'
        '<col class="c-desc"><col class="c-qty"><col class="c-mat">'
        '</colgroup>'
        f'{head}<tbody>{body}</tbody></table>'
    )


def _tree_schematic_html(rows: list[dict]) -> str:
    """סכמה מקננת — רשימה אינדנטית עם צבעים לפי רמה."""
    if not rows:
        return ""
    parts = ['<ul class="tree">']
    for r in rows:
        lvl = max(0, min(int(r.get("level", 0)), 3))
        pn = _ltr(r.get("part_number", "—"))
        dwg = r.get("drawing_number", "")
        desc = r.get("description", "")
        qty = r.get("qty", "")
        mat = r.get("material", "")

        meta_bits = []
        if dwg:
            meta_bits.append(f'DWG: {_ltr(dwg)}')
        if desc:
            meta_bits.append(_h(desc))
        meta_html = (' · '.join(meta_bits)) if meta_bits else ''

        tail_bits = []
        if qty:
            tail_bits.append(f'<span class="tree-qty">×{_ltr(qty)}</span>')
        if mat:
            tail_bits.append(f'<span class="tree-mat">[{_h(mat)}]</span>')
        tail_html = ' '.join(tail_bits)

        # אינדנט ויזואלי באמצעות margin-right (RTL)
        margin = lvl * 18
        parts.append(
            f'<li class="lvl-{lvl}" style="margin-right:{margin}pt;">'
            f'<span class="tree-pn">{pn}</span> '
            f'<span class="tree-meta">{meta_html}</span> '
            f'{tail_html}'
            f'</li>'
        )
    parts.append('</ul>')
    return ''.join(parts)


def _tree_cover_html(n_drawings: int, n_rows: int) -> str:
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        "<h1>🌳 דוח עץ מוצר (מקוצר)</h1>"
        '<div class="meta-card">'
        f'<p><span class="muted">📅 תאריך הפקה:</span> <b>{ts}</b></p>'
        f'<p><span class="muted">📄 שרטוטים שהועלו:</span> <b>{n_drawings}</b> · '
        f'<span class="muted">פריטים בעץ:</span> <b>{n_rows}</b></p>'
        '</div>'
    )


def build_tree_pdf(
    drawings: list[dict],
    relationships: dict | None,
    out_path: Path,
) -> Path:
    """בונה דוח PDF מקוצר של עץ המוצר בלבד.

    כולל:
      • שער קצר
      • טבלת עץ (רמה, P/N, Drawing, תיאור, כמות, חומר)
      • סכמה ויזואלית מקננת
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = _flatten_tree_rows(drawings, relationships)

    page_w, page_h = fitz.paper_size("a4")
    margin = 36
    mediabox = fitz.Rect(0, 0, page_w, page_h)
    where = fitz.Rect(margin, margin, page_w - margin, page_h - margin)

    summary = ""
    rel_summary = ((relationships or {}).get("summary_he") or "").strip()
    if rel_summary:
        summary = f'<div class="summary">📋 {_h(rel_summary)}</div>'

    sections = [
        _wrap_rtl_tree(
            _tree_cover_html(len(drawings or []), len(rows))
            + summary
            + "<h2>📋 טבלת עץ מוצר</h2>"
            + _tree_table_html(rows)
        ),
        _wrap_rtl_tree(
            "<h2>🗂️ סכמת עץ מוצר</h2>"
            + _tree_schematic_html(rows)
        ),
    ]

    writer = fitz.DocumentWriter(str(out_path))
    try:
        for html_content in sections:
            story = fitz.Story(html=html_content)
            more = 1
            while more:
                dev = writer.begin_page(mediabox)
                more, _filled = story.place(where)
                story.draw(dev)
                writer.end_page()
    finally:
        writer.close()

    return out_path


def build_tree_excel(
    drawings: list[dict],
    relationships: dict | None,
    out_path: Path,
) -> Path:
    """שומר את עץ המוצר כקובץ Excel.

    גיליון 'Tree': עץ מוצר אמיתי בלבד + עמודות אב ישיר ונתיב.
    גיליון נוסף 'OverviewImage': פריטי בועיות מתמונת המכלול (אם קיימים).
    """
    import pandas as pd  # ייבוא עצל

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = _flatten_tree_rows(drawings, relationships)
    overview_rows = _flatten_overview_image_rows(drawings, relationships)
    idx = _build_drawing_index(drawings)

    excel_rows = []
    for r in rows:
        pn = (r.get("part_number") or "").strip()
        excel_rows.append({
            "רמה": r.get("level", 0),
            "אב ישיר (P/N)": r.get("parent_part_number", ""),
            "P/N": pn,
            "Drawing": r.get("drawing_number", ""),
            "תיאור": r.get("description", ""),
            "כמות": r.get("qty", ""),
            "חומר": r.get("material", ""),
            "נתיב": r.get("hierarchy_path", ""),
            "הועלה?": "כן" if pn and pn.upper() in idx else "לא",
        })

    cols = [
        "רמה", "אב ישיר (P/N)", "P/N", "Drawing", "תיאור",
        "כמות", "חומר", "נתיב", "הועלה?"
    ]
    df = pd.DataFrame(excel_rows, columns=cols)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Tree", index=False)
        ws = writer.sheets["Tree"]
        widths = {
            "A": 6, "B": 20, "C": 20, "D": 18, "E": 34,
            "F": 8, "G": 20, "H": 38, "I": 9,
        }
        for col, w in widths.items():
            ws.column_dimensions[col].width = w
        ws.sheet_view.rightToLeft = True

        if overview_rows:
            df_img = pd.DataFrame(overview_rows)
            df_img.to_excel(writer, sheet_name="OverviewImage", index=False)
            ws_img = writer.sheets["OverviewImage"]
            widths_img = {
                "A": 24, "B": 16, "C": 16, "D": 10,
                "E": 16, "F": 30, "G": 12, "H": 16,
                "I": 16, "J": 12, "K": 24, "L": 32,
                "M": 12, "N": 12,
            }
            for col, w in widths_img.items():
                ws_img.column_dimensions[col].width = w
            ws_img.sheet_view.rightToLeft = True

    return out_path


# ═══════════════════════════════════════════════════════════════
# Excel מקיף (Full) — גיליונות מרובים עם כל הנתונים שחולצו
# ═══════════════════════════════════════════════════════════════
def build_assembly_excel(
    drawings: list[dict],
    relationships: dict | None,
    out_path: Path,
    *,
    single_mode: bool = False,
) -> Path:
    """ייצוא Excel מקיף של כל הניתוח עם גיליונות מרובים.

    single_mode=True → מדלג על גיליונות 'עץ מוצר' ו-'עץ מתמונה'
    (מתאים לדוח של שרטוט בודד ללא היררכיה).
    """
    import pandas as pd  # ייבוא עצל

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    drawings = drawings or []

    # ─── גיליון 1: סיכום ───
    summary_rows = []
    for d in drawings:
        if not isinstance(d, dict):
            continue
        cost = (d.get("_cost_info") or {}).get("total_cost_usd", "")
        rw = d.get("raw_weight") or {}
        rw_qty = (rw.get("qty") or "") if isinstance(rw, dict) else ""
        rw_unit = (rw.get("unit") or "") if isinstance(rw, dict) else ""
        pw = d.get("part_weight") or {}
        pw_qty = (pw.get("qty") or "") if isinstance(pw, dict) else ""
        pw_unit = (pw.get("unit") or "") if isinstance(pw, dict) else ""
        summary_rows.append({
            "קובץ": d.get("source_filename", ""),
            "P/N": d.get("part_number", ""),
            "Drawing No.": d.get("drawing_number", ""),
            "Rev": d.get("revision", ""),
            "לקוח": d.get("customer", ""),
            "כותרת": d.get("title", ""),
            "חומר": d.get("material", ""),
            "כמות": d.get("quantity", ""),
            "CAT NO.": d.get("catalog_number", ""),
            "CAGE": d.get("cage_code", ""),
            "משקל גלם": f"{rw_qty} {rw_unit}".strip() if rw_qty or rw_unit else "",
            "משקל פריט": f"{pw_qty} {pw_unit}".strip() if pw_qty or pw_unit else "",
            "חומר חלופי": d.get("alternative_material", ""),
            "חומר מבוטל (formerly)": d.get("material_formerly", ""),
            "OS Level": d.get("os_level", ""),
            "תנאי סביבה": "; ".join(
                str(x) for x in (d.get("environment_requirements") or []) if x
            ),
            "תפקיד": d.get("assembly_role", ""),
            "BOM items": len(d.get("bom_items") or []),
            "עיבוד שבבי": len(d.get("machining_processes") or []),
            "ריתוך": len(d.get("welding_processes") or []),
            "טיפול חום": len(d.get("heat_treatment_processes") or []),
            "ציפויים": len(d.get("coating_processes") or []),
            "צביעות": len(d.get("painting_processes") or []),
            "NDT": len(d.get("ndt_processes") or []),
            "בדיקות": len(d.get("inspection_processes") or []),
            "תקנים": len(d.get("standards") or []),
            "OCR בשימוש": "כן" if d.get("_ocr_used") else "לא",
            "עלות (USD)": cost,
        })

    # ─── גיליון 2: עץ מוצר ───
    tree_rows_raw = _flatten_tree_rows(drawings, relationships)
    tree_image_rows = _flatten_overview_image_rows(drawings, relationships)
    idx = _build_drawing_index(drawings)
    tree_rows = []
    for r in tree_rows_raw:
        pn = (r.get("part_number") or "").strip()
        tree_rows.append({
            "רמה": r.get("level", 0),
            "אב ישיר (P/N)": r.get("parent_part_number", ""),
            "P/N": pn,
            "Drawing": r.get("drawing_number", ""),
            "תיאור": r.get("description", ""),
            "כמות": r.get("qty", ""),
            "חומר": r.get("material", ""),
            "נתיב": r.get("hierarchy_path", ""),
            "הועלה?": "כן" if pn and pn.upper() in idx else "לא",
        })

    # ─── גיליון 3: BOM ───
    bom_rows = []
    for d in drawings:
        parent_pn = d.get("part_number", "")
        parent_file = d.get("source_filename", "")
        for item in (d.get("bom_items") or []):
            if not isinstance(item, dict):
                continue
            bom_rows.append({
                "מכלול אב (P/N)": parent_pn,
                "קובץ אב": parent_file,
                "Item No.": item.get("item_no", ""),
                "P/N של פריט": item.get("part_number", ""),
                "תיאור": item.get("description", ""),
                "כמות": item.get("qty", ""),
            })

    # ─── גיליונות 4-8: תהליכים ───
    mach_rows = _flatten_process_rows(
        drawings, "machining_processes",
        ["step_no", "name_en", "name_he", "details"],
        ["שלב", "שם (EN)", "שם (HE)", "פרטים"],
    )
    weld_rows = _flatten_process_rows(
        drawings, "welding_processes",
        ["step_no", "name_en", "name_he", "details"],
        ["שלב", "שם (EN)", "שם (HE)", "פרטים"],
    )
    heat_rows = _flatten_process_rows(
        drawings, "heat_treatment_processes",
        ["step_no", "name_en", "name_he", "details"],
        ["שלב", "שם (EN)", "שם (HE)", "פרטים"],
    )
    coat_rows = _flatten_process_rows(
        drawings, "coating_processes",
        ["step_no", "type", "type_he", "name", "thickness", "standard", "rohs"],
        ["שלב", "סוג (EN)", "סוג (HE)", "שם מלא", "עובי", "תקן", "RoHS"],
    )
    paint_rows = _flatten_process_rows(
        drawings, "painting_processes",
        ["step_no", "type", "type_he", "name", "thickness", "standard", "rohs"],
        ["שלב", "סוג (EN)", "סוג (HE)", "שם מלא", "עובי", "תקן", "RoHS"],
    )
    ndt_rows = _flatten_process_rows(
        drawings, "ndt_processes",
        ["step_no", "name_en", "name_he", "details"],
        ["שלב", "שם (EN)", "שם (HE)", "פרטים"],
    )
    insp_rows = _flatten_process_rows(
        drawings, "inspection_processes",
        ["step_no", "name_en", "name_he", "details"],
        ["שלב", "שם (EN)", "שם (HE)", "פרטים"],
    )
    final_rows = _flatten_process_rows(
        drawings, "final_approval",
        ["step_no", "name_en", "name_he", "details"],
        ["שלב", "שם (EN)", "שם (HE)", "פרטים"],
    )

    # ─── גיליון 9: תקנים ───
    std_rows = []
    for d in drawings:
        for s in (d.get("standards") or []):
            std_rows.append({
                "קובץ": d.get("source_filename", ""),
                "P/N": d.get("part_number", ""),
                "תקן": s,
            })

    # ─── גיליון 10: תהליכים נוספים + אריזה + הערות ───
    extra_rows = []
    for d in drawings:
        for p in (d.get("additional_processes") or []):
            if isinstance(p, dict):
                step = p.get("step_no", "")
                details = p.get("details", "")
                detail_col = f"{step} | {details}".strip(" |") if step or details else ""
                extra_rows.append({
                    "קובץ": d.get("source_filename", ""),
                    "P/N": d.get("part_number", ""),
                    "סוג": "תהליך נוסף",
                    "EN": p.get("name_en", ""),
                    "HE": p.get("name_he", ""),
                    "פרטים": detail_col,
                })
        pkg = d.get("packaging_notes") or {}
        if isinstance(pkg, dict) and (pkg.get("en") or pkg.get("he")):
            extra_rows.append({
                "קובץ": d.get("source_filename", ""),
                "P/N": d.get("part_number", ""),
                "סוג": "אריזה",
                "EN": pkg.get("en", ""),
                "HE": pkg.get("he", ""),
                "פרטים": pkg.get("step_no", ""),
            })
        notes = (d.get("notes") or "").strip()
        if notes:
            extra_rows.append({
                "קובץ": d.get("source_filename", ""),
                "P/N": d.get("part_number", ""),
                "סוג": "הערות",
                "EN": "",
                "HE": notes,
                "פרטים": "",
            })

    # ─── גיליון 11: עלויות ───
    cost_rows = []
    total_cost = 0.0
    for d in drawings:
        ci = d.get("_cost_info") or {}
        if not ci:
            continue
        c = ci.get("total_cost_usd", 0) or 0
        try:
            total_cost += float(c)
        except (TypeError, ValueError):
            pass
        cost_rows.append({
            "קובץ": d.get("source_filename", ""),
            "P/N": d.get("part_number", ""),
            "Input tokens": ci.get("input_tokens", ""),
            "Output tokens": ci.get("output_tokens", ""),
            "עלות (USD)": ci.get("total_cost_usd", ""),
            "עלות (ILS)": ci.get("total_cost_ils", ""),
        })
    if cost_rows:
        cost_rows.append({
            "קובץ": "—— סה״כ ——",
            "P/N": "",
            "Input tokens": "",
            "Output tokens": "",
            "עלות (USD)": round(total_cost, 4),
            "עלות (ILS)": round(total_cost * 3.7, 2),
        })

    # ─── כתיבה ───
    sheets: list[tuple[str, list[dict], dict[str, int]]] = [
        ("סיכום", summary_rows, {"A": 38, "B": 18, "C": 18, "D": 6, "E": 14,
                                  "F": 32, "G": 8, "H": 16, "I": 11, "J": 12,
                                  "K": 10, "L": 10, "M": 10, "N": 9, "O": 12,
                                  "P": 12}),
    ]
    if not single_mode:
        sheets.append(("עץ מוצר", tree_rows, {
            "A": 6, "B": 20, "C": 20, "D": 18, "E": 34,
            "F": 8, "G": 24, "H": 38, "I": 9,
        }))
    sheets.extend([
        ("BOM", bom_rows, {"A": 22, "B": 38, "C": 10, "D": 22, "E": 38, "F": 8}),
        ("עיבוד שבבי", mach_rows, {"A": 38, "B": 18, "C": 8, "D": 26,
                                    "E": 26, "F": 50}),
        ("ריתוך", weld_rows, {"A": 38, "B": 18, "C": 8, "D": 26,
                                "E": 26, "F": 50}),
        ("טיפול חום", heat_rows, {"A": 38, "B": 18, "C": 8, "D": 26,
                                    "E": 26, "F": 50}),
        ("ציפויים", coat_rows, {"A": 38, "B": 18, "C": 8, "D": 18, "E": 18,
                                "F": 32, "G": 12, "H": 28, "I": 8}),
        ("צביעה", paint_rows, {"A": 38, "B": 18, "C": 8, "D": 18, "E": 18,
                                "F": 32, "G": 12, "H": 28, "I": 8}),
        ("NDT", ndt_rows, {"A": 38, "B": 18, "C": 8, "D": 26,
                            "E": 26, "F": 50}),
        ("בדיקות", insp_rows, {"A": 38, "B": 18, "C": 8, "D": 26,
                                "E": 26, "F": 50}),
        ("אישור סופי", final_rows, {"A": 38, "B": 18, "C": 8, "D": 26,
                                     "E": 26, "F": 50}),
        ("תקנים", std_rows, {"A": 38, "B": 18, "C": 50}),
        ("תהליכים נוספים", extra_rows, {"A": 38, "B": 18, "C": 12, "D": 26,
                                         "E": 50, "F": 16}),
        ("עלויות", cost_rows, {"A": 38, "B": 22, "C": 14, "D": 14, "E": 12,
                                "F": 12}),
    ])
    if not single_mode:
        sheets.append(("עץ מתמונה", tree_image_rows, {
            "A": 24, "B": 16, "C": 16, "D": 10,
            "E": 16, "F": 30, "G": 12, "H": 16,
            "I": 16, "J": 12, "K": 24, "L": 32,
            "M": 12, "N": 12,
        }))

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet_name, rows, widths in sheets:
            if not rows:
                df = pd.DataFrame([{"מידע": "(אין נתונים בגיליון זה)"}])
            else:
                df = pd.DataFrame(rows)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]
            for col, w in widths.items():
                ws.column_dimensions[col].width = w
            ws.sheet_view.rightToLeft = True

    return out_path


def _flatten_process_rows(
    drawings: list[dict],
    field: str,
    keys: list[str],
    headers_he: list[str],
) -> list[dict]:
    """משטח שדה רשימה (כמו machining_processes) לשורות שטוחות עם הקשר לקובץ/PN."""
    rows = []
    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        items = d.get(field) or []
        # לפעמים final_approval הוא dict יחיד
        if isinstance(items, dict):
            items = [items]
        for it in items:
            if not isinstance(it, dict):
                continue
            row = {
                "קובץ": d.get("source_filename", ""),
                "P/N": d.get("part_number", ""),
            }
            for k, h in zip(keys, headers_he):
                v = it.get(k, "")
                if isinstance(v, bool):
                    v = "כן" if v else "לא"
                row[h] = v
            rows.append(row)
    return rows
