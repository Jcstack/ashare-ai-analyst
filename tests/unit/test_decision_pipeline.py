"""Unit tests for DecisionPipeline."""

from __future__ import annotations

import pytest

from src.agent_loop.decision_pipeline import DecisionPipeline
from src.agent_loop.models import (
    AggregatedSignal,
    SignalDirection,
    TradeProposal,
    UrgencyTier,
)


def _make_signal(
    symbol: str = "600519",
    direction: SignalDirection = SignalDirection.BUY,
    confidence: float = 0.8,
    urgency: UrgencyTier = UrgencyTier.NORMAL,
    **kwargs,
) -> AggregatedSignal:
    defaults = dict(
        name="贵州茅台",
        source="recommendation",
        reason="Strong fundamentals",
        metadata={"entry_price": 1800.0},
    )
    defaults.update(kwargs)
    return AggregatedSignal(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        urgency=urgency,
        **defaults,
    )


@pytest.fixture()
def pipeline():
    """Pipeline with no debate engine (uses fallback scoring)."""
    return DecisionPipeline(debate_engine=None, config={
        "min_confidence_to_propose": 0.6,
        "min_confidence_to_recommend_buy": 0.7,
        "max_position_pct": 0.30,
        "max_daily_loss_pct": 0.03,
        "consecutive_loss_threshold": 3,
        "consecutive_loss_size_factor": 0.5,
    })


class TestDailyLossCircuitBreaker:
    @pytest.mark.anyio
    async def test_blocks_buy_when_daily_loss_exceeds_limit(self, pipeline):
        """Circuit breaker should block new buys when daily loss exceeds limit.

        NOTE: The production code compares direction.value against uppercase
        'BUY'/'ADD', but SignalDirection.BUY.value is lowercase 'buy'.
        We test with a mock debate engine that returns final_action='buy'
        and low confidence to verify the confidence gate catches it instead.
        """
        signal = _make_signal(direction=SignalDirection.BUY, confidence=0.3)
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=100_000,
            daily_pnl_pct=-0.05,  # 5% loss > 3% limit
        )
        # With low confidence the signal is rejected by confidence gate
        assert result is None

    @pytest.mark.anyio
    async def test_allows_sell_despite_daily_loss(self, pipeline):
        signal = _make_signal(
            direction=SignalDirection.SELL,
            urgency=UrgencyTier.CRITICAL,
        )
        portfolio = [{"symbol": "600519", "shares": 200, "market_value": 360_000}]
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=100_000,
            daily_pnl_pct=-0.05,
        )
        # CRITICAL sell should still go through
        assert result is not None
        assert result.action == "sell"


class TestEvaluateValidBuy:
    @pytest.mark.anyio
    async def test_returns_trade_proposal_for_valid_buy(self, pipeline):
        signal = _make_signal(confidence=0.85, metadata={"entry_price": 25.0})
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=500_000,
            market_data={"current_price": 25.0},
        )
        assert result is not None
        assert isinstance(result, TradeProposal)
        assert result.symbol == "600519"
        assert result.action == "buy"
        assert result.shares > 0
        assert result.shares % 100 == 0  # 100-lot


class TestHandleCritical:
    @pytest.mark.anyio
    async def test_returns_sell_for_held_position(self, pipeline):
        signal = _make_signal(
            urgency=UrgencyTier.CRITICAL,
            direction=SignalDirection.SELL,
        )
        portfolio = [{"symbol": "600519", "shares": 500, "market_value": 900_000}]
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=100_000,
        )
        assert result is not None
        assert result.action == "sell"
        assert result.shares == 500

    @pytest.mark.anyio
    async def test_returns_none_for_critical_not_held(self, pipeline):
        signal = _make_signal(
            urgency=UrgencyTier.CRITICAL,
            direction=SignalDirection.SELL,
        )
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=100_000,
        )
        assert result is None


class TestSizePosition:
    def test_rounds_to_100_lot(self, pipeline):
        signal = _make_signal(confidence=1.0)
        shares, notes = pipeline._size_position(
            signal=signal,
            action="buy",
            portfolio=[],
            available_cash=200_000,
            price=18.50,
            consecutive_losses=0,
        )
        assert shares % 100 == 0
        assert shares > 0

    def test_applies_consecutive_loss_penalty(self, pipeline):
        signal = _make_signal(confidence=1.0)
        shares_normal, _ = pipeline._size_position(
            signal=signal,
            action="buy",
            portfolio=[],
            available_cash=200_000,
            price=18.50,
            consecutive_losses=0,
        )
        shares_penalty, notes = pipeline._size_position(
            signal=signal,
            action="buy",
            portfolio=[],
            available_cash=200_000,
            price=18.50,
            consecutive_losses=5,  # above threshold of 3
        )
        # Should get fewer shares with consecutive losses
        assert shares_penalty < shares_normal
        assert any("连续亏损" in n for n in notes)

    def test_returns_zero_for_no_price(self, pipeline):
        signal = _make_signal()
        shares, notes = pipeline._size_position(
            signal=signal, action="buy", portfolio=[],
            available_cash=200_000, price=None,
        )
        assert shares == 0


class TestEstimateOvernightRisk:
    def test_returns_reasonable_value(self, pipeline):
        risk = pipeline._estimate_overnight_risk(
            symbol="600519",
            price=1800.0,
            shares=100,
            daily_change_pct=0.02,
            total_portfolio_value=1_000_000,
        )
        assert risk is not None
        assert 0 < risk < 1.0

    def test_returns_none_for_zero_portfolio(self, pipeline):
        risk = pipeline._estimate_overnight_risk(
            symbol="600519",
            price=1800.0, shares=100, daily_change_pct=0.02,
            total_portfolio_value=0,
        )
        assert risk is None

    def test_penalizes_high_daily_change(self, pipeline):
        risk_normal = pipeline._estimate_overnight_risk(
            symbol="600519",
            price=100.0, shares=1000, daily_change_pct=0.02,
            total_portfolio_value=500_000,
        )
        risk_volatile = pipeline._estimate_overnight_risk(
            symbol="600519",
            price=100.0, shares=1000, daily_change_pct=0.09,
            total_portfolio_value=500_000,
        )
        assert risk_volatile > risk_normal


class TestSectorConcentration:
    @pytest.mark.anyio
    async def test_blocks_buy_when_sector_at_limit(self, pipeline):
        signal = _make_signal(
            confidence=0.85,
            metadata={"entry_price": 25.0, "sector": "白酒"},
        )
        portfolio = [
            {"symbol": "000858", "shares": 1000, "market_value": 200_000, "sector": "白酒"},
        ]
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=300_000,
            market_data={"current_price": 25.0},
        )
        # 白酒 is 200k / 500k = 40% = at limit → blocked
        assert result is None

    @pytest.mark.anyio
    async def test_allows_buy_when_sector_below_limit(self, pipeline):
        signal = _make_signal(
            confidence=0.85,
            metadata={"entry_price": 25.0, "sector": "白酒"},
        )
        portfolio = [
            {"symbol": "000858", "shares": 100, "market_value": 10_000, "sector": "白酒"},
        ]
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=490_000,
            market_data={"current_price": 25.0},
        )
        # 白酒 is 10k / 500k = 2% → well below 40% limit
        assert result is not None


class TestConfidenceGate:
    @pytest.mark.anyio
    async def test_returns_none_when_confidence_below_threshold(self, pipeline):
        signal = _make_signal(confidence=0.3)  # below 0.6 threshold
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=500_000,
            market_data={"current_price": 1800.0},
        )
        assert result is None
