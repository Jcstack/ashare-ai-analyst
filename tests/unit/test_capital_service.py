"""Tests for the capital management service."""

import tempfile
from pathlib import Path

import pytest

from src.web.services.capital_service import (
    COMMISSION_MIN,
    COMMISSION_RATE,
    STAMP_TAX_RATE,
    CapitalService,
    calculate_commission,
    calculate_stamp_tax,
)


def _make_service() -> CapitalService:
    """Create a CapitalService with a temporary database."""
    tmp = tempfile.mkdtemp()
    return CapitalService(db_path=Path(tmp) / "test_agent.db")


# ---------------------------------------------------------------------------
# Fee calculation
# ---------------------------------------------------------------------------


class TestFeeCalculation:
    """Test A-share fee calculations."""

    def test_commission_normal(self):
        """Commission = 0.03% of trade amount."""
        assert calculate_commission(100000) == pytest.approx(100000 * COMMISSION_RATE)

    def test_commission_minimum(self):
        """Commission has a ¥5 minimum."""
        # Small trade where 0.03% < ¥5
        assert calculate_commission(1000) == COMMISSION_MIN

    def test_commission_at_boundary(self):
        """Commission exactly at the ¥5 boundary."""
        # ¥5 / 0.0003 ≈ ¥16,666.67
        boundary = COMMISSION_MIN / COMMISSION_RATE
        assert calculate_commission(boundary) == pytest.approx(COMMISSION_MIN)
        assert calculate_commission(boundary - 1) == COMMISSION_MIN

    def test_stamp_tax(self):
        """Stamp tax = 0.1% of trade amount."""
        assert calculate_stamp_tax(100000) == pytest.approx(100000 * STAMP_TAX_RATE)

    def test_stamp_tax_small_amount(self):
        """Stamp tax on small amount (no minimum)."""
        assert calculate_stamp_tax(1000) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------


class TestDeposit:
    """Test deposit operations."""

    def test_initial_deposit(self):
        """First deposit is recorded as initial_deposit."""
        svc = _make_service()
        tx = svc.deposit(500000)

        assert tx.type == "initial_deposit"
        assert tx.amount == 500000
        assert tx.balance_after == 500000
        assert svc.get_balance() == 500000

    def test_subsequent_deposit(self):
        """Second deposit is recorded as deposit."""
        svc = _make_service()
        svc.deposit(500000)
        tx = svc.deposit(100000)

        assert tx.type == "deposit"
        assert tx.amount == 100000
        assert tx.balance_after == 600000
        assert svc.get_balance() == 600000

    def test_deposit_invalid_amount(self):
        """Deposit with zero or negative amount raises ValueError."""
        svc = _make_service()
        with pytest.raises(ValueError, match="positive"):
            svc.deposit(0)
        with pytest.raises(ValueError, match="positive"):
            svc.deposit(-100)

    def test_deposit_custom_description(self):
        """Deposit with custom description."""
        svc = _make_service()
        tx = svc.deposit(500000, description="年终奖入金")
        assert tx.description == "年终奖入金"

    def test_multiple_deposits(self):
        """Multiple deposits accumulate correctly."""
        svc = _make_service()
        svc.deposit(100000)
        svc.deposit(200000)
        svc.deposit(300000)
        assert svc.get_balance() == 600000


# ---------------------------------------------------------------------------
# Withdrawals
# ---------------------------------------------------------------------------


class TestWithdraw:
    """Test withdrawal operations."""

    def test_basic_withdraw(self):
        """Withdraw from available balance."""
        svc = _make_service()
        svc.deposit(500000)
        tx = svc.withdraw(100000)

        assert tx.type == "withdrawal"
        assert tx.amount == -100000
        assert tx.balance_after == 400000
        assert svc.get_balance() == 400000

    def test_withdraw_exceeds_balance(self):
        """Withdraw more than available balance raises ValueError."""
        svc = _make_service()
        svc.deposit(500000)
        with pytest.raises(ValueError, match="Insufficient"):
            svc.withdraw(600000)

    def test_withdraw_exact_balance(self):
        """Withdraw exact balance leaves zero."""
        svc = _make_service()
        svc.deposit(500000)
        tx = svc.withdraw(500000)
        assert tx.balance_after == 0.0
        assert svc.get_balance() == 0.0

    def test_withdraw_invalid_amount(self):
        """Withdraw zero or negative raises ValueError."""
        svc = _make_service()
        svc.deposit(500000)
        with pytest.raises(ValueError, match="positive"):
            svc.withdraw(0)

    def test_withdraw_from_empty(self):
        """Withdraw from empty account raises ValueError."""
        svc = _make_service()
        with pytest.raises(ValueError, match="Insufficient"):
            svc.withdraw(100)


# ---------------------------------------------------------------------------
# Trade buy
# ---------------------------------------------------------------------------


class TestTradeBuy:
    """Test trade buy settlement."""

    def test_trade_buy_basic(self):
        """Buy deducts gross + commission."""
        svc = _make_service()
        svc.deposit(500000)

        tx = svc.record_trade_buy("t1", "600519", 100, 1920.0)

        gross = 100 * 1920.0
        commission = calculate_commission(gross)
        expected_balance = 500000 - gross - commission

        assert tx.type == "trade_buy"
        assert tx.amount < 0
        assert tx.balance_after == pytest.approx(expected_balance, abs=0.01)
        assert tx.trade_id == "t1"
        assert tx.symbol == "600519"

    def test_trade_buy_commission_in_description(self):
        """Description includes commission amount."""
        svc = _make_service()
        svc.deposit(500000)
        tx = svc.record_trade_buy("t1", "600519", 100, 1920.0)
        assert "佣金" in tx.description

    def test_trade_buy_insufficient_funds(self):
        """Buy exceeding available capital raises ValueError."""
        svc = _make_service()
        svc.deposit(10000)
        with pytest.raises(ValueError, match="Insufficient"):
            svc.record_trade_buy("t1", "600519", 100, 1920.0)

    def test_trade_buy_minimum_commission(self):
        """Small trade uses minimum ¥5 commission."""
        svc = _make_service()
        svc.deposit(100000)
        # Buy 100 shares at ¥1 = ¥100 gross → commission = ¥5 minimum
        tx = svc.record_trade_buy("t1", "000001", 100, 1.0)
        expected = 100000 - 100 - COMMISSION_MIN
        assert tx.balance_after == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# Trade sell
# ---------------------------------------------------------------------------


class TestTradeSell:
    """Test trade sell settlement."""

    def test_trade_sell_basic(self):
        """Sell credits gross - commission - stamp tax."""
        svc = _make_service()
        svc.deposit(500000)

        tx = svc.record_trade_sell("t1", "600519", 100, 2000.0)

        gross = 100 * 2000.0
        commission = calculate_commission(gross)
        stamp_tax = calculate_stamp_tax(gross)
        expected_balance = 500000 + gross - commission - stamp_tax

        assert tx.type == "trade_sell"
        assert tx.amount > 0
        assert tx.balance_after == pytest.approx(expected_balance, abs=0.01)

    def test_trade_sell_description_includes_fees(self):
        """Description includes both commission and stamp tax."""
        svc = _make_service()
        svc.deposit(500000)
        tx = svc.record_trade_sell("t1", "600519", 100, 2000.0)
        assert "佣金" in tx.description
        assert "印花税" in tx.description

    def test_trade_sell_from_zero_balance(self):
        """Sell credits even from zero balance (proceeds come in)."""
        svc = _make_service()
        svc.deposit(0.01)  # need at least initial deposit
        # Manually hack balance to 0 by withdrawing
        svc.withdraw(0.01)
        assert svc.get_balance() == 0.0

        tx = svc.record_trade_sell("t1", "600519", 100, 10.0)
        assert tx.balance_after > 0


# ---------------------------------------------------------------------------
# Balance queries
# ---------------------------------------------------------------------------


class TestBalance:
    """Test balance queries."""

    def test_empty_balance(self):
        """Empty database returns 0 balance."""
        svc = _make_service()
        assert svc.get_balance() == 0.0

    def test_balance_info(self):
        """get_balance_info returns metadata."""
        svc = _make_service()
        info = svc.get_balance_info()
        assert info.available_cash == 0.0
        assert info.total_transactions == 0
        assert info.has_initial_deposit is False

    def test_balance_info_after_deposit(self):
        """Balance info reflects initial deposit."""
        svc = _make_service()
        svc.deposit(500000)
        info = svc.get_balance_info()
        assert info.available_cash == 500000
        assert info.total_transactions == 1
        assert info.has_initial_deposit is True

    def test_breakdown(self):
        """get_breakdown returns structured result."""
        svc = _make_service()
        svc.deposit(500000)
        breakdown = svc.get_breakdown()
        assert breakdown.available_cash == 500000
        assert breakdown.has_initial_deposit is True
        assert breakdown.total_assets >= 500000

    def test_balance_after_mixed_operations(self):
        """Balance correct after deposit + withdraw + trades."""
        svc = _make_service()
        svc.deposit(1000000)
        svc.withdraw(100000)
        svc.record_trade_buy("t1", "600519", 100, 1920.0)
        svc.record_trade_sell("t2", "300750", 200, 250.0)

        # Verify balance chain
        history = svc.get_history(limit=100)
        # Most recent first, so last entry has most recent balance
        assert history[0].balance_after == svc.get_balance()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestHistory:
    """Test transaction history."""

    def test_empty_history(self):
        """Empty database returns empty list."""
        svc = _make_service()
        assert svc.get_history() == []

    def test_history_ordering(self):
        """History is ordered by created_at desc."""
        svc = _make_service()
        svc.deposit(100000)
        svc.deposit(200000)
        svc.withdraw(50000)

        history = svc.get_history()
        assert len(history) == 3
        # Most recent first
        assert history[0].type == "withdrawal"
        assert history[1].type == "deposit"
        assert history[2].type == "initial_deposit"

    def test_history_type_filter(self):
        """Filter history by transaction type."""
        svc = _make_service()
        svc.deposit(500000)
        svc.record_trade_buy("t1", "600519", 100, 100.0)
        svc.record_trade_sell("t2", "600519", 100, 110.0)

        buys = svc.get_history(tx_type="trade_buy")
        assert len(buys) == 1
        assert buys[0].type == "trade_buy"

        sells = svc.get_history(tx_type="trade_sell")
        assert len(sells) == 1

    def test_history_pagination(self):
        """Pagination with limit and offset."""
        svc = _make_service()
        for i in range(5):
            svc.deposit(10000 + i)

        page1 = svc.get_history(limit=2, offset=0)
        page2 = svc.get_history(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id

    def test_transaction_count(self):
        """Count transactions."""
        svc = _make_service()
        assert svc.get_transaction_count() == 0

        svc.deposit(100000)
        svc.withdraw(10000)
        assert svc.get_transaction_count() == 2
        assert svc.get_transaction_count(tx_type="withdrawal") == 1


# ---------------------------------------------------------------------------
# Migration from user_config
# ---------------------------------------------------------------------------


class TestMigration:
    """Test migration from user_config available_capital."""

    def test_migrate_from_config(self):
        """Migrate existing available_capital to initial_deposit."""
        svc = _make_service()

        # Mock UserConfigService
        class MockConfig:
            def __init__(self):
                self._data = {"available_capital": "500000"}

            def get(self, key):
                return self._data.get(key)

            def delete(self, key):
                self._data.pop(key, None)

        config = MockConfig()
        result = svc.maybe_migrate_from_config(config)

        assert result is True
        assert svc.get_balance() == 500000
        assert config.get("available_capital") is None

    def test_no_migrate_if_already_migrated(self):
        """Skip migration if already performed (tracked by _migrations table)."""
        svc = _make_service()

        class MockConfig:
            def __init__(self):
                self._data = {"available_capital": "500000"}

            def get(self, key):
                return self._data.get(key)

            def delete(self, key):
                self._data.pop(key, None)

        config = MockConfig()
        # First call: performs migration
        assert svc.maybe_migrate_from_config(config) is True
        assert svc.get_balance() == 500000

        # Second call: skips because flag is set, even with a new config source
        class MockConfig2:
            def get(self, key):
                return "999999"

            def delete(self, key):
                pass

        assert svc.maybe_migrate_from_config(MockConfig2()) is False
        assert svc.get_balance() == 500000  # unchanged

    def test_no_migrate_if_no_capital(self):
        """No-op if available_capital not set."""
        svc = _make_service()

        class MockConfig:
            def get(self, key):
                return None

            def delete(self, key):
                pass

        result = svc.maybe_migrate_from_config(MockConfig())
        assert result is False
        assert svc.get_balance() == 0.0

    def test_no_migrate_zero_amount(self):
        """No-op if available_capital is 0."""
        svc = _make_service()

        class MockConfig:
            def get(self, key):
                return "0"

            def delete(self, key):
                pass

        result = svc.maybe_migrate_from_config(MockConfig())
        assert result is False
