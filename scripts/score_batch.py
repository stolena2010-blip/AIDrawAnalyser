"""
Quality scoring for the 10 most recent v24 cache entries.
Score is on a 0-100 scale per drawing, with weighted breakdown:
  - Identity (P/N, DWG, Customer, Title): 25 pts
  - Material+Material qualifiers: 15 pts
  - Standards quality (real vs noise): 15 pts
  - Processes coverage (machining/coating/painting/inspection/etc.): 25 pts
  - Revisions+CAGE+OCR usage: 10 pts
  - Warnings/Hallucination handling: 10 pts
"""
import io
import json
import sys
import re
import hashlib
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Find the 10 most recent v24 caches
v24_caches = sorted(
    Path("output/.cache").glob("v24_*assembly.json"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)[:10]

# Match to source filenames
all_drawings = {}
for folder in ["draws", "draws/1", "draws/new", "draws/new2", "draws/new3", "draws/NEW4"]:
    p = Path(folder)
    if not p.exists():
        continue
    for f in p.iterdir():
        if f.is_file() and f.suffix.lower() == ".pdf":
            h = hashlib.md5()
            with open(f, "rb") as fp:
                for chunk in iter(lambda: fp.read(8192), b""):
                    h.update(chunk)
            all_drawings[h.hexdigest()] = f.name


def score_drawing(d: dict, source_name: str = "") -> dict:
    """Score a single drawing 0-100."""
    breakdown = {}

    # ─── 1. Identity (25 pts) ─────────────────────────────────
    pts = 0
    if (d.get("part_number") or "").strip():
        pts += 6
        # bonus if matches filename
        compact = lambda s: re.sub(r"[\s\-\.,/_]", "", (s or "").upper())
        if compact(d.get("part_number")) in compact(source_name):
            pts += 3
    if (d.get("drawing_number") or "").strip():
        pts += 4
    if (d.get("customer") or "").strip():
        pts += 6
    if (d.get("title") or "").strip():
        pts += 3
    if (d.get("revision") or "").strip():
        pts += 3
    breakdown["identity"] = (pts, 25)

    # ─── 2. Material (15 pts) ─────────────────────────────────
    pts = 0
    mat = (d.get("material") or "").strip()
    if mat:
        pts += 8
        if len(mat) > 20:  # detailed material with spec
            pts += 4
        if re.search(r"\b(?:AMS|ASTM|MIL|QQ|SAE|EN)[\s\-\d]", mat, re.IGNORECASE):
            pts += 3  # material with explicit spec
    breakdown["material"] = (pts, 15)

    # ─── 3. Standards quality (15 pts) ────────────────────────
    pts = 0
    stds = d.get("standards") or []
    if stds:
        pts += 5
        # Check what fraction are real vs noise
        warns = d.get("_pn_warnings") or []
        sus_count = sum(1 for w in warns if "SUSPICIOUS_STANDARD" in w)
        halluc_count = sum(1 for w in warns if "POSSIBLE_HALLUCINATION" in w)
        clean = len(stds) - sus_count - halluc_count
        if len(stds) > 0:
            quality_ratio = max(0, clean) / len(stds)
            pts += int(10 * quality_ratio)
    breakdown["standards"] = (pts, 15)

    # ─── 4. Processes coverage (25 pts) ───────────────────────
    pts = 0
    proc_categories = [
        ("machining_processes", 4),
        ("welding_processes", 2),
        ("heat_treatment_processes", 2),
        ("coating_processes", 4),
        ("painting_processes", 3),
        ("inspection_processes", 3),
        ("final_approval", 3),
        ("additional_processes", 4),
    ]
    role = (d.get("assembly_role") or "").upper()
    for key, weight in proc_categories:
        items = d.get(key) or []
        if items:
            pts += weight
        elif role == "ASSEMBLY" and key in ("machining_processes", "coating_processes",
                                              "painting_processes"):
            # Assemblies often don't have direct processes — penalize less
            pts += weight // 2
    # Cap at 25
    pts = min(pts, 25)
    breakdown["processes"] = (pts, 25)

    # ─── 5. Revisions + CAGE + OCR (10 pts) ───────────────────
    pts = 0
    if d.get("_ocr_used", False):
        pts += 3
    if d.get("revisions_history"):
        pts += 3
        if len(d.get("revisions_history") or []) > 1:
            pts += 1  # full history bonus
    if (d.get("cage_code") or "").strip():
        pts += 3
    breakdown["meta"] = (pts, 10)

    # ─── 6. Warnings (10 pts) ─────────────────────────────────
    # 10 if 0 HIGH warnings, scaling down per HIGH
    pts = 10
    warns = d.get("_pn_warnings") or []
    high_count = sum(1 for w in warns if "[HIGH]" in w)
    pts = max(0, 10 - 2 * high_count)
    breakdown["warnings"] = (pts, 10)

    total = sum(p for p, _ in breakdown.values())
    return {"total": total, "breakdown": breakdown}


# ─── Score all 10 ───────────────────────────────────────────────
print("=" * 105)
print("QUALITY SCORE — 10 MOST RECENT DRAWINGS (v24)")
print("=" * 105)
print(f'{"#":<3s} {"Drawing":<42s} {"Total":<7s} {"ID":<7s} {"Mat":<7s} {"Std":<7s} {"Proc":<7s} {"Meta":<7s} {"Warn":<7s}')
print("-" * 105)

scores = []
for i, cf in enumerate(v24_caches, 1):
    md5 = cf.stem.split("_")[2]
    source = all_drawings.get(md5, f"(unknown:{md5[:8]})")
    with open(cf, encoding="utf-8") as fp:
        d = json.load(fp)
    s = score_drawing(d, source)
    scores.append((source, s, d))
    fmt_breakdown = lambda key: f"{s['breakdown'][key][0]}/{s['breakdown'][key][1]}"
    print(f'{i:<3d} {source[:40]:<42s} {s["total"]:<3d}/100 '
          f'{fmt_breakdown("identity"):<7s} {fmt_breakdown("material"):<7s} '
          f'{fmt_breakdown("standards"):<7s} {fmt_breakdown("processes"):<7s} '
          f'{fmt_breakdown("meta"):<7s} {fmt_breakdown("warnings"):<7s}')

print("-" * 105)
totals = [s[1]["total"] for s in scores]
avg = sum(totals) / len(totals)
print(f'AVERAGE: {avg:.1f}/100')
print(f'MEDIAN:  {sorted(totals)[len(totals)//2]}/100')
print(f'BEST:    {max(totals)}/100')
print(f'WORST:   {min(totals)}/100')

print()
print("=" * 105)
print("DETAILS PER DRAWING")
print("=" * 105)
for fname, s, d in scores:
    print(f"\n📄 {fname}")
    print(f"   Score: {s['total']}/100")
    print(f"   P/N: {d.get('part_number','-')!r}  |  Customer: {d.get('customer','-')!r}")
    print(f"   Material: {(d.get('material','') or '-')[:80]!r}")
    role = d.get("assembly_role", "-")
    bom_n = len(d.get("bom_items") or [])
    revs_n = len(d.get("revisions_history") or [])
    cage = d.get("cage_code") or "-"
    print(f"   Role: {role}  CAGE: {cage}  BOM: {bom_n}  Revisions: {revs_n}")
    n_proc = sum(len(d.get(k, []) or []) for k in [
        "machining_processes", "welding_processes", "heat_treatment_processes",
        "coating_processes", "painting_processes", "inspection_processes",
        "final_approval", "additional_processes"
    ])
    n_std = len(d.get("standards") or [])
    n_warns = len(d.get("_pn_warnings") or [])
    high_w = sum(1 for w in (d.get("_pn_warnings") or []) if "[HIGH]" in w)
    print(f"   Processes: {n_proc}  Standards: {n_std}  Warnings: {n_warns} ({high_w} HIGH)")
