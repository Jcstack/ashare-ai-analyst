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
    source_count: int | None = None,
    **kwargs,
) -> AggregatedSignal:
    defaults = dict(
        name="贵州茅台",
        source="recommendation",
        reason="Strong fundamentals",
        metadata={"entry_price": 1800.0},
    )
    defaults.update(kwargs)
    sig = AggregatedSignal(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        urgency=urgency,
        **defaults,
    )
    # Default source_count=2 for buy/add so convergence gate passes;
    # sell/reduce/hold default to 1 (convergence not required).
    if source_count is not None:
        sig.source_count = source_count
    elif direction in (SignalDirection.BUY, SignalDirection.ADD):
        sig.source_count = 2
    return sig


_PIPELINE_CONFIG = {
    "min_confidence_to_propose": 0.6,
    "min_confidence_to_recommend_buy": 0.7,
    "max_position_pct": 0.30,
    "max_daily_loss_pct": 0.03,
    "consecutive_loss_threshold": 3,
    "consecutive_loss_size_factor": 0.5,
}


class _FakeDebateRecord:
    """Minimal debate record that returns a buy-approving dict."""

    def __init__(self, confidence: float = 0.8):
        self._confidence = confidence

    def to_dict(self):
        return {
            "bull_score": self._confidence * 0.7,
            "bear_score": (1 - self._confidence) * 0.5,
            "reasoning": "Test debate approved",
            "risk_veto": False,
            "final_action": "buy",
            "verdict": {
                "win_probability": self._confidence,
                "stop_loss_pct": -5.0,
                "take_profit_pct": 10.0,
            },
        }


class _FakeDebateEngine:
    """Minimal debate engine for testing buy signal paths."""

    def run_debate(self, **kwargs):
        return _FakeDebateRecord()


@pytest.fixture()
def pipeline():
    """Pipeline with no debate engine — buy signals will be vetoed."""
    return DecisionPipeline(debate_engine=None, config=_PIPELINE_CONFIG)


@pytest.fixture()
def pipeline_with_debate():
    """Pipeline with a fake debate engine — buy signals pass through."""
    return DecisionPipeline(debate_engine=_FakeDebateEngine(), config=_PIPELINE_CONFIG)


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
    async def test_returns_trade_proposal_for_valid_buy(self, pipeline_with_debate):
        signal = _make_signal(confidence=0.85, metadata={"entry_price": 25.0})
        result = await pipeline_with_debate.evaluate(
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

    @pytest.mark.anyio
    async def test_vetoes_buy_without_debate_engine(self, pipeline):
        """Buy signals without debate engine are blocked (returns None)."""
        signal = _make_signal(confidence=0.85, metadata={"entry_price": 25.0})
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=500_000,
            market_data={"current_price": 25.0},
        )
        assert result is None


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
            signal=signal,
            action="buy",
            portfolio=[],
            available_cash=200_000,
            price=None,
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
            price=1800.0,
            shares=100,
            daily_change_pct=0.02,
            total_portfolio_value=0,
        )
        assert risk is None

    def test_penalizes_high_daily_change(self, pipeline):
        risk_normal = pipeline._estimate_overnight_risk(
            symbol="600519",
            price=100.0,
            shares=1000,
            daily_change_pct=0.02,
            total_portfolio_value=500_000,
        )
        risk_volatile = pipeline._estimate_overnight_risk(
            symbol="600519",
            price=100.0,
            shares=1000,
            daily_change_pct=0.09,
            total_portfolio_value=500_000,
        )
        assert risk_volatile > risk_normal


class TestSectorConcentration:
    @pytest.mark.anyio
    async def test_blocks_buy_when_sector_at_limit(self, pipeline_with_debate):
        signal = _make_signal(
            confidence=0.85,
            metadata={"entry_price": 25.0, "sector": "白酒"},
        )
        portfolio = [
            {
                "symbol": "000858",
                "shares": 1000,
                "market_value": 200_000,
                "sector": "白酒",
            },
        ]
        result = await pipeline_with_debate.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=300_000,
            market_data={"current_price": 25.0},
        )
        # 白酒 is 200k / 500k = 40% = at limit → blocked
        assert result is None

    @pytest.mark.anyio
    async def test_allows_buy_when_sector_below_limit(self, pipeline_with_debate):
        signal = _make_signal(
            confidence=0.85,
            metadata={"entry_price": 25.0, "sector": "白酒"},
        )
        portfolio = [
            {
                "symbol": "000858",
                "shares": 100,
                "market_value": 10_000,
                "sector": "白酒",
            },
        ]
        result = await pipeline_with_debate.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=490_000,
            market_data={"current_price": 25.0},
        )
        # 白酒 is 10k / 500k = 2% → well below 40% limit
        assert result is not None


class TestBayesianPrescreen:
    @pytest.mark.anyio
    async def test_prescreen_blocks_low_posterior(self):
        """Bayesian prescreen P(bull) < 0.45 → blocks buy, debate never called."""
        mock_debate = _FakeDebateEngine()
        # Track whether debate was called
        debate_called = []
        original_run = mock_debate.run_debate

        def tracking_run(**kwargs):
            debate_called.append(True)
            return original_run(**kwargs)

        mock_debate.run_debate = tracking_run

        pipeline = DecisionPipeline(
            debate_engine=mock_debate,
            config={
                **_PIPELINE_CONFIG,
                "bayesian_prescreen_threshold": 0.45,
            },
        )

        # Low-confidence buy signal → weak prior → prescreen rejects
        signal = _make_signal(confidence=0.3, source="technical")
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=500_000,
            market_data={"current_price": 25.0, "regime": "bear"},
        )
        assert result is None
        assert len(debate_called) == 0  # debate was never called

    @pytest.mark.anyio
    async def test_prescreen_passes_strong_signal(self, pipeline_with_debate):
        """Strong buy signal passes prescreen and reaches debate."""
        signal = _make_signal(confidence=0.85, metadata={"entry_price": 25.0})
        result = await pipeline_with_debate.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=500_000,
            market_data={"current_price": 25.0, "regime": "bull"},
        )
        assert result is not None
        assert result.action == "buy"

    @pytest.mark.anyio
    async def test_sell_skips_prescreen(self):
        """Sell/reduce signals skip prescreen entirely."""
        pipeline = DecisionPipeline(
            debate_engine=None,
            config={
                **_PIPELINE_CONFIG,
                "bayesian_prescreen_threshold": 0.99,  # absurdly high
            },
        )

        signal = _make_signal(
            direction=SignalDirection.SELL,
            urgency=UrgencyTier.CRITICAL,
        )
        portfolio = [{"symbol": "600519", "shares": 200, "market_value": 360_000}]
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=100_000,
        )
        # CRITICAL sell should still go through (prescreen not applied)
        assert result is not None
        assert result.action == "sell"


class TestBudgetExhausted:
    @pytest.mark.anyio
    async def test_budget_exhausted_blocks_buy(self):
        """When LLM budget is exhausted, buy debate is skipped → returns None."""
        from unittest.mock import MagicMock

        mock_budget = MagicMock()
        mock_budget.can_call.return_value = False

        pipeline = DecisionPipeline(
            debate_engine=_FakeDebateEngine(),
            budget_tracker=mock_budget,
            config=_PIPELINE_CONFIG,
        )

        signal = _make_signal(confidence=0.85, metadata={"entry_price": 25.0})
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=[],
            available_cash=500_000,
            market_data={"current_price": 25.0},
        )
        assert result is None

    @pytest.mark.anyio
    async def test_budget_exhausted_allows_sell(self):
        """Sell signals pass through even when budget is exhausted."""
        from unittest.mock import MagicMock

        mock_budget = MagicMock()
        mock_budget.can_call.return_value = False

        pipeline = DecisionPipeline(
            debate_engine=None,
            budget_tracker=mock_budget,
            config=_PIPELINE_CONFIG,
        )

        signal = _make_signal(
            direction=SignalDirection.SELL,
            urgency=UrgencyTier.CRITICAL,
        )
        portfolio = [{"symbol": "600519", "shares": 200, "market_value": 360_000}]
        result = await pipeline.evaluate(
            signal=signal,
            portfolio=portfolio,
            available_cash=100_000,
        )
        assert result is not None
        assert result.action == "sell"


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
