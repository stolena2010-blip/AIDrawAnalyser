"""
Tests עבור 3 מודולים חדשים: audit, diff, notifications.
"""
from __future__ import annotations

import pytest

from core import audit, diff, notifications


@pytest.fixture
def temp_audit(tmp_path, monkeypatch):
    """מבודד את audit log לקובץ זמני."""
    monkeypatch.setattr(audit, "_AUDIT_PATH", tmp_path / "audit.jsonl")
    yield audit


# ═════════════════════════════════════════════════════════════════════
# Audit log
# ═════════════════════════════════════════════════════════════════════
class TestAuditLog:
    def test_log_event_basic(self, temp_audit):
        temp_audit.log_event("EXTRACT", subject="x.pdf", model="gpt-4o", cost_usd=0.05)
        events = temp_audit.read_events()
        assert len(events) == 1
        e = events[0]
        assert e["action"] == "EXTRACT"
        assert e["subject"] == "x.pdf"
        assert e["model"] == "gpt-4o"
        assert e["cost_usd"] == 0.05
        assert "timestamp" in e
        assert "user" in e

    def test_log_extract_helper(self, temp_audit):
        temp_audit.log_extract("a.pdf", model="gpt-4o", cost_usd=0.1)
        events = temp_audit.read_events()
        assert events[0]["action"] == temp_audit.ACTION_EXTRACT

    def test_log_cache_hit_helper(self, temp_audit):
        temp_audit.log_extract("a.pdf", cache_hit=True)
        events = temp_audit.read_events()
        assert events[0]["action"] == temp_audit.ACTION_CACHE_HIT

    def test_log_edit(self, temp_audit):
        temp_audit.log_edit("AC-001", ["part_number", "material"])
        events = temp_audit.read_events()
        assert events[0]["action"] == temp_audit.ACTION_EDIT
        assert events[0]["details"]["fields_changed"] == ["part_number", "material"]

    def test_log_approve(self, temp_audit):
        temp_audit.log_approve("AC-001", has_edits=True)
        events = temp_audit.read_events()
        assert events[0]["action"] == temp_audit.ACTION_APPROVE
        assert events[0]["details"]["has_edits"] is True

    def test_log_export(self, temp_audit):
        temp_audit.log_export("report.html", "HTML", reviewed=True)
        events = temp_audit.read_events()
        assert events[0]["action"] == temp_audit.ACTION_EXPORT
        assert events[0]["details"]["format"] == "HTML"
        assert events[0]["details"]["reviewed"] is True

    def test_filter_by_action(self, temp_audit):
        temp_audit.log_event("EXTRACT", subject="a")
        temp_audit.log_event("EDIT", subject="b")
        temp_audit.log_event("EXTRACT", subject="c")
        extracts = temp_audit.read_events(action_filter="EXTRACT")
        assert len(extracts) == 2

    def test_event_summary(self, temp_audit):
        temp_audit.log_event("EXTRACT", subject="a")
        temp_audit.log_event("EXTRACT", subject="b")
        temp_audit.log_event("APPROVE", subject="c")
        summary = temp_audit.event_summary()
        assert summary["total"] == 3
        assert summary["by_action"]["EXTRACT"] == 2
        assert summary["by_action"]["APPROVE"] == 1

    def test_empty_when_no_file(self, temp_audit):
        assert temp_audit.read_events() == []
        assert temp_audit.event_summary()["total"] == 0

    def test_disabled_via_env(self, temp_audit, monkeypatch):
        monkeypatch.setenv("AUDIT_LOG_DISABLED", "true")
        temp_audit.log_event("EXTRACT", subject="x.pdf")
        assert temp_audit.read_events() == []


# ═════════════════════════════════════════════════════════════════════
# Diff
# ═════════════════════════════════════════════════════════════════════
class TestDiffDrawings:
    def test_identical_drawings_no_changes(self):
        d = {"part_number": "AC-001", "revision": "A", "material": "AL"}
        result = diff.diff_drawings(d, d)
        assert result["summary"]["total_changes"] == 0
        assert result["changes_by_category"] == {}

    def test_revision_change_detected(self):
        a = {"part_number": "AC-001", "revision": "A"}
        b = {"part_number": "AC-001", "revision": "B"}
        result = diff.diff_drawings(a, b)
        assert result["summary"]["total_changes"] >= 1
        assert "identity" in result["changes_by_category"]
        rev_change = next(c for c in result["changes_by_category"]["identity"]
                          if c["field"] == "revision")
        assert rev_change["type"] == diff.CHANGE_MODIFIED
        assert rev_change["old"] == "A"
        assert rev_change["new"] == "B"

    def test_material_addition(self):
        a = {"part_number": "AC-001", "material": ""}
        b = {"part_number": "AC-001", "material": "ALUMINUM 6061"}
        result = diff.diff_drawings(a, b)
        material_changes = result["changes_by_category"].get("material", [])
        assert any(c["type"] == diff.CHANGE_ADDED for c in material_changes)

    def test_bom_item_removal(self):
        a = {"bom_items": [{"item_no": "1", "part_number": "X"},
                            {"item_no": "2", "part_number": "Y"}]}
        b = {"bom_items": [{"item_no": "1", "part_number": "X"}]}
        result = diff.diff_drawings(a, b)
        bom_changes = result["changes_by_category"].get("bom", [])
        assert any(c["type"] == diff.CHANGE_REMOVED for c in bom_changes)

    def test_summary_labels(self):
        a = {"part_number": "AC-001", "revision": "A"}
        b = {"part_number": "AC-001", "revision": "B"}
        result = diff.diff_drawings(a, b)
        assert "AC-001" in result["summary"]["a_label"]
        assert "Rev A" in result["summary"]["a_label"]
        assert "Rev B" in result["summary"]["b_label"]

    def test_format_change_human(self):
        msg = diff.format_change_human({
            "field": "revision", "type": "modified",
            "old": "A", "new": "B",
        })
        assert "revision" in msg
        assert "🔄" in msg


# ═════════════════════════════════════════════════════════════════════
# Notifications (without actually sending — env vars not configured)
# ═════════════════════════════════════════════════════════════════════
class TestNotifications:
    def test_send_slack_no_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert notifications.send_slack("test") is False

    def test_send_email_no_config_returns_false(self, monkeypatch):
        for k in ["NOTIFICATION_EMAIL", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"]:
            monkeypatch.delenv(k, raising=False)
        assert notifications.send_email("subj", "body") is False

    def test_send_webhook_no_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("GENERIC_WEBHOOK_URL", raising=False)
        assert notifications.send_webhook({"event": "test"}) is False

    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATIONS_DISABLED", "true")
        result = notifications.notify_batch_complete(
            drawing_count=5, success_count=5, failed_count=0,
            total_cost_usd=0.5, total_warnings=2,
        )
        assert result.get("disabled") is True

    def test_is_any_channel_configured_false_by_default(self, monkeypatch):
        for k in ["SLACK_WEBHOOK_URL", "NOTIFICATION_EMAIL", "SMTP_HOST",
                  "SMTP_USER", "SMTP_PASSWORD", "GENERIC_WEBHOOK_URL"]:
            monkeypatch.delenv(k, raising=False)
        assert notifications.is_any_channel_configured() is False

    def test_is_any_channel_configured_true_with_slack(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.com/webhook")
        assert notifications.is_any_channel_configured() is True
