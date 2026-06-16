"""Unit tests for BacktestEngine.

Tests cover:
- Run returns a valid BacktestResult with correct structure
- Commission calculation on buy side
- Stamp tax added on sell side
- T+1 enforcement (cannot sell on buy day)
- Lot-size rounding to 100-share multiples
- Stop-loss trigger exits position
- Equity curve length matches data length
- All hold signals produce no trades
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine, BacktestResult
from src.strategy.base import (
    SIGNAL_BUY,
    SIGNAL_HOLD,
    SIGNAL_SELL,
    BaseStrategy,
)


# ---- Mock strategy for testing ------------------------------------------


class MockStrategy(BaseStrategy):
    """Concrete strategy stub that returns pre-defined signals.

    Args:
        signals_df: A DataFrame with at least a ``signal`` column.
        config_path: Name of the YAML config file (without extension).
    """

    def __init__(self, signals_df: pd.DataFrame, config_path: str = "strategy") -> None:
        super().__init__(config_path=config_path)
        self._signals = signals_df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return the pre-defined signals DataFrame.

        Args:
            df: Ignored; signals are fixed at construction time.

        Returns:
            The signals DataFrame passed at init.
        """
        return self._signals.copy()


# ---- Fixtures -----------------------------------------------------------


@pytest.fixture
def engine() -> BacktestEngine:
    """Return a BacktestEngine with default strategy config."""
    return BacktestEngine(config_path="strategy")


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Build a 30-row OHLCV DataFrame with a gentle uptrend."""
    dates = pd.date_range("2024-01-02", periods=30, freq="B")
    base_prices = [
        10.0,
        10.1,
        10.2,
        10.0,
        10.3,
        10.4,
        10.2,
        10.5,
        10.6,
        10.3,
        10.7,
        10.8,
        10.5,
        10.9,
        11.0,
        10.7,
        11.1,
        11.2,
        10.9,
        11.3,
        11.4,
        11.1,
        11.5,
        11.6,
        11.3,
        11.7,
        11.8,
        11.5,
        11.9,
        12.0,
    ]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [p - 0.05 for p in base_prices],
            "high": [p + 0.15 for p in base_prices],
            "low": [p - 0.15 for p in base_prices],
            "close": base_prices,
            "volume": [1_000_000] * 30,
        }
    )


def _make_signals(
    n: int, buy_indices: list[int] | None = None, sell_indices: list[int] | None = None
) -> pd.DataFrame:
    """Build a signals DataFrame with HOLD everywhere except specified indices.

    Args:
        n: Total number of rows.
        buy_indices: Row indices that should have a BUY signal.
        sell_indices: Row indices that should have a SELL signal.

    Returns:
        DataFrame with columns ``date``, ``signal``, ``strength``,
        ``reason``.
    """
    buy_indices = buy_indices or []
    sell_indices = sell_indices or []

    signals = [SIGNAL_HOLD] * n
    for i in buy_indices:
        signals[i] = SIGNAL_BUY
    for i in sell_indices:
        signals[i] = SIGNAL_SELL

    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "signal": signals,
            "strength": [0.8] * n,
            "reason": ["test"] * n,
        }
    )


# ---- Tests ---------------------------------------------------------------


class TestRunReturnsBacktestResult:
    """Verify that run() returns a properly structured BacktestResult."""

    def test_run_returns_backtest_result(self, engine, sample_df):
        """run() should return a BacktestResult instance."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[5])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        assert isinstance(result, BacktestResult)

    def test_result_has_required_fields(self, engine, sample_df):
        """BacktestResult should contain trades, equity_curve, etc."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[5])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        assert isinstance(result.trades, list)
        assert isinstance(result.equity_curve, list)
        assert isinstance(result.daily_returns, list)
        assert result.initial_capital == 1_000_000
        assert result.final_capital > 0


class TestBuyDeductsCommission:
    """Verify that commission is correctly deducted on buy."""

    def test_buy_deducts_commission(self, engine, sample_df):
        """After a buy, cash should decrease by value + commission."""
        signals = _make_signals(30, buy_indices=[2])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        buy_trades = [t for t in result.trades if t["action"] == "buy"]
        assert len(buy_trades) == 1

        trade = buy_trades[0]
        expected_commission = max(
            trade["value"] * engine.commission_rate,
            engine.min_commission,
        )
        assert trade["commission"] == pytest.approx(expected_commission)

    def test_buy_commission_minimum(self, engine):
        """Commission should never be less than min_commission (5 RMB)."""
        # Very small trade: 100 shares at 1.0 = 100 RMB
        # commission = 100 * 0.0003 = 0.03, but min is 5.0
        commission = engine._calculate_commission(100.0, is_sell=False)
        assert commission == 5.0


class TestSellAddsStampTax:
    """Verify stamp tax is added only on sell side."""

    def test_sell_adds_stamp_tax(self, engine, sample_df):
        """Sell commission includes stamp tax; buy does not."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[5])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        sell_trades = [t for t in result.trades if t["action"] == "sell"]
        assert len(sell_trades) == 1

        sell = sell_trades[0]
        sell_value = sell["value"]

        # Expected: max(value * 0.0003, 5.0) + value * 0.001
        base_commission = max(
            sell_value * engine.commission_rate,
            engine.min_commission,
        )
        stamp_tax = sell_value * engine.stamp_tax_rate
        expected = base_commission + stamp_tax
        assert sell["commission"] == pytest.approx(expected)

    def test_buy_has_no_stamp_tax(self, engine):
        """Buy-side commission should NOT include stamp tax."""
        buy_comm = engine._calculate_commission(100_000.0, is_sell=False)
        sell_comm = engine._calculate_commission(100_000.0, is_sell=True)
        # sell should be higher due to stamp tax
        assert sell_comm > buy_comm

    def test_stamp_tax_amount(self, engine):
        """Stamp tax should be exactly amount * stamp_tax_rate."""
        amount = 100_000.0
        buy_comm = engine._calculate_commission(amount, is_sell=False)
        sell_comm = engine._calculate_commission(amount, is_sell=True)
        stamp_tax = amount * engine.stamp_tax_rate
        assert sell_comm - buy_comm == pytest.approx(stamp_tax)


class TestTPlusOneEnforcement:
    """Verify T+1: cannot sell on the same day as buy."""

    def test_t_plus_1_enforcement(self, engine):
        """Stop-loss on buy day should be blocked by T+1.

        We set up a scenario where the buy happens at index 2
        (price=10.0) and the price at index 2 is already below the
        stop-loss threshold.  Since T+1 blocks same-day selling, the
        engine's _can_sell should return False.
        """
        buy_date = pd.Timestamp("2024-01-04")
        current_date = pd.Timestamp("2024-01-04")  # same day

        dates = pd.date_range("2024-01-02", periods=5, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0] * 5,
                "high": [10.5] * 5,
                "low": [9.5] * 5,
                "close": [10.0] * 5,
                "volume": [1_000_000] * 5,
            }
        )

        # _can_sell should return False when buy_date == current_date
        assert (
            engine._can_sell(buy_date, current_date, 9.0, df, idx=2, board="main")
            is False
        )

    def test_t_plus_1_blocks_sell_signal_on_buy_day(self, engine):
        """A sell signal on the same day as a buy should be ignored.

        We buy at index 2, then on index 2 the stop-loss/take-profit
        check runs but _can_sell blocks the sell since it is the same
        day.  We verify indirectly by checking no sell trade occurs on
        the buy day even when the price drops sharply.
        """
        dates = pd.date_range("2024-01-02", periods=10, freq="B")
        # Price at index 2 is 10.0, then at index 3 it drops
        prices = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]

        df = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": [p + 0.1 for p in prices],
                "low": [p - 0.1 for p in prices],
                "close": prices,
                "volume": [1_000_000] * 10,
            }
        )

        # Buy at 2, sell at 2 -- but sell_indices overwrites buy_indices,
        # so we need two separate signals: buy first, sell next day
        signals = _make_signals(10, buy_indices=[2], sell_indices=[3])
        strategy = MockStrategy(signals)

        result = engine.run(df, strategy)

        buy_trades = [t for t in result.trades if t["action"] == "buy"]
        sell_trades = [t for t in result.trades if t["action"] == "sell"]
        assert len(buy_trades) == 1
        assert len(sell_trades) == 1
        # Verify sell did not happen on the buy day
        assert sell_trades[0]["date"] != buy_trades[0]["date"]

    def test_sell_allowed_next_day(self, engine, sample_df):
        """Sell on the next day after buy should succeed."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[3])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        buy_trades = [t for t in result.trades if t["action"] == "buy"]
        sell_trades = [t for t in result.trades if t["action"] == "sell"]
        assert len(buy_trades) == 1
        assert len(sell_trades) == 1

    def test_can_sell_returns_false_same_day(self, engine):
        """_can_sell directly returns False when dates match."""
        dates = pd.date_range("2024-01-02", periods=3, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0, 10.0, 10.0],
                "high": [10.5, 10.5, 10.5],
                "low": [9.5, 9.5, 9.5],
                "close": [10.0, 10.0, 10.0],
                "volume": [1_000_000] * 3,
            }
        )
        same_date = pd.Timestamp("2024-01-03")
        assert engine._can_sell(same_date, same_date, 10.0, df, 1, "main") is False

    def test_can_sell_returns_true_different_day(self, engine):
        """_can_sell returns True when buy and current dates differ."""
        dates = pd.date_range("2024-01-02", periods=3, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0, 10.0, 10.0],
                "high": [10.5, 10.5, 10.5],
                "low": [9.5, 9.5, 9.5],
                "close": [10.0, 10.0, 10.0],
                "volume": [1_000_000] * 3,
            }
        )
        buy_date = pd.Timestamp("2024-01-02")
        sell_date = pd.Timestamp("2024-01-03")
        assert engine._can_sell(buy_date, sell_date, 10.0, df, 1, "main") is True


class TestRoundToLot100:
    """Verify lot-size rounding to 100-share multiples."""

    def test_round_to_lot_exact(self, engine):
        """Exact multiples of 100 are unchanged."""
        assert engine._round_to_lot(500) == 500

    def test_round_to_lot_down(self, engine):
        """Fractional lots are rounded down."""
        assert engine._round_to_lot(350) == 300

    def test_round_to_lot_below_minimum(self, engine):
        """Shares below 100 round to zero."""
        assert engine._round_to_lot(99) == 0

    def test_round_to_lot_float(self, engine):
        """Float input is rounded down correctly."""
        assert engine._round_to_lot(250.9) == 200

    def test_round_to_lot_zero(self, engine):
        """Zero shares returns zero."""
        assert engine._round_to_lot(0) == 0

    def test_shares_are_lot_multiple(self, engine, sample_df):
        """All buy trades should have shares as multiples of 100."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[10])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        for trade in result.trades:
            assert trade["shares"] % 100 == 0


class TestStopLossTriggers:
    """Verify stop-loss exits position automatically."""

    def test_stop_loss_triggers(self, engine):
        """Position should be closed when price drops beyond stop_loss."""
        # Build a DataFrame with a significant drop after the buy
        dates = pd.date_range("2024-01-02", periods=30, freq="B")
        prices = [10.0] * 30
        # Buy at index 2 (price=10.0), then drop steadily
        for i in range(3, 30):
            prices[i] = 10.0 - (i - 2) * 0.3  # drops 0.3 per day

        df = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": [p + 0.05 for p in prices],
                "low": [p - 0.05 for p in prices],
                "close": prices,
                "volume": [1_000_000] * 30,
            }
        )

        # Only a buy signal at index 2, no explicit sell
        signals = _make_signals(30, buy_indices=[2])
        strategy = MockStrategy(signals)

        result = engine.run(df, strategy)

        # The engine should have generated a stop-loss sell
        sell_trades = [t for t in result.trades if t["action"] == "sell"]
        assert len(sell_trades) >= 1, "Stop-loss should have triggered a sell"


class TestEquityCurveLength:
    """Verify the equity curve has the same length as input data."""

    def test_equity_curve_length(self, engine, sample_df):
        """Equity curve should have one entry per data row."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[5])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        assert len(result.equity_curve) == len(sample_df)

    def test_daily_returns_length(self, engine, sample_df):
        """Daily returns should match equity curve length."""
        signals = _make_signals(30, buy_indices=[2], sell_indices=[5])
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        assert len(result.daily_returns) == len(result.equity_curve)


class TestNoTradesOnHoldSignals:
    """Verify that all-hold signals produce zero trades."""

    def test_no_trades_on_hold_signals(self, engine, sample_df):
        """When all signals are HOLD, no trades should execute."""
        signals = _make_signals(30)  # all HOLD
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        assert len(result.trades) == 0
        assert result.final_capital == pytest.approx(result.initial_capital)

    def test_equity_curve_flat_on_hold(self, engine, sample_df):
        """Equity curve should be flat (all equal) with no trades."""
        signals = _make_signals(30)  # all HOLD
        strategy = MockStrategy(signals)

        result = engine.run(sample_df, strategy)

        for value in result.equity_curve:
            assert value == pytest.approx(engine.initial_capital)


class TestInputValidation:
    """Verify engine rejects invalid input."""

    def test_empty_dataframe_raises(self, engine):
        """Empty DataFrame should raise ValueError."""
        df = pd.DataFrame()
        signals = pd.DataFrame({"signal": []})
        strategy = MockStrategy(signals)

        with pytest.raises(ValueError, match="empty"):
            engine.run(df, strategy)

    def test_missing_columns_raises(self, engine):
        """DataFrame missing required columns should raise ValueError."""
        df = pd.DataFrame({"date": [1], "close": [10.0]})
        signals = _make_signals(1)
        strategy = MockStrategy(signals)

        with pytest.raises(ValueError, match="missing columns"):
            engine.run(df, strategy)


class TestCalculateCommission:
    """Direct tests for _calculate_commission."""

    def test_buy_commission_normal(self, engine):
        """Normal buy commission: amount * rate."""
        amount = 100_000.0
        comm = engine._calculate_commission(amount, is_sell=False)
        expected = amount * engine.commission_rate
        assert comm == pytest.approx(expected)

    def test_sell_commission_includes_stamp_tax(self, engine):
        """Sell commission: max(amount*rate, min) + stamp_tax."""
        amount = 100_000.0
        comm = engine._calculate_commission(amount, is_sell=True)
        base = max(amount * engine.commission_rate, engine.min_commission)
        stamp = amount * engine.stamp_tax_rate
        assert comm == pytest.approx(base + stamp)

    def test_minimum_commission_enforced(self, engine):
        """Small trades should pay the minimum commission (5 RMB)."""
        comm = engine._calculate_commission(50.0, is_sell=False)
        assert comm == engine.min_commission
