"""
התראות חיצוניות — Slack / Email — אחרי batch של ניתוחים.

מטרה: עבודה asynchronous. המשתמש מעלה 50 שרטוטים → יוצא לקפה →
מקבל הודעת Slack כשהעבודה הסתיימה.

תמיכה:
  • Slack (webhook URL — ב-.env)
  • Email (SMTP — ב-.env)
  • Generic webhook (POST של JSON)

הגדרת .env:
  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
  NOTIFICATION_EMAIL=user@example.com
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=sender@example.com
  SMTP_PASSWORD=app-password
  GENERIC_WEBHOOK_URL=https://your-system.example.com/webhook

אם משתנה לא מוגדר — ה-channel הזה פשוט לא נשלח אליו (silent skip).
לכיבוי כללי: ``NOTIFICATIONS_DISABLED=true``.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    return os.environ.get("NOTIFICATIONS_DISABLED", "").strip().lower() not in (
        "true", "1", "yes",
    )


# ─────────────────────────────────────────────────────────────────
# Slack
# ─────────────────────────────────────────────────────────────────
def send_slack(text: str, *, blocks: list | None = None) -> bool:
    """שולח הודעה ל-Slack webhook. מחזיר True אם הצליח."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return False
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("[notifications] Slack send failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────
# Email (SMTP)
# ─────────────────────────────────────────────────────────────────
def send_email(
    subject: str,
    body: str,
    *,
    to: str | None = None,
    html: bool = False,
) -> bool:
    """שולח אימייל דרך SMTP. מחזיר True אם הצליח."""
    to_addr = to or os.environ.get("NOTIFICATION_EMAIL", "").strip()
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    if not (to_addr and smtp_host and smtp_user and smtp_password):
        return False

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("[notifications] Email send failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────
# Generic webhook
# ─────────────────────────────────────────────────────────────────
def send_webhook(payload: dict) -> bool:
    """POST של JSON payload ל-URL חיצוני (ERP / MES / monitoring)."""
    url = os.environ.get("GENERIC_WEBHOOK_URL", "").strip()
    if not url:
        return False
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("[notifications] Webhook send failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────
# High-level: batch completion notification
# ─────────────────────────────────────────────────────────────────
def notify_batch_complete(
    *,
    drawing_count: int,
    success_count: int,
    failed_count: int,
    total_cost_usd: float,
    total_warnings: int,
    duration_seconds: float | None = None,
) -> dict:
    """שולח הודעת "ניתוח batch הסתיים" לכל הערוצים המוגדרים.

    מחזיר dict עם סטטוס לכל ערוץ:
        {"slack": True/False, "email": True/False, "webhook": True/False}
    """
    if not _is_enabled():
        return {"slack": False, "email": False, "webhook": False, "disabled": True}

    duration_str = ""
    if duration_seconds is not None:
        m, s = divmod(int(duration_seconds), 60)
        duration_str = f" ({m}:{s:02d})"

    text = (
        f"📐 *AIDrawAnalyser* — batch הושלם{duration_str}\n"
        f"• ניתוחים: {success_count}/{drawing_count} הצליחו"
        f"{f' · {failed_count} נכשלו' if failed_count else ''}\n"
        f"• אזהרות ולידציה: {total_warnings}\n"
        f"• עלות AI: ${total_cost_usd:.4f}"
    )

    payload = {
        "event": "batch_complete",
        "drawing_count": drawing_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "total_cost_usd": round(total_cost_usd, 6),
        "total_warnings": total_warnings,
        "duration_seconds": duration_seconds,
    }

    results = {
        "slack": send_slack(text),
        "email": send_email(
            subject=f"📐 AIDrawAnalyser — {success_count} drawings analyzed",
            body=text.replace("*", ""),
        ),
        "webhook": send_webhook(payload),
    }
    return results


def is_any_channel_configured() -> bool:
    """האם לפחות ערוץ אחד מוגדר ב-.env? — שימושי להחבאת UI אם אין configs."""
    return any([
        os.environ.get("SLACK_WEBHOOK_URL", "").strip(),
        all([
            os.environ.get("NOTIFICATION_EMAIL", "").strip(),
            os.environ.get("SMTP_HOST", "").strip(),
            os.environ.get("SMTP_USER", "").strip(),
            os.environ.get("SMTP_PASSWORD", ""),
        ]),
        os.environ.get("GENERIC_WEBHOOK_URL", "").strip(),
    ])
