"""
סריקת כל ה-JSON הקשאים הקיימים ב-output/.cache/ + פלטי output/*.json,
הרצת validate_standards() על כל אחד, וסיכום ההזיות שנמצאו.

שימוש:
    python scripts/find_hallucinated_standards.py
"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

# Windows console לא יודע לטפל ב-UTF-8 כברירת מחדל → עטיפת stdout ל-UTF-8
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# לאפשר import מהתיקייה הראשית
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.validators import validate_standards  # noqa: E402


def scan_json_file(path: Path) -> tuple[list[dict], dict]:
    """מחזיר (warnings, report) לקובץ אחד. מתעלם משגיאות JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], {}

    if not isinstance(report, dict):
        return [], {}

    return validate_standards(report), report


def main() -> int:
    scan_dirs = [
        ROOT / "output" / ".cache",
        ROOT / "output",
    ]

    files: list[Path] = []
    for d in scan_dirs:
        if d.exists():
            files.extend(d.glob("*.json"))

    if not files:
        print("לא נמצאו קבצי JSON לסריקה.")
        return 1

    total_files = 0
    files_with_hallucinations = 0
    all_flagged_standards: Counter[str] = Counter()
    per_file: list[tuple[str, list[str]]] = []

    for path in files:
        if path.name == "_runtime_settings.json":
            continue
        total_files += 1
        warnings, report = scan_json_file(path)
        if not warnings:
            continue
        flagged = [w["value"] for w in warnings]
        files_with_hallucinations += 1
        all_flagged_standards.update(flagged)
        per_file.append((path.name, flagged))

    # ─── דוח ─────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"סה\"כ קבצים שנסרקו: {total_files}")
    print(f"קבצים עם תקנים חשודים: {files_with_hallucinations} "
          f"({files_with_hallucinations/max(total_files,1)*100:.1f}%)")
    print(f"סה\"כ הופעות חשודות: {sum(all_flagged_standards.values())}")
    print(f"תקנים חשודים ייחודיים: {len(all_flagged_standards)}")
    print(f"{'='*70}\n")

    if all_flagged_standards:
        print("TOP תקנים חשודים (לפי תדירות):")
        for std, count in all_flagged_standards.most_common(20):
            print(f"  {count:4d}x  {std}")

    if per_file:
        print(f"\n{'─'*70}")
        print("פירוט לקבצים (10 ראשונים):")
        for name, flagged in per_file[:10]:
            print(f"\n  📄 {name}")
            for std in flagged:
                print(f"       ❌ {std}")

        # שמירה ל-CSV לסקירה
        out_csv = ROOT / "output" / "hallucinated_standards_report.csv"
        with open(out_csv, "w", encoding="utf-8") as f:
            f.write("file,flagged_standard\n")
            for name, flagged in per_file:
                for std in flagged:
                    # מסיר פסיקים מהשם כדי לא לשבור את ה-CSV
                    safe_std = std.replace(",", ";")
                    f.write(f"{name},{safe_std}\n")
        print(f"\n✅ דוח מלא נשמר: {out_csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
