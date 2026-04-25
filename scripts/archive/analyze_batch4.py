"""
Analysis of Batch 4 (draws/NEW4/) — 21 drawings tested with v23.
"""
import io
import json
import sys
import re
import hashlib
import os
from pathlib import Path
from collections import Counter

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

folder = "draws/NEW4"
files_md5 = {}
for f in sorted(os.listdir(folder)):
    h = hashlib.md5()
    with open(os.path.join(folder, f), "rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            h.update(chunk)
    files_md5[h.hexdigest()] = f

cache_by_md5 = {cf.stem.split("_")[2]: cf
                for cf in Path("output/.cache").glob("v23_*assembly.json")
                if len(cf.stem.split("_")) >= 3}


def compact(s):
    return re.sub(r"[\s\-\.,/_]", "", (s or "").upper())


rows = []
agg = {"cost": 0.0, "warnings": 0, "sus": 0, "ocr": 0,
       "cage_set": 0, "rev_set": 0, "bom_items": 0, "rev_entries": 0,
       "material_set": 0, "title_set": 0, "customer_set": 0,
       "pn_in_filename": 0, "prefix_mismatch": 0}
customers = Counter()
sus_vals = Counter()
warning_types = Counter()
pn_mismatches = []

seen = set()
for md5, fname in sorted(files_md5.items(), key=lambda x: x[1]):
    if md5 in seen:
        continue
    seen.add(md5)
    cf = cache_by_md5.get(md5)
    if not cf:
        print(f"NO CACHE for {fname}")
        continue
    with open(cf, encoding="utf-8") as fp:
        d = json.load(fp)

    pn = d.get("part_number") or ""
    rev = d.get("revision") or ""
    cust = d.get("customer") or ""
    cage = d.get("cage_code") or ""
    mat = d.get("material") or ""
    title = d.get("title") or ""
    role = d.get("assembly_role") or ""
    bom = d.get("bom_items") or []
    revs = d.get("revisions_history") or []
    stds = d.get("standards") or []
    warns = d.get("_pn_warnings") or []
    cost = (d.get("_cost_info") or {}).get("total_cost_usd", 0)
    ocr = d.get("_ocr_used", False)

    pn_in_fname = compact(pn) in compact(fname) if pn else False

    rows.append({
        "file": fname[:40], "pn": pn[:22], "rev": rev[:5], "cust": cust[:25],
        "cage": cage[:5] if cage else "-", "bom": len(bom), "revs_n": len(revs),
        "stds_n": len(stds), "w": len(warns), "cost": cost, "role": role[:12],
        "pn_match": "v" if pn_in_fname else "!",
    })
    agg["cost"] += cost
    agg["warnings"] += len(warns)
    agg["ocr"] += int(bool(ocr))
    if cage: agg["cage_set"] += 1
    if revs: agg["rev_set"] += 1
    if mat: agg["material_set"] += 1
    if title: agg["title_set"] += 1
    if cust: agg["customer_set"] += 1
    if pn_in_fname: agg["pn_in_filename"] += 1
    agg["bom_items"] += len(bom)
    agg["rev_entries"] += len(revs)
    if cust: customers[cust] += 1
    for w in warns:
        m = re.match(r"\[([^\]]+)\]\[([^\]]+)\]", w)
        if m:
            warning_types[m.group(2)] += 1
            if m.group(2) == "CUSTOMER_PREFIX_MISMATCH":
                agg["prefix_mismatch"] += 1
        if "SUSPICIOUS_STANDARD" in w:
            agg["sus"] += 1
            mv = re.search(r"'([^']+)'", w)
            if mv:
                sus_vals[mv.group(1)] += 1

    if not pn_in_fname and pn:
        pn_mismatches.append((fname, pn))

n = len(rows)
print(f"=" * 115)
print(f"BATCH 4: NEW4/ ({n} drawings, v23)")
print(f"=" * 115)
hdr = f'{"File":<42s} {"P/N":<23s} {"v":<2s} {"Rev":<5s} {"Customer":<26s} {"CAGE":<6s} {"BOM":<4s} {"R":<3s} {"W":<3s} {"$":<6s}'
print(hdr)
print("-" * 115)
for r in rows:
    cost_s = f"${r['cost']:.3f}"
    print(f'{r["file"]:<42s} {r["pn"]:<23s} {r["pn_match"]:<2s} {r["rev"]:<5s} {r["cust"]:<26s} {r["cage"]:<6s} {r["bom"]:<4} {r["revs_n"]:<3} {r["w"]:<3} {cost_s}')

print()
print(f"=" * 115)
print("AGGREGATES")
print(f"=" * 115)
print(f"Drawings:             {n}")
print(f"OCR used:             {agg['ocr']}/{n}  ({100*agg['ocr']/n:.0f}%)")
print(f"Customer set:         {agg['customer_set']}/{n}  ({100*agg['customer_set']/n:.0f}%)")
print(f"CAGE set:             {agg['cage_set']}/{n}  ({100*agg['cage_set']/n:.0f}%)")
print(f"Material set:         {agg['material_set']}/{n}  ({100*agg['material_set']/n:.0f}%)")
print(f"Title set:            {agg['title_set']}/{n}  ({100*agg['title_set']/n:.0f}%)")
print(f"Revisions set:        {agg['rev_set']}/{n}  ({100*agg['rev_set']/n:.0f}%)  [{agg['rev_entries']} entries]")
print(f"P/N matches filename: {agg['pn_in_filename']}/{n}  ({100*agg['pn_in_filename']/n:.0f}%)")
print(f"BOM items total:      {agg['bom_items']}")
print(f"Warnings total:       {agg['warnings']}")
print(f"SUSPICIOUS_STANDARD:  {agg['sus']}")
print(f"CUSTOMER_PREFIX_MISMATCH: {agg['prefix_mismatch']}")
print(f"Total cost:           ${agg['cost']:.3f}  (~NIS {agg['cost']*3.7:.2f})")
print(f"Avg cost/drawing:     ${agg['cost']/max(n,1):.4f}")
print()
print("Warning types:")
for t, c in warning_types.most_common():
    print(f"  {c:>3}x  {t}")

print()
print(f"Customers ({len(customers)} unique):")
for c, cnt in customers.most_common():
    print(f"  {cnt}x  {c}")

if pn_mismatches:
    print()
    print(f"P/N does not match filename ({len(pn_mismatches)}):")
    for fname, pn in pn_mismatches:
        print(f"  {fname:<42s} -> {pn}")

if sus_vals:
    print()
    print("Remaining SUSPICIOUS_STANDARD values:")
    for v, c in sus_vals.most_common():
        print(f"  {c}x  {v!r}")
