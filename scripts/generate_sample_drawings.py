"""
מייצר 3 שרטוטי PDF sanitized לתיקיית sample_drawings/.

המטרה: לחסוך עבודה ידנית של עריכת PDF להסרת שמות לקוחות מ-3 שרטוטים אמיתיים.
במקום זה — מייצרים PDF גנרי עם תוכן בדיוני (לקוח "ACME Aerospace Inc.")
שמדמה מבנה של title block + production routing chart + BOM.

הקבצים שייוצרו:
  sample_drawings/01_simple_part.pdf       — חלק פשוט (P/N + חומר + תקנים)
  sample_drawings/02_complex_part.pdf      — חלק מורכב (BOM + ציפויים + צביעות + תקנים)
  sample_drawings/03_assembly_overview.pdf — assembly עם BOM של 5 פריטים

הרצה:
    python scripts/generate_sample_drawings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    print("❌ reportlab לא מותקן. הרצי: pip install reportlab")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sample_drawings"


def _title_block(title: str, pn: str, rev: str, customer: str = "ACME Aerospace Inc.",
                 cage: str = "AC001") -> Table:
    """Title block גנרי בסגנון תעשייתי."""
    data = [
        ["TITLE:", title, "P.N.:", pn],
        ["CUSTOMER:", customer, "REV:", rev],
        ["CAGE CODE:", cage, "DRAWING NO.:", pn],
        ["SCALE:", "1:1", "SHEET:", "1 OF 1"],
    ]
    t = Table(data, colWidths=[3 * cm, 8 * cm, 3 * cm, 4 * cm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("BACKGROUND", (2, 0), (2, -1), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _section_header(text: str, styles) -> Paragraph:
    return Paragraph(
        f'<font size="11"><b>{text}</b></font>', styles["Normal"]
    )


def _routing_chart(rows: list[tuple[str, str, str]]) -> Table:
    """Production routing chart — STEP / DESCRIPTION / SPEC."""
    header = ["NO.", "DESCRIPTION", "SPEC"]
    data = [header] + [list(r) for r in rows]
    t = Table(data, colWidths=[1.5 * cm, 11 * cm, 5 * cm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _bom_table(items: list[tuple[str, str, str, str]]) -> Table:
    """BOM table — Item / P/N / Description / Qty."""
    header = ["ITEM", "P/N", "DESCRIPTION", "QTY"]
    data = [header] + [list(r) for r in items]
    t = Table(data, colWidths=[1.5 * cm, 3.5 * cm, 11 * cm, 1.5 * cm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
    ]))
    return t


# ─────────────────────────────────────────────────────────────────
# DRAWING 1 — Simple part (mounting bracket)
# ─────────────────────────────────────────────────────────────────
def build_simple_part(out_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=1 * cm, bottomMargin=1 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            '<font size="14"><b>SAMPLE DRAWING — DEMO ONLY</b></font>',
            styles["Title"]),
        Spacer(1, 0.4 * cm),
        _title_block(
            title="MOUNTING BRACKET — UPPER",
            pn="AC-12345", rev="A",
        ),
        Spacer(1, 0.5 * cm),
        _section_header("MATERIAL", styles),
        Paragraph(
            "ALUMINUM ALLOY 6061-T6 PER AMS-QQ-A-250/11",
            styles["Normal"]),
        Spacer(1, 0.3 * cm),
        _section_header("PRODUCTION ROUTING CHART", styles),
        _routing_chart([
            ("10", "ROUGH MILL — STOCK 60×80×12 mm", "AC-PROC-001"),
            ("20", "FINISH MILL — Ra 1.6 microns", "AC-PROC-001"),
            ("30", "DEBURR — Manual, break sharp edges 0.2 max", "—"),
            ("40", "CHROMATE CONVERSION — Class 1A clear", "MIL-DTL-5541F"),
            ("50", "VISUAL INSPECTION — 100%", "ASTM E1417"),
            ("60", "QA STAMP + SERVICEABILITY TAG", "—"),
        ]),
        Spacer(1, 0.4 * cm),
        _section_header("NOTES", styles),
        Paragraph(
            "1. ALL DIMENSIONS IN MILLIMETERS UNLESS OTHERWISE SPECIFIED.<br/>"
            "2. BREAK ALL SHARP EDGES 0.2 MAX.<br/>"
            "3. SURFACE FINISH 1.6 MICRON Ra UNLESS OTHERWISE SPECIFIED.<br/>"
            "4. PACK IN INDIVIDUAL ESD BAG.",
            styles["Normal"]),
    ]
    doc.build(story)


# ─────────────────────────────────────────────────────────────────
# DRAWING 2 — Complex part (with painting + multiple standards)
# ─────────────────────────────────────────────────────────────────
def build_complex_part(out_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=1 * cm, bottomMargin=1 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            '<font size="14"><b>SAMPLE DRAWING — DEMO ONLY</b></font>',
            styles["Title"]),
        Spacer(1, 0.4 * cm),
        _title_block(
            title="CAMERA HOUSING ASSEMBLY",
            pn="AC-23456", rev="C",
        ),
        Spacer(1, 0.4 * cm),
        _section_header("MATERIAL", styles),
        Paragraph(
            "ALUMINUM ALLOY 7075-T651 PER AMS-QQ-A-250/12<br/>"
            "ALTERNATIVE: ALUMINUM ALLOY 6061-T6 PER AMS-QQ-A-250/11",
            styles["Normal"]),
        Spacer(1, 0.3 * cm),
        _section_header("PRODUCTION ROUTING CHART", styles),
        _routing_chart([
            ("10", "CNC MILL — 5-axis", "AC-PROC-002"),
            ("20", "TURN — OD .500\" tolerance ±0.0005", "AC-PROC-005"),
            ("30", "DRILL & TAP — M5×0.8 ×4 places", "—"),
            ("40", "DEBURR + CLEAN", "—"),
            ("50", "BLACK ANODIZE TYPE II CLASS 2", "MIL-A-8625"),
            ("60", "EPOXY PRIMER 25-30 microns", "MIL-PRF-23377K"),
            ("70", "POLYURETHANE TOPCOAT — RAL 7035 Light Grey", "MIL-PRF-85285E"),
            ("80", "FLUORESCENT PENETRANT INSPECTION — Type I", "ASTM E1417"),
            ("90", "DIMENSIONAL INSPECTION — CMM REPORT", "—"),
            ("100", "FINAL APPROVAL — QA STAMP", "—"),
            ("110", "ESD PACKAGING — Individual bag", "—"),
        ]),
        Spacer(1, 0.4 * cm),
        _section_header("NOTES", styles),
        Paragraph(
            "1. ALL DIMENSIONS IN MILLIMETERS.<br/>"
            "2. PAINT THICKNESS — TOTAL 50-75 microns.<br/>"
            "3. RoHS COMPLIANT.<br/>"
            "4. ESD HANDLING REQUIRED — CLEAN ROOM CLASS 100,000.<br/>"
            "5. TEMPERATURE RANGE -40°C TO +85°C OPERATIONAL.",
            styles["Normal"]),
    ]
    doc.build(story)


# ─────────────────────────────────────────────────────────────────
# DRAWING 3 — Assembly overview with BOM
# ─────────────────────────────────────────────────────────────────
def build_assembly_drawing(out_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=1 * cm, bottomMargin=1 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            '<font size="14"><b>SAMPLE ASSEMBLY DRAWING — DEMO ONLY</b></font>',
            styles["Title"]),
        Spacer(1, 0.4 * cm),
        _title_block(
            title="CAMERA MOUNT SYSTEM — TOP LEVEL ASSEMBLY",
            pn="ACME-MOUNT-001", rev="B",
        ),
        Spacer(1, 0.4 * cm),
        _section_header("ASSEMBLY ROLE", styles),
        Paragraph(
            "ASSEMBLY — Top-level. See BOM below for sub-components.",
            styles["Normal"]),
        Spacer(1, 0.3 * cm),
        _section_header("BILL OF MATERIALS (BOM)", styles),
        _bom_table([
            ("1", "AC-12345", "MOUNTING BRACKET (UPPER) — Aluminum 6061-T6", "1"),
            ("2", "AC-12346", "MOUNTING PLATE (LOWER) — Stainless Steel 316L", "1"),
            ("3", "AC-23456", "CAMERA HOUSING ASSEMBLY — Aluminum 7075", "1"),
            ("4", "AC-FAS-M5x20", "M5x20 HEX SOCKET CAP SCREW — Steel zinc", "4"),
            ("5", "AC-FAS-M5W", "M5 LOCK WASHER — Stainless 316", "4"),
        ]),
        Spacer(1, 0.4 * cm),
        _section_header("PROCESS REQUIREMENTS", styles),
        _routing_chart([
            ("10", "ASSEMBLE BRACKETS PER BOM ITEMS 1-2", "—"),
            ("20", "TORQUE FASTENERS TO 5.5 N·m ±0.5", "AC-TORQ-M5"),
            ("30", "VERIFY GROUNDING CONTINUITY — < 2.5 ohm", "MIL-STD-1542"),
            ("40", "INSTALL CAMERA HOUSING (BOM ITEM 3)", "—"),
            ("50", "FINAL INSPECTION — DIMENSIONAL + FUNCTIONAL", "—"),
            ("60", "PACKAGING — ESD BAG + FOAM INSERT", "—"),
        ]),
        Spacer(1, 0.4 * cm),
        _section_header("NOTES", styles),
        Paragraph(
            "1. THIS IS A SAMPLE / DEMO DRAWING — DO NOT USE FOR PRODUCTION.<br/>"
            "2. ALL P/Ns ARE FICTIONAL — NO REAL CUSTOMER DATA.<br/>"
            "3. FOR DEMONSTRATION OF AIDrawAnalyser CAPABILITIES.<br/>"
            "4. ASSEMBLY MUST PASS AS9100 REV D INSPECTION.",
            styles["Normal"]),
    ]
    doc.build(story)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────
def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n📐 Generating sample drawings to: {OUT_DIR}\n")

    drawings = [
        ("01_simple_part.pdf", build_simple_part, "Simple Part — AC-12345 Mounting Bracket"),
        ("02_complex_part.pdf", build_complex_part, "Complex Part — AC-23456 Camera Housing (paint+anodize+NDT)"),
        ("03_assembly_overview.pdf", build_assembly_drawing, "Assembly — ACME-MOUNT-001 (5 BOM items)"),
    ]

    for filename, builder, description in drawings:
        path = OUT_DIR / filename
        try:
            builder(path)
            size_kb = path.stat().st_size / 1024
            print(f"  ✅ {filename}  —  {description}")
            print(f"     ({size_kb:.1f} KB)\n")
        except Exception as exc:
            print(f"  ❌ {filename} failed: {exc}\n")
            return 1

    print(f"🎉 Done. Sample drawings ready in {OUT_DIR}/")
    print("\n💡 Use these for sales demos — fully sanitized, no real customer IP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
