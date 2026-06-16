"""Unit tests for BaseStrategy abstract base class.

Tests cover:
- ABC instantiation guard
- T+1 sell-on-buy-day validation
- Price limit checks for main board and chinext/star boards
- Lot-size rounding to 100-share multiples
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategy.base import (
    BOARD_CHINEXT,
    BOARD_MAIN,
    BOARD_STAR,
    SIGNAL_BUY,
    SIGNAL_HOLD,
    SIGNAL_SELL,
    BaseStrategy,
)


# ---- Concrete stub for testing the abstract base ----


class _StubStrategy(BaseStrategy):
    """Minimal concrete subclass that satisfies the ABC contract."""

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


# ---- Fixtures -------------------------------------------------------


@pytest.fixture
def strategy():
    """Return a _StubStrategy instance using the default config."""
    return _StubStrategy(config_path="strategy")


@pytest.fixture
def sample_df():
    """Build a small OHLCV DataFrame (5 rows) with known values."""
    dates = pd.date_range("2024-06-03", periods=5, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 10.5, 11.0, 11.5, 12.0],
            "high": [10.6, 11.1, 11.6, 12.1, 12.6],
            "low": [9.8, 10.3, 10.8, 11.3, 11.8],
            "close": [10.5, 11.0, 11.5, 12.0, 12.5],
            "volume": [1_000_000] * 5,
        }
    )


@pytest.fixture
def price_limit_df():
    """DataFrame where row 1 is exactly +10% from row 0."""
    dates = pd.date_range("2024-06-03", periods=3, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 11.0, 11.0],
            "high": [10.5, 11.5, 11.5],
            "low": [9.5, 10.5, 10.5],
            "close": [10.0, 11.0, 11.0],  # +10% at idx=1
            "volume": [1_000_000] * 3,
        }
    )


# ---- Tests -----------------------------------------------------------


class TestBaseStrategyAbstract:
    """Tests for the ABC contract."""

    def test_cannot_instantiate_abstract(self):
        """BaseStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseStrategy()  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self, strategy):
        """A concrete subclass can be created."""
        assert strategy is not None
        assert hasattr(strategy, "generate_signals")


class TestValidateSignalTPlusOne:
    """T+1 rule: cannot sell on the same day as a buy."""

    def test_sell_blocked_on_buy_day(self, strategy, sample_df):
        """A sell signal at the same date as a buy should be invalid."""
        # Simulate a buy at index 2
        buy_valid = strategy.validate_signal(
            SIGNAL_BUY, sample_df, idx=2, board=BOARD_MAIN
        )
        assert buy_valid is True

        # Attempt to sell at index 2 (same day) -- must be blocked
        sell_valid = strategy.validate_signal(
            SIGNAL_SELL, sample_df, idx=2, board=BOARD_MAIN
        )
        assert sell_valid is False

    def test_sell_allowed_next_day(self, strategy, sample_df):
        """A sell on the day after a buy should succeed (T+1 passed)."""
        strategy.validate_signal(SIGNAL_BUY, sample_df, idx=1, board=BOARD_MAIN)

        sell_valid = strategy.validate_signal(
            SIGNAL_SELL, sample_df, idx=2, board=BOARD_MAIN
        )
        assert sell_valid is True

    def test_hold_always_valid(self, strategy, sample_df):
        """HOLD signals are always valid regardless of state."""
        assert (
            strategy.validate_signal(SIGNAL_HOLD, sample_df, idx=0, board=BOARD_MAIN)
            is True
        )


class TestValidateSignalPriceLimit:
    """Price-limit checks per board type."""

    def test_price_limit_main_board_blocks_at_10_percent(
        self, strategy, price_limit_df
    ):
        """A signal at exactly +10% on main board should be blocked."""
        # Row 1 close=11.0, row 0 close=10.0 => +10%
        valid = strategy.validate_signal(
            SIGNAL_BUY, price_limit_df, idx=1, board=BOARD_MAIN
        )
        assert valid is False

    def test_price_limit_chinext_allows_up_to_20_percent(self, strategy):
        """ChiNext allows up to 20%, so +10% should pass."""
        dates = pd.date_range("2024-06-03", periods=2, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.0, 11.0],  # +10%
                "volume": [1_000_000] * 2,
            }
        )
        valid = strategy.validate_signal(SIGNAL_BUY, df, idx=1, board=BOARD_CHINEXT)
        assert valid is True

    def test_price_limit_chinext_blocks_at_20_percent(self, strategy):
        """ChiNext blocks at exactly 20%."""
        dates = pd.date_range("2024-06-03", periods=2, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0, 12.0],
                "high": [10.5, 12.5],
                "low": [9.5, 11.5],
                "close": [10.0, 12.0],  # +20%
                "volume": [1_000_000] * 2,
            }
        )
        valid = strategy.validate_signal(SIGNAL_BUY, df, idx=1, board=BOARD_CHINEXT)
        assert valid is False

    def test_price_limit_star_board_same_as_chinext(self, strategy):
        """STAR board uses the same 20% limit as ChiNext."""
        dates = pd.date_range("2024-06-03", periods=2, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0, 11.5],
                "high": [10.5, 12.0],
                "low": [9.5, 11.0],
                "close": [10.0, 11.5],  # +15% — within 20%
                "volume": [1_000_000] * 2,
            }
        )
        valid = strategy.validate_signal(SIGNAL_BUY, df, idx=1, board=BOARD_STAR)
        assert valid is True

    def test_price_limit_within_range_passes(self, strategy, sample_df):
        """A normal move well within 10% should pass."""
        valid = strategy.validate_signal(SIGNAL_BUY, sample_df, idx=1, board=BOARD_MAIN)
        assert valid is True


class TestCheckPriceLimit:
    """Direct tests for the _check_price_limit helper."""

    def test_within_limit(self, strategy):
        assert strategy._check_price_limit(0.05, BOARD_MAIN) is True

    def test_at_limit_exact(self, strategy):
        assert strategy._check_price_limit(0.10, BOARD_MAIN) is False

    def test_exceeds_limit(self, strategy):
        assert strategy._check_price_limit(0.12, BOARD_MAIN) is False

    def test_negative_at_limit(self, strategy):
        assert strategy._check_price_limit(-0.10, BOARD_MAIN) is False

    def test_negative_within_limit(self, strategy):
        assert strategy._check_price_limit(-0.05, BOARD_MAIN) is True

    def test_chinext_limit(self, strategy):
        assert strategy._check_price_limit(0.15, BOARD_CHINEXT) is True
        assert strategy._check_price_limit(0.20, BOARD_CHINEXT) is False

    def test_zero_change(self, strategy):
        assert strategy._check_price_limit(0.0, BOARD_MAIN) is True


class TestRoundToLot:
    """Tests for the _round_to_lot helper."""

    def test_exact_lot(self, strategy):
        assert strategy._round_to_lot(500) == 500

    def test_round_down(self, strategy):
        assert strategy._round_to_lot(350) == 300

    def test_less_than_one_lot(self, strategy):
        assert strategy._round_to_lot(99) == 0

    def test_large_number(self, strategy):
        assert strategy._round_to_lot(1550) == 1500

    def test_float_input(self, strategy):
        assert strategy._round_to_lot(250.7) == 200

    def test_zero(self, strategy):
        assert strategy._round_to_lot(0) == 0
