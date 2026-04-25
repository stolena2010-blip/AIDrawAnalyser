"""
מנתח את 21 התוצאות מ-draws/new7/ ומחזיר דוח איכות:
  • שלמות שדות חובה (PN, customer, material, revision, CAGE)
  • אזהרות ולידציה לפי severity
  • מקרים חשודים (PN זהה לשם הקובץ? CAGE לא תואם customer?)
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

DRAWS_DIR = Path("draws/new7")
CACHE_DIR = Path("output/.cache")
CACHE_VERSION_PREFIX = "v24_"  # version בו רץ ה-batch ב-25/04 08:32-08:43


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def load_results() -> list[tuple[str, dict]]:
    """מחזיר רשימה של (filename, extraction_result) ממויינת לפי שם."""
    md5_to_name = {md5(p): p.name for p in DRAWS_DIR.iterdir() if p.is_file()}
    pairs = []
    for cache in CACHE_DIR.glob(f"{CACHE_VERSION_PREFIX}*_assembly.json"):
        parts = cache.stem.split("_")
        h = parts[2]
        if h in md5_to_name:
            data = json.loads(cache.read_text(encoding="utf-8"))
            pairs.append((md5_to_name[h], data))
    return sorted(pairs, key=lambda t: t[0])


def is_filled(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        return bool(s) and s.upper() not in {"", "-", "—", "N/A", "NA", "NONE"}
    if isinstance(v, (list, dict)):
        return bool(v)
    return True


def main() -> None:
    pairs = load_results()
    n = len(pairs)
    print(f"📊 Analyzing {n} drawings from draws/new7/\n")

    # ── 1. Field completeness ──
    fields = ["part_number", "drawing_number", "customer", "material",
              "revision", "cage_code", "title"]
    print("─" * 70)
    print("🧩 FIELD COMPLETENESS")
    print("─" * 70)
    for f in fields:
        filled = sum(1 for _, d in pairs if is_filled(d.get(f)))
        bar = "█" * int(filled * 30 / n)
        pct = filled * 100 // n
        print(f"  {f:<18} {bar:<30} {filled:>2}/{n}  ({pct:>3}%)")

    # ── 2. List counts (BOM/standards/notes) ──
    print()
    print("─" * 70)
    print("📋 LIST FIELDS — סך כל הפריטים בכל 21 השרטוטים")
    print("─" * 70)
    for f in ["standards", "bom_items", "machining_processes",
              "coating_processes", "additional_processes", "revisions_history"]:
        counts = [len(d.get(f) or []) for _, d in pairs]
        total = sum(counts)
        zeros = sum(1 for c in counts if c == 0)
        print(f"  {f:<22} total={total:<4}  empty={zeros}/{n}  "
              f"avg={total/n:.1f}  max={max(counts)}")

    # ── 3. Validation warnings by severity/type ──
    print()
    print("─" * 70)
    print("⚠️  VALIDATION WARNINGS")
    print("─" * 70)
    severity_count: Counter = Counter()
    type_count: Counter = Counter()
    drawings_with_warnings = 0
    for _, d in pairs:
        warnings = d.get("_validation_warnings") or []
        if warnings:
            drawings_with_warnings += 1
        for w in warnings:
            severity_count[w.get("severity", "?")] += 1
            type_count[w.get("type", "?")] += 1
    print(f"  שרטוטים עם אזהרות: {drawings_with_warnings}/{n}")
    print()
    print("  לפי severity:")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        c = severity_count.get(sev, 0)
        if c:
            print(f"    {sev:<10} {c}")
    print()
    print("  לפי סוג (Top 10):")
    for typ, c in type_count.most_common(10):
        print(f"    {typ:<35} {c}")

    # ── 4. Customer extraction quality ──
    print()
    print("─" * 70)
    print("🏢 CUSTOMER & CAGE")
    print("─" * 70)
    customers = Counter()
    cages = Counter()
    no_customer = []
    no_cage = []
    for fname, d in pairs:
        cust = (d.get("customer") or "").strip()
        cage = (d.get("cage_code") or "").strip()
        if cust:
            customers[cust] += 1
        else:
            no_customer.append(fname)
        if cage:
            cages[cage] += 1
        else:
            no_cage.append(fname)
    print(f"  לקוחות שזוהו ({len(customers)} ייחודיים):")
    for c, count in customers.most_common():
        print(f"    {count}× {c[:60]}")
    print()
    print(f"  CAGE codes ({len(cages)} ייחודיים):")
    for c, count in cages.most_common():
        print(f"    {count}× {c}")
    if no_customer:
        print(f"\n  ⚠️ ללא customer ({len(no_customer)}): "
              f"{', '.join(n[:25] for n in no_customer[:5])}"
              + ("..." if len(no_customer) > 5 else ""))

    # ── 5. Suspicious findings ──
    print()
    print("─" * 70)
    print("🚨 SUSPICIOUS FINDINGS — בעיות פוטנציאליות שכדאי לבדוק ידנית")
    print("─" * 70)
    suspicious = []

    for fname, d in pairs:
        pn = (d.get("part_number") or "").strip()
        cust = (d.get("customer") or "").strip()
        mat = (d.get("material") or "").strip()
        rev = (d.get("revision") or "").strip()

        # א. customer חשוד (מילה אחת לא-קנונית, או lowercase weird)
        if cust and len(cust) < 4:
            suspicious.append(f"  [SHORT_CUSTOMER] {fname}: customer='{cust}'")
        if cust and cust.islower() and len(cust) > 1:
            suspicious.append(f"  [LOWERCASE_CUSTOMER] {fname}: customer='{cust}' (חשוד)")

        # ב. material קצר מדי (פחות מ-5 תווים = כנראה שבר)
        if mat and len(mat) < 5:
            suspicious.append(f"  [SHORT_MATERIAL] {fname}: material='{mat}'")

        # ג. revision חריג (יותר מ-3 תווים זה לא נפוץ)
        if rev and len(rev) > 3:
            suspicious.append(f"  [WEIRD_REVISION] {fname}: rev='{rev}'")

        # ד. PN שמתחיל ב-"ITEM" / מספר הקובץ עצמו
        if pn and re.match(r"^(?:ITEM|PART)\s+\d+$", pn, re.IGNORECASE):
            suspicious.append(f"  [GENERIC_PN] {fname}: pn='{pn}'")

    if suspicious:
        for s in suspicious[:20]:
            print(s)
        if len(suspicious) > 20:
            print(f"  ... ועוד {len(suspicious) - 20}")
    else:
        print("  ✅ לא נמצאו חשדות אוטומטיים")

    # ── 6. Per-drawing summary table ──
    print()
    print("─" * 70)
    print("📑 PER-DRAWING SUMMARY")
    print("─" * 70)
    print(f"{'#':<3} {'filename':<38} {'PN':<22} {'cust':<10} "
          f"{'rev':<5} {'#std':<5} {'#warn':<5}")
    for i, (fname, d) in enumerate(pairs, 1):
        pn = (d.get("part_number") or "")[:20]
        cust_full = d.get("customer") or ""
        cust = cust_full[:8]
        rev = (d.get("revision") or "-")[:4]
        n_std = len(d.get("standards") or [])
        n_warn = len(d.get("_validation_warnings") or [])
        warn_marker = "🔴" if n_warn else " "
        print(f"{i:<3} {fname[:38]:<38} {pn:<22} {cust:<10} "
              f"{rev:<5} {n_std:<5} {warn_marker}{n_warn:<4}")


if __name__ == "__main__":
    main()
