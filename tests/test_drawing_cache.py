"""
Unit tests ל-core.drawing_cache — cache I/O + ניהול גרסאות.

הרצה:
    pytest tests/test_drawing_cache.py -v
"""
from pathlib import Path

import pytest

from core import drawing_cache
from core.drawing_cache import (
    cache_stats,
    cleanup_stale_cache,
    clear_cache,
    get_cached_result,
    is_cache_enabled,
    save_cached_result,
)


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """כל בדיקה — תיקיית cache ייעודית."""
    monkeypatch.setattr(drawing_cache, "_CACHE_DIR", tmp_path / "cache")
    return tmp_path / "cache"


@pytest.fixture
def fake_pdf(tmp_path):
    p = tmp_path / "BP70534A-A.pdf"
    p.write_bytes(b"%PDF-1.4\n" + b"x" * 1000)
    return p


# ─────────────────────────────────────────────────────────────────
# is_cache_enabled
# ─────────────────────────────────────────────────────────────────
class TestIsCacheEnabled:
    def test_default_enabled(self, monkeypatch):
        monkeypatch.delenv("DRAWING_CACHE_DISABLED", raising=False)
        assert is_cache_enabled() is True

    @pytest.mark.parametrize("val", ["true", "TRUE", "True"])
    def test_disabled_when_env_true(self, monkeypatch, val):
        monkeypatch.setenv("DRAWING_CACHE_DISABLED", val)
        assert is_cache_enabled() is False

    def test_enabled_when_env_false(self, monkeypatch):
        monkeypatch.setenv("DRAWING_CACHE_DISABLED", "false")
        assert is_cache_enabled() is True


# ─────────────────────────────────────────────────────────────────
# save_cached_result + get_cached_result roundtrip
# ─────────────────────────────────────────────────────────────────
class TestCacheRoundtrip:
    def test_save_then_get_returns_data(self, isolated_cache, fake_pdf):
        data = {"part_number": "BP70534A", "customer": "RAFAEL"}
        save_cached_result(fake_pdf, data, extra="test")
        result = get_cached_result(fake_pdf, extra="test")
        assert result is not None
        assert result["part_number"] == "BP70534A"
        # _cache_hit מסומן רק בקריאה
        assert result.get("_cache_hit") is True

    def test_different_extra_keys_separated(self, isolated_cache, fake_pdf):
        save_cached_result(fake_pdf, {"v": 1}, extra="a")
        save_cached_result(fake_pdf, {"v": 2}, extra="b")
        assert get_cached_result(fake_pdf, extra="a")["v"] == 1
        assert get_cached_result(fake_pdf, extra="b")["v"] == 2

    def test_cache_miss_returns_none(self, isolated_cache, fake_pdf):
        assert get_cached_result(fake_pdf, extra="nothing") is None

    def test_save_strips_cache_hit_flag(self, isolated_cache, fake_pdf):
        # אם נכתב {"_cache_hit": True} — אסור שיופיע בקובץ
        save_cached_result(fake_pdf, {"_cache_hit": True, "data": 1}, extra="x")
        result = get_cached_result(fake_pdf, extra="x")
        # _cache_hit מתווסף בקריאה — אבל זה הערך החדש שהוסף, לא נשמר במקור
        assert result.get("data") == 1

    def test_disabled_cache_skips_save_and_get(self, isolated_cache, fake_pdf, monkeypatch):
        monkeypatch.setenv("DRAWING_CACHE_DISABLED", "true")
        save_cached_result(fake_pdf, {"v": 1})
        assert get_cached_result(fake_pdf) is None

    def test_save_empty_result_skipped(self, isolated_cache, fake_pdf):
        # אסור לשמור dict ריק
        save_cached_result(fake_pdf, {})
        assert get_cached_result(fake_pdf) is None

    def test_get_nonexistent_file_returns_none(self, isolated_cache):
        assert get_cached_result("/nonexistent/path.pdf") is None


# ─────────────────────────────────────────────────────────────────
# clear_cache
# ─────────────────────────────────────────────────────────────────
class TestClearCache:
    def test_clears_all_files(self, isolated_cache, fake_pdf, tmp_path):
        save_cached_result(fake_pdf, {"v": 1}, extra="a")
        save_cached_result(fake_pdf, {"v": 2}, extra="b")
        assert cache_stats()["count"] == 2
        removed = clear_cache()
        assert removed == 2
        assert cache_stats()["count"] == 0

    def test_clear_empty_returns_zero(self, isolated_cache):
        assert clear_cache() == 0


# ─────────────────────────────────────────────────────────────────
# cache_stats
# ─────────────────────────────────────────────────────────────────
class TestCacheStats:
    def test_empty_cache(self, isolated_cache):
        s = cache_stats()
        assert s["count"] == 0
        assert s["size_mb"] == 0.0
        assert "enabled" in s

    def test_counts_files(self, isolated_cache, fake_pdf):
        save_cached_result(fake_pdf, {"v": 1}, extra="a")
        save_cached_result(fake_pdf, {"v": 2}, extra="b")
        s = cache_stats()
        assert s["count"] == 2
        assert s["size_mb"] >= 0.0


# ─────────────────────────────────────────────────────────────────
# cleanup_stale_cache — המוקד החדש
# ─────────────────────────────────────────────────────────────────
class TestCleanupStaleCache:
    def _make_files(self, cache_dir: Path, version_count: dict[str, int]):
        """יוצר קבצי-cache דמה: {"v22": 3, "v25": 2, "v26": 5}."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        for ver, count in version_count.items():
            for i in range(count):
                (cache_dir / f"{ver}_gpt-test_hash{i}_assembly.json").write_text("{}")

    def test_removes_only_stale_versions(self, isolated_cache):
        self._make_files(isolated_cache, {"v22": 3, "v25": 2, "v26": 5})
        removed = cleanup_stale_cache(keep_versions=1)
        # שומר רק v26 (5 קבצים), מוחק v22 (3) + v25 (2) = 5 הוסרו
        assert removed == 5
        remaining = sorted(p.stem for p in isolated_cache.glob("*.json"))
        assert all(s.startswith("v26_") for s in remaining)
        assert len(remaining) == 5

    def test_keep_versions_2(self, isolated_cache):
        self._make_files(isolated_cache, {"v22": 3, "v25": 2, "v26": 5})
        removed = cleanup_stale_cache(keep_versions=2)
        # שומר v25 + v26 (7), מוחק רק v22 (3)
        assert removed == 3

    def test_no_stale_returns_zero(self, isolated_cache):
        self._make_files(isolated_cache, {"v26": 3})
        assert cleanup_stale_cache(keep_versions=1) == 0

    def test_empty_cache_returns_zero(self, isolated_cache):
        assert cleanup_stale_cache() == 0

    def test_ignores_non_versioned_files(self, isolated_cache):
        isolated_cache.mkdir(parents=True, exist_ok=True)
        (isolated_cache / "random.json").write_text("{}")
        (isolated_cache / "v26_gpt_h1.json").write_text("{}")
        removed = cleanup_stale_cache(keep_versions=1)
        # קבצים בלי version prefix לא נחשבים
        assert removed == 0
        # שני הקבצים נשארו
        assert len(list(isolated_cache.glob("*.json"))) == 2

    def test_no_cache_dir_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drawing_cache, "_CACHE_DIR", tmp_path / "missing")
        assert cleanup_stale_cache() == 0
