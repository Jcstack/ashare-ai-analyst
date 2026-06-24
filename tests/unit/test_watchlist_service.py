"""Tests for WatchlistService (SQLite-backed watchlist)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.web.services.watchlist_service import WatchlistService


@pytest.fixture()
def svc(tmp_path: Path) -> WatchlistService:
    """Return a WatchlistService backed by a temp database."""
    db_path = tmp_path / "test.db"
    return WatchlistService(db_path=db_path)


class TestWatchlistCRUD:
    def test_empty_on_start(self, svc: WatchlistService) -> None:
        assert svc.list_all() == []

    def test_add_and_list(self, svc: WatchlistService) -> None:
        item = svc.add("600519", "贵州茅台", "沪主板")
        assert item["symbol"] == "600519"
        assert item["name"] == "贵州茅台"
        assert item["board"] == "沪主板"

        items = svc.list_all()
        assert len(items) == 1
        assert items[0]["symbol"] == "600519"

    def test_add_duplicate_is_noop(self, svc: WatchlistService) -> None:
        svc.add("600519", "贵州茅台", "沪主板")
        svc.add("600519", "贵州茅台", "沪主板")
        assert len(svc.list_all()) == 1

    def test_contains(self, svc: WatchlistService) -> None:
        assert not svc.contains("600519")
        svc.add("600519", "贵州茅台")
        assert svc.contains("600519")

    def test_remove(self, svc: WatchlistService) -> None:
        svc.add("600519", "贵州茅台")
        removed = svc.remove("600519")
        assert removed is True
        assert svc.list_all() == []

    def test_remove_nonexistent(self, svc: WatchlistService) -> None:
        removed = svc.remove("999999")
        assert removed is False

    def test_bulk_replace(self, svc: WatchlistService) -> None:
        svc.add("600519", "贵州茅台")
        svc.add("000001", "平安银行")

        new_items = [
            {"symbol": "300750", "name": "宁德时代", "board": "创业板"},
        ]
        result = svc.bulk_replace(new_items)
        assert len(result) == 1
        assert result[0]["symbol"] == "300750"


class TestWatchlistMigration:
    def test_migrate_from_yaml_skips_after_first_run(
        self, svc: WatchlistService
    ) -> None:
        """Migration should only run once, tracked by _migrations table."""
        # First call performs the migration (even if YAML is empty, flag is set)
        svc.maybe_migrate_from_yaml()
        # Second call is a no-op because the flag is already set
        assert svc.maybe_migrate_from_yaml() is False

    def test_migrate_does_not_reseed_after_user_clears_data(
        self, svc: WatchlistService
    ) -> None:
        """Core bug fix: clearing watchlist should NOT trigger re-migration."""
        # Run migration once
        svc.maybe_migrate_from_yaml()
        # User adds and then removes all items
        svc.add("600519", "贵州茅台")
        svc.remove("600519")
        assert svc.list_all() == []
        # Migration must NOT re-run even though table is now empty
        assert svc.maybe_migrate_from_yaml() is False
