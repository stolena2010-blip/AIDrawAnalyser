"""
היסטוריה של ניתוחים שבוצעו — שמירה ל-output/history.jsonl + קריאה ל-UI.

מטרה: דף "📋 ניתוחים אחרונים" שמאפשר למשתמש לראות מה ניתח לאחרונה
ולחזור לתוצאה (אם הקובץ JSON נשמר).

פורמט קובץ — JSON Lines (שורה לרשומה):
    {
      "timestamp": "2026-04-25T20:30:00",
      "filename": "BP70616A.pdf",
      "mode": "single" | "assembly",
      "part_number": "BP70616A",
      "drawing_count": 1,        # 1 ל-single, n ל-assembly
      "warning_count": 2,
      "review_status": "pending" | "edited" | "reviewed",
      "cost_usd": 0.0341,        # עלות הניתוח הזה
      "cache_hit": false,        # האם נטען מ-cache
      "json_path": "output/BP70616A_20260425_203000.json"  # ייתכן null
    }

הרשומה מתווספת אחרי כל ניתוח מוצלח. הקובץ נטען עצלן בעת קריאה.
ניתן לכבות/לאפשר עם משתנה הסביבה ``HISTORY_DISABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HISTORY_PATH = Path("output") / "history.jsonl"
_MAX_RECORDS_DEFAULT = 200  # ברירת מחדל לתצוגה — נטען רק את האחרונים


def _is_enabled() -> bool:
    return os.environ.get("HISTORY_DISABLED", "").strip().lower() not in (
        "true", "1", "yes",
    )


def _ensure_dir() -> None:
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def append_history(
    *,
    filename: str,
    mode: str,
    part_number: str = "",
    drawing_count: int = 1,
    warning_count: int = 0,
    review_status: str = "pending",
    cost_usd: float = 0.0,
    cache_hit: bool = False,
    json_path: str | None = None,
) -> None:
    """מוסיף רשומה לקובץ ההיסטוריה. נכשל בשקט אם הכתיבה נכשלת — זה
    log-only, לא חוסם זרימה ראשית."""
    if not _is_enabled():
        return
    record: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "filename": filename or "",
        "mode": mode,
        "part_number": part_number or "",
        "drawing_count": int(drawing_count),
        "warning_count": int(warning_count),
        "review_status": review_status,
        "cost_usd": round(float(cost_usd or 0.0), 6),
        "cache_hit": bool(cache_hit),
        "json_path": json_path or "",
    }
    try:
        _ensure_dir()
        with _HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("[history] לא הצלחתי לכתוב ל-%s: %s", _HISTORY_PATH, exc)


def read_history(limit: int = _MAX_RECORDS_DEFAULT) -> list[dict]:
    """מחזיר את ``limit`` הרשומות האחרונות. רשומות ישנות יותר נחתכות.

    אם הקובץ לא קיים או פגום — מחזיר רשימה ריקה.
    """
    if not _HISTORY_PATH.exists():
        return []
    try:
        lines = _HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("[history] קריאה נכשלה: %s", exc)
        return []
    records: list[dict] = []
    # קוראים מהסוף (חדש ביותר ראשון)
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                records.append(rec)
                if len(records) >= limit:
                    break
        except json.JSONDecodeError:
            continue
    return records


def aggregate_stats(records: list[dict] | None = None) -> dict:
    """סטטיסטיקות מצטברות מההיסטוריה — לשימוש ב-dashboard."""
    if records is None:
        records = read_history(limit=10000)
    if not records:
        return {
            "count": 0, "total_cost_usd": 0.0, "avg_cost_usd": 0.0,
            "cache_hits": 0, "cache_hit_rate": 0.0,
            "by_mode": {}, "by_review_status": {},
        }
    total_cost = sum(r.get("cost_usd", 0) or 0 for r in records)
    cache_hits = sum(1 for r in records if r.get("cache_hit"))
    by_mode: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in records:
        m = r.get("mode", "unknown")
        by_mode[m] = by_mode.get(m, 0) + 1
        s = r.get("review_status", "pending")
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "count": len(records),
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_usd": round(total_cost / len(records), 6),
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / len(records), 3),
        "by_mode": by_mode,
        "by_review_status": by_status,
    }


def clear_history() -> int:
    """מוחק את קובץ ההיסטוריה. מחזיר את מספר הרשומות שנמחקו."""
    if not _HISTORY_PATH.exists():
        return 0
    try:
        n = sum(1 for line in _HISTORY_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip())
        _HISTORY_PATH.unlink()
        return n
    except OSError as exc:
        logger.warning("[history] מחיקה נכשלה: %s", exc)
        return 0
