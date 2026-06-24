"""Tests for position sizing engine.

Part of v17.0 Risk Engine.
"""

from __future__ import annotations

import numpy as np

from src.risk.position_sizer import PositionSizer, PositionSizingConfig


class TestKellyCriterion:
    def test_positive_edge(self):
        sizer = PositionSizer()
        # Win 60%, avg win 5%, avg loss 3%
        kelly = sizer.kelly_criterion(0.6, 0.05, 0.03)
        assert kelly > 0

    def test_no_edge(self):
        sizer = PositionSizer()
        # Win 50%, equal win/loss → kelly = 0
        kelly = sizer.kelly_criterion(0.5, 0.03, 0.03)
        assert kelly == 0.0

    def test_negative_edge(self):
        sizer = PositionSizer()
        # Win 30%, avg win 3%, avg loss 5% → negative kelly → clamped to 0
        kelly = sizer.kelly_criterion(0.3, 0.03, 0.05)
        assert kelly == 0.0

    def test_zero_loss(self):
        sizer = PositionSizer()
        kelly = sizer.kelly_criterion(0.6, 0.05, 0)
        assert kelly == 0.0

    def test_edge_cases(self):
        sizer = PositionSizer()
        assert sizer.kelly_criterion(0, 0.05, 0.03) == 0.0
        assert sizer.kelly_criterion(1, 0.05, 0.03) == 0.0


class TestVolatilityScale:
    def test_high_vol_reduces_size(self):
        sizer = PositionSizer()
        # Target 15%, realized 30% → scale = 0.5
        scale = sizer.volatility_scale(0.30, 0.15)
        assert abs(scale - 0.5) < 0.01

    def test_low_vol_increases_size(self):
        sizer = PositionSizer()
        # Target 15%, realized 10% → scale = 1.5
        scale = sizer.volatility_scale(0.10, 0.15)
        assert abs(scale - 1.5) < 0.01

    def test_scale_capped_at_2(self):
        sizer = PositionSizer()
        # Very low vol → capped at 2.0
        scale = sizer.volatility_scale(0.01, 0.15)
        assert scale == 2.0

    def test_zero_vol(self):
        sizer = PositionSizer()
        scale = sizer.volatility_scale(0.0)
        assert scale == 1.0


class TestCalculateSize:
    def test_basic_sizing(self):
        sizer = PositionSizer()
        result = sizer.calculate_size(
            symbol="600519",
            portfolio_value=1_000_000,
            current_price=1680.0,
            win_rate=0.6,
            avg_win=0.05,
            avg_loss=0.03,
            realized_vol=0.25,
        )
        assert result.symbol == "600519"
        assert result.recommended_shares >= 0
        assert result.recommended_shares % 100 == 0  # A-share lots
        assert result.recommended_weight <= 0.30  # Max cap

    def test_30pct_cap(self):
        config = PositionSizingConfig(max_single_weight=0.30)
        sizer = PositionSizer(config)
        result = sizer.calculate_size(
            symbol="600519",
            portfolio_value=1_000_000,
            current_price=10.0,
            win_rate=0.9,
            avg_win=0.20,
            avg_loss=0.02,
            realized_vol=0.05,
            # High conviction (strong R/R + confidence) pushes the conviction
            # multiplier to its 2.0 ceiling, so the raw weight far exceeds the
            # 30% cap and the single-position cap must engage.
            rr_ratio=4.0,
            current_confidence=0.9,
        )
        assert result.recommended_weight <= 0.30
        assert result.capped is True

    def test_100_share_lots(self):
        sizer = PositionSizer()
        result = sizer.calculate_size(
            symbol="600519",
            portfolio_value=100_000,
            current_price=1680.0,
            win_rate=0.55,
            avg_win=0.04,
            avg_loss=0.03,
            realized_vol=0.20,
        )
        assert result.recommended_shares % 100 == 0

    def test_negative_kelly_warning(self):
        sizer = PositionSizer()
        result = sizer.calculate_size(
            symbol="600519",
            portfolio_value=1_000_000,
            current_price=100.0,
            win_rate=0.3,
            avg_win=0.02,
            avg_loss=0.05,
        )
        assert any("Kelly" in w for w in result.warnings)

    def test_zero_price(self):
        sizer = PositionSizer()
        result = sizer.calculate_size(
            symbol="000001",
            portfolio_value=1_000_000,
            current_price=0,
            win_rate=0.6,
            avg_win=0.05,
            avg_loss=0.03,
        )
        assert result.recommended_shares == 0
        assert any("股价无效" in w for w in result.warnings)

    def test_vol_from_returns(self):
        sizer = PositionSizer()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 100)

        result = sizer.calculate_size(
            symbol="600519",
            portfolio_value=1_000_000,
            current_price=100.0,
            win_rate=0.6,
            avg_win=0.05,
            avg_loss=0.03,
            returns=returns,
        )
        assert result.vol_adjustment > 0


class TestPortfolioValidation:
    def test_valid_weights(self):
        sizer = PositionSizer()
        warnings = sizer.validate_portfolio_weights(
            {"600519": 0.20, "300750": 0.15, "601318": 0.10}
        )
        assert len(warnings) == 0

    def test_single_position_too_large(self):
        sizer = PositionSizer()
        warnings = sizer.validate_portfolio_weights({"600519": 0.50})
        assert any("单仓上限" in w for w in warnings)

    def test_total_exceeds_leverage(self):
        sizer = PositionSizer()
        warnings = sizer.validate_portfolio_weights(
            {"A": 0.30, "B": 0.30, "C": 0.30, "D": 0.20}
        )
        assert any("总仓位" in w for w in warnings)

    def test_negative_weight(self):
        sizer = PositionSizer()
        warnings = sizer.validate_portfolio_weights({"A": -0.10})
        assert any("负" in w for w in warnings)
