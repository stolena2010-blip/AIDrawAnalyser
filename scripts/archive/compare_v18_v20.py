"""
השוואה ישירה v18 (אחרי Easy Wins) ↔ v20 (אחרי Medium Effort) על 20 שרטוטי new/.
בודק שיפור ב: P/N, Material, Revisions, BOM, Customer, Standards, Warnings.
"""
import io
import json
import sys
import re
import hashlib
import os
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

# MD5 → filename
files_md5 = {}
for f in sorted(os.listdir("draws/new")):
    h = hashlib.md5()
    with open(os.path.join("draws/new", f), "rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            h.update(chunk)
    files_md5[h.hexdigest()] = f

v18_cache, v20_cache = {}, {}
for cf in Path("output/.cache").glob("*_assembly.json"):
    parts = cf.stem.split("_")
    if len(parts) < 3:
        continue
    ver, md5 = parts[0], parts[2]
    if md5 not in files_md5:
        continue
    if ver == "v18":
        v18_cache[md5] = cf
    elif ver == "v20":
        v20_cache[md5] = cf


def compact(s):
    return re.sub(r"[\s\-\.,/]", "", (s or "").upper())


# Metric tracking
metrics_v18 = {
    "customer_empty": 0, "cage_empty": 0, "material_empty": 0,
    "title_empty": 0, "revisions_empty": 0, "warnings": 0,
    "sus_standards": 0, "pn_truncated": 0, "bom_items_total": 0,
    "rev_entries_total": 0, "cost": 0.0,
}
metrics_v20 = {k: 0 if isinstance(v, (int, float)) else v for k, v in metrics_v18.items()}
metrics_v20["cost"] = 0.0

per_file_changes = []

for md5, fname in sorted(files_md5.items(), key=lambda x: x[1]):
    v18 = v18_cache.get(md5)
    v20 = v20_cache.get(md5)
    if not v18 or not v20:
        continue

    with open(v18, encoding="utf-8") as fp:
        d18 = json.load(fp)
    with open(v20, encoding="utf-8") as fp:
        d20 = json.load(fp)

    changes = []

    def empty(d, k):
        v = d.get(k)
        if isinstance(v, list):
            return not v
        if isinstance(v, dict):
            return not v or all(not x for x in v.values() if isinstance(x, str))
        return not (v or "").strip() if isinstance(v, str) else not v

    # count empties
    for k, label in [("customer", "customer_empty"), ("cage_code", "cage_empty"),
                     ("material", "material_empty"), ("title", "title_empty"),
                     ("revisions_history", "revisions_empty")]:
        if empty(d18, k):
            metrics_v18[label] += 1
        if empty(d20, k):
            metrics_v20[label] += 1

        # Compare field value
        old_v = d18.get(k)
        new_v = d20.get(k)
        if empty(d18, k) and not empty(d20, k):
            if isinstance(new_v, list):
                changes.append(f"✅ {k}: היה ריק → {len(new_v)} רשומות")
            else:
                changes.append(f"✅ {k}: היה ריק → {str(new_v)[:40]!r}")
        elif not empty(d18, k) and empty(d20, k):
            changes.append(f"❌ {k}: רגרסיה! היה קיים → ריק")

    # PN/DWG changes
    if d18.get("part_number") != d20.get("part_number"):
        changes.append(f"🔧 part_number: {d18.get('part_number')!r} → {d20.get('part_number')!r}")
    if d18.get("drawing_number") != d20.get("drawing_number"):
        changes.append(f"🔧 drawing_number: {d18.get('drawing_number')!r} → {d20.get('drawing_number')!r}")

    # PN truncation check
    fname_compact = compact(Path(fname).stem)
    for d, key in [(d18, "v18"), (d20, "v20")]:
        pn_c = compact(d.get("part_number") or "")
        if pn_c and len(pn_c) >= 6 and pn_c not in fname_compact:
            metrics_v18["pn_truncated" if key == "v18" else "pn_truncated"] += 0
            if key == "v18":
                metrics_v18["pn_truncated"] += 1
            else:
                metrics_v20["pn_truncated"] += 1

    # BOM items count
    metrics_v18["bom_items_total"] += len(d18.get("bom_items") or [])
    metrics_v20["bom_items_total"] += len(d20.get("bom_items") or [])

    # Revisions entries
    metrics_v18["rev_entries_total"] += len(d18.get("revisions_history") or [])
    metrics_v20["rev_entries_total"] += len(d20.get("revisions_history") or [])

    # Warnings count
    v18_warns = d18.get("_pn_warnings") or []
    v20_warns = d20.get("_pn_warnings") or []
    metrics_v18["warnings"] += len(v18_warns)
    metrics_v20["warnings"] += len(v20_warns)
    for w in v18_warns:
        if "SUSPICIOUS_STANDARD" in w:
            metrics_v18["sus_standards"] += 1
    for w in v20_warns:
        if "SUSPICIOUS_STANDARD" in w:
            metrics_v20["sus_standards"] += 1

    # Customer changes (normalization)
    if (d18.get("customer") or "") != (d20.get("customer") or "") and d20.get("customer"):
        if d18.get("customer"):
            changes.append(f"🧹 customer: {d18['customer']!r} → {d20['customer']!r}")

    # Cost
    c18 = (d18.get("_cost_info") or {}).get("total_cost_usd", 0)
    c20 = (d20.get("_cost_info") or {}).get("total_cost_usd", 0)
    metrics_v18["cost"] += c18
    metrics_v20["cost"] += c20

    if changes:
        per_file_changes.append((fname, changes))


# Print results
print("=" * 95)
print("HEAD-TO-HEAD: v18 ↔ v20")
print("=" * 95)
print(f'{"Metric":<30s} {"v18":>12s} {"v20":>12s} {"Δ":>12s}')
print("-" * 95)
for key, label in [
    ("customer_empty", "Customer empty"),
    ("cage_empty", "CAGE empty"),
    ("material_empty", "Material empty"),
    ("title_empty", "Title empty"),
    ("revisions_empty", "Revisions empty"),
    ("pn_truncated", "PN truncated/mismatch"),
    ("warnings", "Total warnings"),
    ("sus_standards", "SUSPICIOUS_STANDARD"),
    ("bom_items_total", "BOM items total"),
    ("rev_entries_total", "Revisions entries total"),
]:
    v18v, v20v = metrics_v18[key], metrics_v20[key]
    delta = v20v - v18v
    sign = "↓" if delta < 0 else ("↑" if delta > 0 else "=")
    # For "good" metrics (more is better: bom_items, rev_entries), invert interpretation
    print(f"{label:<30s} {v18v:>12} {v20v:>12} {sign}{abs(delta):>10}")

print("-" * 95)
print(f'{"Total cost (USD)":<30s} ${metrics_v18["cost"]:>11.3f} ${metrics_v20["cost"]:>11.3f} '
      f'  ${metrics_v20["cost"] - metrics_v18["cost"]:+.3f}')

print()
print("=" * 95)
print("PER-FILE CHANGES")
print("=" * 95)
for fname, changes in per_file_changes:
    print(f"\n📄 {fname}")
    for c in changes:
        print(f"   {c}")
