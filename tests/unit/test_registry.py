"""Tests for StockRegistry and save_config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import yaml

from src.data.registry import StockRegistry
from src.utils.config import load_config, save_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_STOCK_LIST = pd.DataFrame(
    {
        "code": ["000001", "600519", "300750", "688981", "000858"],
        "name": ["平安银行", "贵州茅台", "宁德时代", "中芯国际", "五粮液"],
    }
)


@pytest.fixture()
def registry() -> StockRegistry:
    """Return a StockRegistry with a pre-populated cache."""
    reg = StockRegistry(ttl_seconds=3600)
    reg._cache = MOCK_STOCK_LIST.copy()
    reg._cache_time = __import__("time").time()
    return reg


# ---------------------------------------------------------------------------
# StockRegistry.search
# ---------------------------------------------------------------------------


class TestRegistrySearch:
    """Tests for StockRegistry.search()."""

    def test_search_by_code_prefix(self, registry: StockRegistry) -> None:
        results = registry.search("6005")
        assert len(results) == 1
        assert results[0]["symbol"] == "600519"
        assert results[0]["name"] == "贵州茅台"
        assert results[0]["board"] == "main"

    def test_search_by_name(self, registry: StockRegistry) -> None:
        results = registry.search("茅台")
        assert len(results) == 1
        assert results[0]["symbol"] == "600519"

    def test_search_empty_query(self, registry: StockRegistry) -> None:
        assert registry.search("") == []
        assert registry.search("   ") == []

    def test_search_no_match(self, registry: StockRegistry) -> None:
        assert registry.search("zzzzz") == []

    def test_search_limit(self, registry: StockRegistry) -> None:
        results = registry.search("0", limit=2)
        assert len(results) <= 2

    def test_search_returns_board(self, registry: StockRegistry) -> None:
        results = registry.search("300750")
        assert len(results) == 1
        assert results[0]["board"] == "chinext"

        results = registry.search("688981")
        assert len(results) == 1
        assert results[0]["board"] == "star"


# ---------------------------------------------------------------------------
# StockRegistry.get_board
# ---------------------------------------------------------------------------


class TestGetBoard:
    """Tests for StockRegistry.get_board()."""

    def test_main_board_sh(self) -> None:
        assert StockRegistry.get_board("600519") == "main"

    def test_main_board_sz(self) -> None:
        assert StockRegistry.get_board("000001") == "main"

    def test_chinext(self) -> None:
        assert StockRegistry.get_board("300750") == "chinext"

    def test_star(self) -> None:
        assert StockRegistry.get_board("688981") == "star"


# ---------------------------------------------------------------------------
# StockRegistry.get_stock_info
# ---------------------------------------------------------------------------


class TestGetStockInfo:
    """Tests for StockRegistry.get_stock_info()."""

    def test_found(self, registry: StockRegistry) -> None:
        info = registry.get_stock_info("600519")
        assert info is not None
        assert info["name"] == "贵州茅台"
        assert info["board"] == "main"

    def test_not_found(self, registry: StockRegistry) -> None:
        assert registry.get_stock_info("999999") is None


# ---------------------------------------------------------------------------
# save_config round-trip
# ---------------------------------------------------------------------------


class TestSaveConfig:
    """Tests for save_config() and load_config() round-trip."""

    def test_round_trip(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "test.yaml"
        config_file.write_text("foo: bar\n", encoding="utf-8")

        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            original = load_config("test")
            assert original == {"foo": "bar"}

            save_config("test", {"foo": "baz", "list": [1, 2, 3]})

            reloaded = load_config("test")
            assert reloaded["foo"] == "baz"
            assert reloaded["list"] == [1, 2, 3]

            # Verify backup was created
            assert (config_dir / "test.yaml.bak").exists()

    def test_save_unicode(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "stocks.yaml"
        config_file.write_text("watchlist: []\n", encoding="utf-8")

        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            data = {
                "watchlist": [{"symbol": "600519", "name": "贵州茅台", "board": "main"}]
            }
            save_config("stocks", data)

            reloaded = load_config("stocks")
            assert reloaded["watchlist"][0]["name"] == "贵州茅台"

            # Verify Chinese chars are stored as unicode, not escaped
            raw = config_file.read_text(encoding="utf-8")
            assert "贵州茅台" in raw


# ---------------------------------------------------------------------------
# Watchlist add/remove endpoints (integration-style)
# ---------------------------------------------------------------------------


class TestWatchlistEndpoints:
    """Tests for watchlist add/remove API endpoints."""

    @pytest.fixture()
    def _mock_config(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "stocks.yaml"

        initial = {
            "watchlist": [
                {"symbol": "000001", "name": "平安银行", "board": "main"},
            ]
        }
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(initial, f, allow_unicode=True)

        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            yield tmp_path

    def test_add_and_remove(self, _mock_config: Path) -> None:
        config = load_config("stocks")
        watchlist = config.get("watchlist", [])
        assert len(watchlist) == 1

        # Add a stock
        watchlist.append({"symbol": "600519", "name": "贵州茅台", "board": "main"})
        config["watchlist"] = watchlist
        save_config("stocks", config)

        reloaded = load_config("stocks")
        assert len(reloaded["watchlist"]) == 2

        # Remove it
        reloaded["watchlist"] = [
            e for e in reloaded["watchlist"] if e["symbol"] != "600519"
        ]
        save_config("stocks", reloaded)

        final = load_config("stocks")
        assert len(final["watchlist"]) == 1
        assert final["watchlist"][0]["symbol"] == "000001"
