"""
Pre-share cleanup script — מריץ checklist לפני שיתוף הריפו עם קונה / שותף.

בודק:
  • אין נתוני לקוחות אמיתיים tracked בגיט (draws/, output/, REPORTS/)
  • אין secrets ב-history (.env, *.key)
  • אין קבצים גדולים (>10MB) tracked
  • Tests עוברים
  • ruff נקי
  • LICENSE קיים

הרצה (read-only — לא מוחק כלום):
    python scripts/prepare_for_sharing.py

הרצה עם תיקונים (interactive — מבקש אישור לכל פעולה):
    python scripts/prepare_for_sharing.py --fix
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Windows console fix — Hebrew + emoji require UTF-8, not cp1255.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

ROOT = Path(__file__).resolve().parent.parent

# ─── תיקיות שאסור שיכילו קבצים אמיתיים ───
SENSITIVE_DIRS = ["draws", "output", "REPORTS"]

# ─── סיומות של secrets/credentials ───
SECRET_PATTERNS = [".env", "*.key", "*.pem", "credentials.json", "secrets.json"]

# ─── מקסימום גודל קובץ tracked (MB) ───
MAX_TRACKED_FILE_MB = 10

# ─── קבצים שחייבים להיות קיימים ───
REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "TECHNICAL_DUE_DILIGENCE.md",
    "SECURITY.md",
    "DATA_HANDLING.md",
    "DEPLOYMENT_GUIDE.md",
    "LICENSE_REVIEW.md",
]


# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────
def _run(cmd: list[str], capture: bool = True) -> tuple[int, str]:
    """מריץ פקודה ומחזיר (returncode, stdout+stderr)."""
    result = subprocess.run(
        cmd, cwd=ROOT, capture_output=capture, text=True, encoding="utf-8"
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output


def _section(title: str) -> None:
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print("═" * 70)


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


# ───────────────────────────────────────────────────────────────
# Checks
# ───────────────────────────────────────────────────────────────
def check_sensitive_dirs_not_tracked() -> list[str]:
    """בודק שתיקיות נתוני לקוח לא tracked בגיט."""
    issues: list[str] = []
    for d in SENSITIVE_DIRS:
        rc, out = _run(["git", "ls-files", d])
        if rc != 0:
            _warn(f"git ls-files {d} failed (לא בריפו git?)")
            continue
        files = [line for line in out.strip().splitlines() if line.strip()]
        # .gitkeep מותר — סימן שהתיקייה קיימת אבל ריקה
        files = [f for f in files if not f.endswith(".gitkeep")]
        if files:
            issues.append(f"{d}/ — {len(files)} קבצים tracked: {files[:3]}...")
            _fail(f"{d}/ tracked: {len(files)} files")
        else:
            _ok(f"{d}/ — נקי (לא tracked)")
    return issues


def check_secrets_not_in_history() -> list[str]:
    """בודק שלא היו secrets ב-history."""
    issues: list[str] = []
    for pattern in SECRET_PATTERNS:
        rc, out = _run(["git", "log", "--all", "--diff-filter=A", "--name-only",
                        "--pretty=format:", "--", pattern])
        if rc != 0:
            continue
        files = sorted({line.strip() for line in out.splitlines() if line.strip()})
        if files:
            issues.append(f"{pattern} — היה ב-history: {files}")
            _fail(f"{pattern} appears in history: {files}")
        else:
            _ok(f"{pattern} — אין ב-history")
    return issues


def check_no_large_tracked_files() -> list[str]:
    """בודק שאין קבצים גדולים tracked."""
    issues: list[str] = []
    rc, out = _run(["git", "ls-files"])
    if rc != 0:
        _warn("לא ניתן לקרוא git ls-files — מדלג")
        return []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
        except OSError:
            continue
        if size_mb > MAX_TRACKED_FILE_MB:
            issues.append(f"{rel} — {size_mb:.1f}MB")
            _fail(f"{rel}: {size_mb:.1f}MB > {MAX_TRACKED_FILE_MB}MB")
    if not issues:
        _ok(f"אין קבצים tracked מעל {MAX_TRACKED_FILE_MB}MB")
    return issues


def check_required_files_exist() -> list[str]:
    """בודק שכל המסמכים הנדרשים קיימים."""
    issues: list[str] = []
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if path.exists():
            _ok(f"{rel} קיים")
        else:
            issues.append(f"{rel} חסר")
            _fail(f"{rel} חסר")
    return issues


def check_tests_pass() -> list[str]:
    """מריץ pytest. אם כושל — אזהרה."""
    print("  ⏳ מריץ pytest...")
    rc, out = _run(["python", "-m", "pytest", "tests/", "-q", "--no-header",
                    "--tb=no"])
    if rc == 0:
        # extract last line with summary
        last_lines = [line for line in out.splitlines() if line.strip()][-3:]
        for line in last_lines:
            _ok(line.strip())
        return []
    _fail("pytest כשל")
    print(out[-1000:])
    return ["pytest failed"]


def check_ruff_clean() -> list[str]:
    """מריץ ruff."""
    print("  ⏳ מריץ ruff...")
    rc, out = _run(["python", "-m", "ruff", "check", "core/", "storage/", "tests/",
                    "app.py", "ui_assembly.py"])
    if rc == 0:
        _ok("ruff נקי")
        return []
    _fail("ruff מצא שגיאות")
    print(out[-1000:])
    return ["ruff failed"]


def check_env_not_tracked() -> list[str]:
    """בודק ש-.env לא tracked."""
    rc, out = _run(["git", "ls-files", ".env"])
    if out.strip():
        _fail(".env tracked בגיט!")
        return [".env tracked"]
    _ok(".env לא tracked")
    return []


def check_customer_mappings_present() -> list[str]:
    """מציג מצב customer_mappings.json — לא חוסם, רק מודיע."""
    path = ROOT / "data" / "customer_mappings.json"
    if not path.exists():
        _warn(
            "data/customer_mappings.json חסר — האפליקציה תעבוד אבל בלי "
            "השלמת לקוחות אוטומטית."
        )
        return []
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        n_cages = len(data.get("cage_to_customer", {}))
        n_aliases = len(data.get("customer_aliases", {}))
        _warn(
            f"data/customer_mappings.json קיים ({n_cages} CAGE codes, "
            f"{n_aliases} aliases). **שקלי אם הקונה אמור לראות את הלקוחות "
            f"שלך — אם לא, החלפי בקובץ ריק לפני שיתוף.**"
        )
    except (OSError, ValueError) as exc:
        _fail(f"customer_mappings.json לא תקין: {exc}")
        return [str(exc)]
    return []


def list_local_files_to_clean() -> None:
    """מציג קבצים מקומיים שכדאי לנקות לפני שיתוף — לא חוסם."""
    print()
    print("  קבצים/תיקיות מקומיים שאינם בגיט אבל קיימים על הדיסק:")
    candidates = [
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".coverage",
        "__pycache__",
        "draws",
        "output",
        "REPORTS",
        ".env",
    ]
    for c in candidates:
        path = ROOT / c
        if path.exists():
            if path.is_dir():
                try:
                    size = sum(
                        f.stat().st_size for f in path.rglob("*") if f.is_file()
                    ) / (1024 * 1024)
                    print(f"    📁 {c}/ — {size:.1f}MB")
                except OSError:
                    print(f"    📁 {c}/")
            else:
                size = path.stat().st_size / 1024
                print(f"    📄 {c} — {size:.1f}KB")
    print(
        "\n  💡 ננקה אותם ידנית רק לפני שיתוף הריפו (לא דרך הסקריפט הזה — "
        "destructive)."
    )


# ───────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-share cleanup checklist for AIDrawAnalyser."
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="(לא ממומש בגרסה זו — ראה קוד) הצעה לתיקון אוטומטי בעתיד.",
    )
    args = parser.parse_args()
    if args.fix:
        print("⚠️  --fix לא ממומש כרגע. מריץ בדיקה בלבד.")

    print("\n🔍 AIDrawAnalyser — Pre-Share Cleanup Checklist")
    print(f"   Root: {ROOT}")

    all_issues: list[tuple[str, list[str]]] = []

    _section("1. תיקיות נתוני לקוח (draws/, output/, REPORTS/)")
    all_issues.append(("Sensitive dirs", check_sensitive_dirs_not_tracked()))

    _section("2. Secrets ב-git history")
    all_issues.append(("Secrets in history", check_secrets_not_in_history()))

    _section("3. .env לא tracked")
    all_issues.append((".env tracked", check_env_not_tracked()))

    _section("4. customer_mappings.json")
    all_issues.append(("Customer mappings", check_customer_mappings_present()))

    _section(f"5. קבצים גדולים tracked (>{MAX_TRACKED_FILE_MB}MB)")
    all_issues.append(("Large files", check_no_large_tracked_files()))

    _section("6. מסמכים נדרשים")
    all_issues.append(("Required files", check_required_files_exist()))

    _section("7. בדיקות (pytest)")
    all_issues.append(("Tests", check_tests_pass()))

    _section("8. Lint (ruff)")
    all_issues.append(("Ruff", check_ruff_clean()))

    _section("9. תיקיות מקומיות לניקוי ידני")
    list_local_files_to_clean()

    # ─── סיכום ───
    _section("📊 סיכום")
    total_issues = sum(len(issues) for _, issues in all_issues)
    if total_issues == 0:
        print("\n  🎉 הריפו מוכן לשיתוף עם קונה!")
        print("\n  💡 דברים שעדיין דורשים תשומת לב ידנית:")
        print("     1. customer_mappings.json — האם הקונה אמור לראות את הלקוחות שלך?")
        print("     2. Masters.xlsx — האם מכיל מידע פנימי שאסור לחשוף?")
        print("     3. ניקוי תיקיות מקומיות (draws/, output/, .env) לפני zip/git push")
        return 0

    print(f"\n  ⚠️  נמצאו {total_issues} בעיות:")
    for category, issues in all_issues:
        if issues:
            print(f"\n  {category}:")
            for issue in issues:
                print(f"    • {issue}")
    print("\n  ❌ תקני אותן לפני שיתוף.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
