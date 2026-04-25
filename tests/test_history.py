"""
Tests ל-core.history — append/read/aggregate/clear של היסטוריית ניתוחים.

הבדיקות מבודדות לקובץ זמני (monkeypatch על _HISTORY_PATH).
"""
from __future__ import annotations

import pytest

from core import history as hist


@pytest.fixture
def temp_history(tmp_path, monkeypatch):
    """מפנה את _HISTORY_PATH לקובץ זמני, ומחזיר את המודול."""
    temp_file = tmp_path / "history.jsonl"
    monkeypatch.setattr(hist, "_HISTORY_PATH", temp_file)
    yield hist


# ─────────────────────────────────────────────────────────────────
# 1. append + read round-trip
# ─────────────────────────────────────────────────────────────────
class TestAppendAndRead:
    def test_empty_history_returns_empty_list(self, temp_history):
        assert temp_history.read_history() == []

    def test_append_then_read(self, temp_history):
        temp_history.append_history(
            filename="test.pdf", mode="single",
            part_number="AC-001", drawing_count=1,
            warning_count=2, cost_usd=0.05,
        )
        records = temp_history.read_history()
        assert len(records) == 1
        r = records[0]
        assert r["filename"] == "test.pdf"
        assert r["mode"] == "single"
        assert r["part_number"] == "AC-001"
        assert r["warning_count"] == 2
        assert r["cost_usd"] == 0.05
        assert "timestamp" in r

    def test_read_returns_newest_first(self, temp_history):
        temp_history.append_history(filename="first.pdf", mode="single")
        temp_history.append_history(filename="second.pdf", mode="single")
        temp_history.append_history(filename="third.pdf", mode="single")
        records = temp_history.read_history()
        assert [r["filename"] for r in records] == ["third.pdf", "second.pdf", "first.pdf"]

    def test_limit_caps_results(self, temp_history):
        for i in range(10):
            temp_history.append_history(filename=f"f{i}.pdf", mode="single")
        records = temp_history.read_history(limit=3)
        assert len(records) == 3
        # newest 3 should be f9, f8, f7
        assert [r["filename"] for r in records] == ["f9.pdf", "f8.pdf", "f7.pdf"]

    def test_corrupt_lines_are_skipped(self, temp_history, tmp_path):
        # Manually write a corrupt file
        (tmp_path / "history.jsonl").write_text(
            '{"filename": "good.pdf", "mode": "single"}\n'
            'not valid json\n'
            '{"filename": "good2.pdf", "mode": "assembly"}\n',
            encoding="utf-8",
        )
        records = temp_history.read_history()
        assert len(records) == 2
        assert {r["filename"] for r in records} == {"good.pdf", "good2.pdf"}


# ─────────────────────────────────────────────────────────────────
# 2. aggregate_stats
# ─────────────────────────────────────────────────────────────────
class TestAggregateStats:
    def test_empty_returns_zeros(self, temp_history):
        stats = temp_history.aggregate_stats([])
        assert stats["count"] == 0
        assert stats["total_cost_usd"] == 0.0
        assert stats["cache_hit_rate"] == 0.0

    def test_aggregates_correctly(self, temp_history):
        records = [
            {"mode": "single", "cost_usd": 0.05, "cache_hit": False, "review_status": "reviewed"},
            {"mode": "single", "cost_usd": 0.0, "cache_hit": True, "review_status": "pending"},
            {"mode": "assembly", "cost_usd": 0.21, "cache_hit": False, "review_status": "edited"},
        ]
        stats = temp_history.aggregate_stats(records)
        assert stats["count"] == 3
        assert stats["total_cost_usd"] == pytest.approx(0.26)
        assert stats["avg_cost_usd"] == pytest.approx(0.26 / 3, abs=1e-4)
        assert stats["cache_hits"] == 1
        assert stats["cache_hit_rate"] == pytest.approx(1 / 3, abs=0.01)
        assert stats["by_mode"] == {"single": 2, "assembly": 1}
        assert stats["by_review_status"] == {
            "reviewed": 1, "pending": 1, "edited": 1,
        }

    def test_aggregate_reads_from_disk_if_no_arg(self, temp_history):
        temp_history.append_history(
            filename="x.pdf", mode="single", cost_usd=0.10,
        )
        stats = temp_history.aggregate_stats()
        assert stats["count"] == 1
        assert stats["total_cost_usd"] == pytest.approx(0.10)


# ─────────────────────────────────────────────────────────────────
# 3. clear_history
# ─────────────────────────────────────────────────────────────────
class TestClearHistory:
    def test_clear_removes_file_and_returns_count(self, temp_history):
        temp_history.append_history(filename="a.pdf", mode="single")
        temp_history.append_history(filename="b.pdf", mode="single")
        n = temp_history.clear_history()
        assert n == 2
        assert temp_history.read_history() == []

    def test_clear_when_no_file_returns_zero(self, temp_history):
        assert temp_history.clear_history() == 0


# ─────────────────────────────────────────────────────────────────
# 4. Disable via environment variable
# ─────────────────────────────────────────────────────────────────
class TestDisabledViaEnv:
    def test_disabled_skips_append(self, temp_history, monkeypatch):
        monkeypatch.setenv("HISTORY_DISABLED", "true")
        temp_history.append_history(filename="x.pdf", mode="single")
        # File should not be created
        assert temp_history.read_history() == []

    def test_enabled_by_default(self, temp_history):
        # Without env var — appending should work
        temp_history.append_history(filename="x.pdf", mode="single")
        assert len(temp_history.read_history()) == 1


# ─────────────────────────────────────────────────────────────────
# 5. Error handling
# ─────────────────────────────────────────────────────────────────
class TestRobustness:
    def test_append_with_minimal_args(self, temp_history):
        """רק שם קובץ + מצב — שאר הפרמטרים מקבלים defaults."""
        temp_history.append_history(filename="x.pdf", mode="single")
        records = temp_history.read_history()
        assert records[0]["part_number"] == ""
        assert records[0]["drawing_count"] == 1
        assert records[0]["warning_count"] == 0
        assert records[0]["review_status"] == "pending"
        assert records[0]["cost_usd"] == 0.0
        assert records[0]["cache_hit"] is False
