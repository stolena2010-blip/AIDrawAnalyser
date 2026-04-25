"""
Audit log — לוג בלתי-משתנה של פעולות משמעותיות באפליקציה.

מיועד לקונים בתעשייה רגולטורית (תעופה, רפואה, ביטחון) שדורשים עקיבות
מלאה: מי עשה מה, מתי, על איזה קובץ, ובאיזה מודל.

ההבדל מ-history.py:
  • history = "מה ניתחתי לאחרונה" — UI-friendly, מוצג למשתמש
  • audit = "מה קרה בכלל" — compliance-friendly, append-only, לא נמחק

פעולות שמתועדות:
  • EXTRACT — חילוץ שרטוט
  • EDIT — עריכת שדה ב-Review form
  • APPROVE — אישור תוצאה
  • EXPORT — יצירת דוח (HTML / Excel / JSON)
  • CACHE_HIT — שימוש בתוצאה ממטמון
  • CUSTOMER_MAPPING_CHANGE — עריכה ב-customer manager
  • RELATIONSHIP_ANALYSIS — ניתוח קשרי מכלול

פורמט — JSON Lines (output/audit.jsonl):
  {
    "timestamp": "2026-04-25T20:30:00",
    "action": "EXTRACT",
    "user": "system" | <username>,
    "subject": "BP70616A.pdf",        # על מה הפעולה
    "details": {...},                 # שדות נוספים לפי הפעולה
    "model": "gpt-4o",                # אם רלוונטי
    "cost_usd": 0.0341,               # אם רלוונטי
  }

הקובץ append-only. לא נמחק אוטומטית. כיבוי עם ``AUDIT_LOG_DISABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUDIT_PATH = Path("output") / "audit.jsonl"

# Action constants
ACTION_EXTRACT = "EXTRACT"
ACTION_EDIT = "EDIT"
ACTION_APPROVE = "APPROVE"
ACTION_EXPORT = "EXPORT"
ACTION_CACHE_HIT = "CACHE_HIT"
ACTION_CUSTOMER_MAPPING = "CUSTOMER_MAPPING_CHANGE"
ACTION_RELATIONSHIP = "RELATIONSHIP_ANALYSIS"


def _is_enabled() -> bool:
    return os.environ.get("AUDIT_LOG_DISABLED", "").strip().lower() not in (
        "true", "1", "yes",
    )


def _resolve_user() -> str:
    """משתמש נוכחי (env var קודם, אז OS user, ברירת מחדל: 'system')."""
    return (
        os.environ.get("AIDRAW_USER")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "system"
    )


def log_event(
    action: str,
    *,
    subject: str = "",
    details: dict | None = None,
    model: str = "",
    cost_usd: float = 0.0,
    user: str | None = None,
) -> None:
    """מתעד אירוע ל-audit log. לא חוסם זרימה — נכשל בשקט אם הכתיבה נכשלת."""
    if not _is_enabled():
        return
    record: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "user": user or _resolve_user(),
        "subject": subject,
    }
    if details:
        record["details"] = details
    if model:
        record["model"] = model
    if cost_usd:
        record["cost_usd"] = round(float(cost_usd), 6)
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("[audit] write failed: %s", exc)


def read_events(
    limit: int = 500,
    action_filter: str | None = None,
    user_filter: str | None = None,
) -> list[dict]:
    """קורא ``limit`` רשומות אחרונות, אופציונלי עם פילטר לפי action / user."""
    if not _AUDIT_PATH.exists():
        return []
    try:
        lines = _AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("[audit] read failed: %s", exc)
        return []
    events: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if action_filter and ev.get("action") != action_filter:
            continue
        if user_filter and ev.get("user") != user_filter:
            continue
        events.append(ev)
        if len(events) >= limit:
            break
    return events


def event_summary() -> dict:
    """סיכום מצטבר — כמה אירועים לכל action, אילו משתמשים פעלו."""
    if not _AUDIT_PATH.exists():
        return {"total": 0, "by_action": {}, "users": []}
    events = read_events(limit=100000)
    by_action: dict[str, int] = {}
    users: set[str] = set()
    for ev in events:
        a = ev.get("action", "?")
        by_action[a] = by_action.get(a, 0) + 1
        u = ev.get("user", "")
        if u:
            users.add(u)
    return {
        "total": len(events),
        "by_action": by_action,
        "users": sorted(users),
    }


# ─── Convenience helpers (called from app.py / ui_assembly.py) ───
def log_extract(filename: str, *, model: str = "", cost_usd: float = 0.0,
                cache_hit: bool = False, mode: str = "single") -> None:
    log_event(
        ACTION_CACHE_HIT if cache_hit else ACTION_EXTRACT,
        subject=filename,
        details={"mode": mode},
        model=model,
        cost_usd=cost_usd,
    )


def log_edit(part_number: str, fields_changed: list[str]) -> None:
    log_event(
        ACTION_EDIT,
        subject=part_number,
        details={"fields_changed": fields_changed},
    )


def log_approve(part_number: str, *, has_edits: bool = False) -> None:
    log_event(
        ACTION_APPROVE,
        subject=part_number,
        details={"has_edits": has_edits},
    )


def log_export(filename: str, format_: str, *, reviewed: bool = False) -> None:
    log_event(
        ACTION_EXPORT,
        subject=filename,
        details={"format": format_, "reviewed": reviewed},
    )


def log_customer_mapping_change(operation: str, customer_name: str) -> None:
    """operation: 'upsert' / 'delete' / 'rename'"""
    log_event(
        ACTION_CUSTOMER_MAPPING,
        subject=customer_name,
        details={"operation": operation},
    )


def log_relationship_analysis(*, drawing_count: int, cost_usd: float = 0.0) -> None:
    log_event(
        ACTION_RELATIONSHIP,
        subject=f"{drawing_count} drawings",
        details={"drawing_count": drawing_count},
        cost_usd=cost_usd,
    )
