"""
השוואה מקיפה: AI extraction (v18 cache) מול PDF native text + Tesseract OCR.
משמש כ-ground truth מכיוון שאין לנו תשובה ידנית מאומתת.
"""
import sys
import io
import json
import re
import hashlib
import os
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import fitz
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
from PIL import Image


def get_ground_truth(pdf_path: str) -> str:
    """PDF native text + OCR (uppercase, combined)."""
    doc = fitz.open(pdf_path)
    native = " | ".join(page.get_text() for page in doc).strip()
    ocr_parts = []
    for page in doc:
        try:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.pil_tobytes(format="PNG")))
            ocr_parts.append(pytesseract.image_to_string(img, lang="eng+heb"))
        except Exception:
            pass
    return (native + "\n" + "\n".join(ocr_parts)).upper()


def compact(s: str) -> str:
    return re.sub(r"[\s\-\.,/]", "", s.upper())


files_md5 = {}
for f in sorted(os.listdir("draws/new")):
    p = os.path.join("draws/new", f)
    h = hashlib.md5()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            h.update(chunk)
    files_md5[h.hexdigest()] = (f, p)

cache_by_md5 = {}
for cf in Path("output/.cache").glob("v18_*assembly.json"):
    parts = cf.stem.split("_")
    if len(parts) >= 3:
        cache_by_md5[parts[2]] = cf

issues = {
    "pn_not_in_text": [],
    "customer_empty_but_clue": [],
    "cage_empty": [],
    "material_empty": [],
    "title_empty": [],
    "revisions_empty": [],
    "ocr_false": [],
    "suspicious_standards": [],
    "possible_hallucination": [],
    "missing_serviceability": [],
    "missing_packing": [],
    "misclass_test_method_as_std": [],
    "standards_is_generic": [],
    "spec_prefix_issue": [],
    "duplicates": [],
}
totals = {"cost": 0.0, "warnings": 0, "stds_susp_unique": set()}
per_file = []

seen_md5 = set()
for md5, (fname, pdf_path) in files_md5.items():
    cf = cache_by_md5.get(md5)
    if not cf:
        continue
    if md5 in seen_md5:
        issues["duplicates"].append(fname)
        continue
    seen_md5.add(md5)

    with open(cf, encoding="utf-8") as fp:
        ai = json.load(fp)

    gt = get_ground_truth(pdf_path)
    gt_compact = compact(gt)

    pn = ai.get("part_number") or ""
    rev = ai.get("revision") or ""
    cust = ai.get("customer") or ""
    mat = ai.get("material") or ""
    cage = ai.get("cage_code") or ""
    title = ai.get("title") or ""
    stds = ai.get("standards") or []
    revs = ai.get("revisions_history") or []
    warns = ai.get("_pn_warnings") or []
    cost = (ai.get("_cost_info") or {}).get("total_cost_usd", 0)

    rec = {
        "file": fname,
        "pn": pn,
        "rev": rev,
        "customer": cust,
        "cage": cage,
        "material": mat[:60],
        "cost": cost,
        "warnings": len(warns),
        "ocr": ai.get("_ocr_used", False),
        "stds_count": len(stds),
        "role": ai.get("assembly_role", ""),
    }
    totals["cost"] += cost
    totals["warnings"] += len(warns)
    per_file.append(rec)

    if pn and not (compact(pn) and compact(pn) in gt_compact):
        issues["pn_not_in_text"].append(f"{fname}: AI={pn}")
    if not cust:
        clue = ""
        for c in ["RAFAEL", "ELBIT", "ELOP", "BIRD", "IAI", "ELTA",
                  "NIR-OR", "SCHNEIDER", "LAOR", "DAKRIM"]:
            if c in gt:
                clue = c
                break
        issues["customer_empty_but_clue"].append(f"{fname} [clue: {clue or '?'}]")
    if not cage:
        issues["cage_empty"].append(fname)
    if not mat:
        issues["material_empty"].append(fname)
    if not title:
        issues["title_empty"].append(fname)
    if not ai.get("_ocr_used", False):
        issues["ocr_false"].append(fname)
    if not revs:
        issues["revisions_empty"].append(fname)

    for w in warns:
        if "SUSPICIOUS_STANDARD" in w:
            m = re.search(r"'([^']+)'", w)
            if m:
                issues["suspicious_standards"].append((fname, m.group(1)))
                totals["stds_susp_unique"].add(m.group(1))
        if "POSSIBLE_HALLUCINATION" in w:
            m = re.search(r"'([^']+)'", w)
            if m:
                issues["possible_hallucination"].append((fname, m.group(1)))
        if "MISSING_SERVICEABILITY_TAG" in w:
            issues["missing_serviceability"].append(fname)
        if "MISSING_PACKING" in w and "NO_PACKING" not in w:
            issues["missing_packing"].append(fname)

    test_methods = {"GTAW", "GMAW", "TIG", "MIG", "WPS", "VT", "PT", "MT",
                    "UT", "RT", "PAINTING", "MARKING", "WELDING"}
    for s in stds:
        first = s.upper().strip().split()[0] if s else ""
        if first in test_methods:
            issues["misclass_test_method_as_std"].append((fname, s))
        if s.upper().strip() == "ISO STANDARDS":
            issues["standards_is_generic"].append((fname, s))
        if re.search(r"PS[\s\-]\s+", s) or re.search(r"\s+PS[\s\-]", s):
            issues["spec_prefix_issue"].append((fname, s))

print("=" * 110)
print(f"SUMMARY — {len(per_file)} unique drawings")
print("=" * 110)
print(f'{"File":<40s} {"P/N":<22s} {"Rev":<5s} {"Customer":<20s} {"CAGE":<6s} {"Cost":<7s} {"W":<3s}')
print("-" * 110)
for r in per_file:
    fn = r["file"][:38]
    pn = r["pn"][:20]
    c = r["customer"][:18]
    cage = r["cage"][:4] if r["cage"] else "-"
    cost_str = f"${r['cost']:.3f}"
    print(f'{fn:<40s} {pn:<22s} {r["rev"]:<5s} {c:<20s} {cage:<6s} {cost_str:<7s} {r["warnings"]}')

print()
print("=" * 110)
print("AGGREGATED ISSUES")
print("=" * 110)
print(f'\nTotal cost: ${totals["cost"]:.3f}')
print(f'Total warnings: {totals["warnings"]}')
print(f'Unique suspicious standards: {len(totals["stds_susp_unique"])}')

for k, v in issues.items():
    if isinstance(v, list) and v:
        print(f"\n[{k}] ({len(v)}):")
        for item in v[:12]:
            print(f"  - {item}")
        if len(v) > 12:
            print(f"  ... +{len(v) - 12} more")

print("\n--- Unique SUSPICIOUS_STANDARD values ---")
for s in sorted(totals["stds_susp_unique"]):
    print(f'  "{s}"')
