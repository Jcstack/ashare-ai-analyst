"""Tests for NotificationOrchestrator — intelligent signal routing pipeline.

Part of v20.0 Market Intelligence Phase 3.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.market_intelligence.notification_orchestrator import NotificationOrchestrator
from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    PushDecision,
    RiskLevel,
    SignalType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    risk_level: RiskLevel = RiskLevel.LOW,
    confidence_score: float = 50.0,
    phase: MarketPhase = MarketPhase.MORNING,
    assets: list[str] | None = None,
) -> MarketSignal:
    """Build a minimal MarketSignal for testing."""
    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=assets or ["600519"],
        phase=phase,
        confidence_score=confidence_score,
        risk_level=risk_level,
        sources=[],
        producer="test",
        summary_short="test signal",
    )


def _make_orchestrator(
    *,
    phase_allowed: bool = True,
    should_block: bool = False,
    cooldown_seconds: int = 300,
) -> tuple[NotificationOrchestrator, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build an orchestrator with fully mocked dependencies.

    Returns (orchestrator, dispatcher_mock, phase_engine_mock,
             risk_overlay_mock, notification_log_mock).
    """
    dispatcher = MagicMock()
    dispatcher.dispatch.return_value = {"dispatched": 1}

    phase_engine = MagicMock()
    phase_engine.is_signal_allowed.return_value = phase_allowed
    phase_engine.get_phase_config.return_value = {
        "allowed_signal_types": [],
        "max_push_count": 20,
        "urgency_boost": False,
        "digest_mode": False,
    }

    risk_overlay = MagicMock()
    risk_overlay.should_block.return_value = should_block

    notification_log = MagicMock()

    orchestrator = NotificationOrchestrator(
        dispatcher=dispatcher,
        phase_engine=phase_engine,
        risk_overlay=risk_overlay,
        notification_log=notification_log,
        cooldown_seconds=cooldown_seconds,
    )
    return orchestrator, dispatcher, phase_engine, risk_overlay, notification_log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNotificationOrchestrator:
    """Tests for NotificationOrchestrator.process() pipeline."""

    def test_process_urgent_extreme_risk(self):
        """Signal with risk_level=EXTREME should produce URGENT decision."""
        orch, dispatcher, *_ = _make_orchestrator()

        signal = _make_signal(risk_level=RiskLevel.EXTREME)
        result = orch.process(signal)

        assert result["push_decision"] == PushDecision.URGENT.value
        assert result["dispatched"] is True
        dispatcher.dispatch.assert_called_once()

    def test_process_digest_normal(self):
        """Normal signal with moderate confidence should produce DIGEST."""
        orch, dispatcher, *_ = _make_orchestrator()

        signal = _make_signal(risk_level=RiskLevel.LOW, confidence_score=40.0)
        result = orch.process(signal)

        assert result["push_decision"] == PushDecision.DIGEST.value
        dispatcher.dispatch.assert_not_called()

    def test_process_block_should_block(self):
        """When risk_overlay.should_block() returns True -> BLOCK."""
        orch, dispatcher, *_ = _make_orchestrator(should_block=True)

        signal = _make_signal()
        result = orch.process(signal)

        assert result["push_decision"] == PushDecision.BLOCK.value
        assert result["dispatched"] is False
        dispatcher.dispatch.assert_not_called()

    def test_process_suppress_not_allowed(self):
        """When phase_engine.is_signal_allowed() returns False -> SUPPRESS."""
        orch, dispatcher, *_ = _make_orchestrator(phase_allowed=False)

        signal = _make_signal()
        result = orch.process(signal)

        assert result["push_decision"] == PushDecision.SUPPRESS.value
        assert result["dispatched"] is False
        dispatcher.dispatch.assert_not_called()

    def test_cooldown_suppresses_duplicate(self):
        """Process same signal twice within cooldown window -> second is SUPPRESS."""
        orch, _, *_ = _make_orchestrator(cooldown_seconds=300)

        signal = _make_signal(signal_type=SignalType.S4_ANOMALY, assets=["000001"])
        result1 = orch.process(signal)

        # Second signal with same type + asset should be suppressed by cooldown
        signal2 = _make_signal(signal_type=SignalType.S4_ANOMALY, assets=["000001"])
        result2 = orch.process(signal2)

        assert result1["push_decision"] == PushDecision.DIGEST.value
        assert result2["push_decision"] == PushDecision.SUPPRESS.value

    def test_quiet_mode_downgrades_urgent(self):
        """Quiet mode should downgrade URGENT (EXTREME risk) to DIGEST."""
        orch, dispatcher, *_ = _make_orchestrator()
        orch.set_quiet_mode(True)

        signal = _make_signal(risk_level=RiskLevel.EXTREME)
        result = orch.process(signal)

        assert result["push_decision"] == PushDecision.DIGEST.value
        # Should NOT dispatch because it was downgraded to DIGEST
        dispatcher.dispatch.assert_not_called()

    def test_get_stats(self):
        """Process multiple signals and verify stats counts are correct."""
        orch, _, *_ = _make_orchestrator()

        # Process one EXTREME (-> URGENT) and two normal (-> DIGEST)
        orch.process(_make_signal(risk_level=RiskLevel.EXTREME, assets=["600519"]))
        orch.process(
            _make_signal(
                risk_level=RiskLevel.LOW,
                confidence_score=30.0,
                signal_type=SignalType.S3_SENTIMENT,
                assets=["000001"],
            )
        )
        orch.process(
            _make_signal(
                risk_level=RiskLevel.MODERATE,
                confidence_score=40.0,
                signal_type=SignalType.S5_VOLATILITY,
                assets=["000002"],
            )
        )

        stats = orch.get_stats()

        assert stats["total"] == 3
        assert stats["URGENT"] == 1
        assert stats["DIGEST"] == 2
        assert stats["BLOCK"] == 0
        assert stats["SUPPRESS"] == 0

    def test_dispatch_called_for_urgent(self):
        """Verify dispatcher.dispatch() is called with correct args for URGENT."""
        orch, dispatcher, *_ = _make_orchestrator()

        signal = _make_signal(
            risk_level=RiskLevel.EXTREME,
            signal_type=SignalType.S4_ANOMALY,
        )
        result = orch.process(signal)

        assert result["dispatched"] is True
        dispatcher.dispatch.assert_called_once()

        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "S4_ANOMALY"
        assert call_kwargs.kwargs["severity"] == "critical"
