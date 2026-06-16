"""Tests for PortfolioStore (SQLite-backed portfolio + capital validation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.web.services.portfolio_store import PortfolioStore


@pytest.fixture()
def store(tmp_path: Path) -> PortfolioStore:
    """Return a PortfolioStore without capital integration."""
    db_path = tmp_path / "test.db"
    return PortfolioStore(capital_service=None, db_path=db_path)


@pytest.fixture()
def capital_mock() -> MagicMock:
    """Return a mock CapitalService."""
    mock = MagicMock()
    mock.get_balance.return_value = 100_000.0
    mock.record_trade_buy.return_value = MagicMock(model_dump=lambda: {"id": "tx1"})
    mock.record_position_liquidation.return_value = MagicMock(
        model_dump=lambda: {"id": "tx2", "amount": 50000.0}
    )
    return mock


@pytest.fixture()
def store_with_capital(tmp_path: Path, capital_mock: MagicMock) -> PortfolioStore:
    """Return a PortfolioStore with a mock CapitalService."""
    db_path = tmp_path / "test_cap.db"
    return PortfolioStore(capital_service=capital_mock, db_path=db_path)


class TestPortfolioCRUD:
    def test_empty_on_start(self, store: PortfolioStore) -> None:
        assert store.list_positions() == []
        data = store.get_portfolio_data()
        assert data["positions"] == []
        assert data["version"] == 1

    def test_add_and_list(self, store: PortfolioStore) -> None:
        pos = store.add_position(
            symbol="600519",
            name="贵州茅台",
            board="沪主板",
            cost_price=1800.0,
            shares=100,
            buy_date="2025-01-15",
            validate_capital=False,
        )
        assert pos["symbol"] == "600519"
        assert pos["shares"] == 100
        assert pos["cost_price"] == 1800.0

        positions = store.list_positions()
        assert len(positions) == 1

    def test_get_position(self, store: PortfolioStore) -> None:
        pos = store.add_position(
            symbol="600519",
            name="贵州茅台",
            cost_price=1800.0,
            shares=100,
            validate_capital=False,
        )
        fetched = store.get_position(pos["id"])
        assert fetched is not None
        assert fetched["id"] == pos["id"]

    def test_get_nonexistent(self, store: PortfolioStore) -> None:
        assert store.get_position("nonexistent") is None

    def test_update_position(self, store: PortfolioStore) -> None:
        pos = store.add_position(
            symbol="600519",
            name="贵州茅台",
            cost_price=1800.0,
            shares=100,
            validate_capital=False,
        )
        updated = store.update_position(
            pos["id"], {"shares": 200, "cost_price": 1750.0}
        )
        assert updated is not None
        assert updated["shares"] == 200
        assert updated["cost_price"] == 1750.0

    def test_update_nonexistent(self, store: PortfolioStore) -> None:
        assert store.update_position("nonexistent", {"shares": 100}) is None

    def test_remove_position(self, store: PortfolioStore) -> None:
        pos = store.add_position(
            symbol="600519",
            name="贵州茅台",
            cost_price=1800.0,
            shares=100,
            validate_capital=False,
        )
        assert store.remove_position(pos["id"]) is True
        assert store.list_positions() == []

    def test_remove_nonexistent(self, store: PortfolioStore) -> None:
        assert store.remove_position("nonexistent") is False


class TestPortfolioDataFormat:
    def test_get_portfolio_data_camelcase(self, store: PortfolioStore) -> None:
        store.add_position(
            symbol="600519",
            name="贵州茅台",
            cost_price=1800.0,
            shares=100,
            buy_date="2025-01-15",
            validate_capital=False,
        )
        data = store.get_portfolio_data()
        pos = data["positions"][0]
        # Should use camelCase keys matching frontend
        assert "costPrice" in pos
        assert "buyDate" in pos
        assert pos["costPrice"] == 1800.0
        assert pos["buyDate"] == "2025-01-15"

    def test_save_and_load_portfolio_data(self, store: PortfolioStore) -> None:
        payload = {
            "version": 1,
            "updatedAt": "2025-01-15T00:00:00Z",
            "positions": [
                {
                    "id": "600519-123",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "board": "沪主板",
                    "costPrice": 1800.0,
                    "shares": 100,
                    "buyDate": "2025-01-15",
                },
            ],
        }
        store.save_portfolio_data(payload)
        data = store.get_portfolio_data()
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "600519"


class TestCapitalValidation:
    def test_add_with_capital_validation_succeeds(
        self, store_with_capital: PortfolioStore, capital_mock: MagicMock
    ) -> None:
        pos = store_with_capital.add_position(
            symbol="600519",
            name="贵州茅台",
            cost_price=100.0,
            shares=100,
            validate_capital=True,
        )
        assert pos["symbol"] == "600519"
        capital_mock.record_trade_buy.assert_called_once()

    def test_add_with_insufficient_capital_raises(
        self, store_with_capital: PortfolioStore, capital_mock: MagicMock
    ) -> None:
        capital_mock.get_balance.return_value = 10.0  # Very low balance
        capital_mock.record_trade_buy.side_effect = ValueError("Insufficient capital")

        with pytest.raises(ValueError, match="资金不足"):
            store_with_capital.add_position(
                symbol="600519",
                name="贵州茅台",
                cost_price=1800.0,
                shares=100,
                validate_capital=True,
            )

    def test_liquidate_credits_capital(
        self, store_with_capital: PortfolioStore, capital_mock: MagicMock
    ) -> None:
        pos = store_with_capital.add_position(
            symbol="600519",
            name="贵州茅台",
            cost_price=100.0,
            shares=100,
            validate_capital=False,
        )
        tx = store_with_capital.liquidate_position(pos["id"], current_price=110.0)
        assert tx is not None
        capital_mock.record_position_liquidation.assert_called_once_with(
            symbol="600519",
            stock_name="贵州茅台",
            shares=100,
            price=110.0,
        )
        # Position should be deleted
        assert store_with_capital.get_position(pos["id"]) is None

    def test_liquidate_nonexistent_raises(
        self, store_with_capital: PortfolioStore
    ) -> None:
        with pytest.raises(ValueError, match="Position not found"):
            store_with_capital.liquidate_position("nonexistent", 100.0)


class TestMigration:
    def test_migrate_skips_after_first_run(self, store: PortfolioStore) -> None:
        """Migration should only run once, tracked by _migrations table."""
        store.maybe_migrate_from_json()
        assert store.maybe_migrate_from_json() is False

    def test_migrate_does_not_reseed_after_user_clears_data(
        self, store: PortfolioStore
    ) -> None:
        """Core bug fix: clearing positions should NOT trigger re-migration."""
        store.maybe_migrate_from_json()
        # User clears ALL positions (including any migrated ones)
        for pos in store.list_positions():
            store.remove_position(pos["id"])
        assert store.list_positions() == []
        # Migration must NOT re-run even though table is now empty
        assert store.maybe_migrate_from_json() is False
