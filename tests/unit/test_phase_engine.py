"""Tests for PhaseEngine — 8-phase model wrapping TradingCalendar.

Part of v20.0 Market Intelligence Phase 3.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.data.trading_calendar import MarketSession
from src.web.schemas.market_signal import MarketPhase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_phase_engine(session: MarketSession = MarketSession.CLOSED):
    """Build a PhaseEngine with a mocked TradingCalendar.

    The mocked calendar returns the given ``session`` from
    ``current_session()`` and ``True`` from ``is_trading_day()``.
    """
    from src.market_intelligence.phase_engine import PhaseEngine

    mock_calendar = MagicMock()
    mock_calendar.current_session.return_value = session
    mock_calendar.is_trading_day.return_value = True

    with patch(
        "src.market_intelligence.phase_engine.load_config",
        side_effect=FileNotFoundError,
    ):
        engine = PhaseEngine(trading_calendar=mock_calendar)

    return engine, mock_calendar


# ---------------------------------------------------------------------------
# Phase resolution tests
# ---------------------------------------------------------------------------


class TestPhaseEngine:
    """Tests for PhaseEngine.get_current_phase() and related methods."""

    def test_get_current_phase_morning(self):
        """Mock TradingCalendar.current_session()=MORNING -> MarketPhase.MORNING."""
        engine, _ = _make_phase_engine(MarketSession.MORNING)

        now = datetime(2026, 2, 15, 10, 30, 0)
        phase = engine.get_current_phase(now)

        assert phase == MarketPhase.MORNING

    def test_get_current_phase_call_auction(self):
        """Mock session=PRE_MARKET with time=09:20 -> CALL_AUCTION."""
        engine, _ = _make_phase_engine(MarketSession.PRE_MARKET)

        now = datetime(2026, 2, 15, 9, 20, 0)
        phase = engine.get_current_phase(now)

        assert phase == MarketPhase.CALL_AUCTION

    def test_get_current_phase_pre_open(self):
        """Mock session=PRE_MARKET with time=09:10 (before 09:15) -> PRE_OPEN."""
        engine, _ = _make_phase_engine(MarketSession.PRE_MARKET)

        now = datetime(2026, 2, 15, 9, 10, 0)
        phase = engine.get_current_phase(now)

        assert phase == MarketPhase.PRE_OPEN

    def test_get_current_phase_closing_auction(self):
        """Mock session=AFTERNOON with time=14:58 -> CLOSING_AUCTION."""
        engine, _ = _make_phase_engine(MarketSession.AFTERNOON)

        now = datetime(2026, 2, 15, 14, 58, 0)
        phase = engine.get_current_phase(now)

        assert phase == MarketPhase.CLOSING_AUCTION

    def test_get_current_phase_closed(self):
        """Mock session=CLOSED -> MarketPhase.CLOSED."""
        engine, _ = _make_phase_engine(MarketSession.CLOSED)

        now = datetime(2026, 2, 15, 20, 0, 0)
        phase = engine.get_current_phase(now)

        assert phase == MarketPhase.CLOSED

    def test_is_signal_allowed_morning(self):
        """During MORNING phase, all signal types should be allowed."""
        engine, _ = _make_phase_engine(MarketSession.MORNING)

        all_types = [
            "S1_TREND",
            "S2_MOMENTUM_SHIFT",
            "S3_SENTIMENT",
            "S4_ANOMALY",
            "S5_VOLATILITY",
            "S6_CORRELATION_SHIFT",
            "S7_POLICY_DRIVEN",
            "S8_MACRO_DRIVEN",
            "S9_REGIME_CHANGE",
            "STOCK_ALERT",
            "SYSTEM_ALERT",
        ]
        for signal_type in all_types:
            assert engine.is_signal_allowed(signal_type, MarketPhase.MORNING) is True

    def test_is_signal_allowed_closed(self):
        """During CLOSED phase, only SYSTEM_ALERT should be allowed."""
        engine, _ = _make_phase_engine(MarketSession.CLOSED)

        assert engine.is_signal_allowed("SYSTEM_ALERT", MarketPhase.CLOSED) is True
        assert engine.is_signal_allowed("S1_TREND", MarketPhase.CLOSED) is False
        assert engine.is_signal_allowed("S4_ANOMALY", MarketPhase.CLOSED) is False
        assert engine.is_signal_allowed("STOCK_ALERT", MarketPhase.CLOSED) is False

    def test_get_phase_config(self):
        """Verify returned config dict has all expected keys."""
        engine, _ = _make_phase_engine()

        config = engine.get_phase_config(MarketPhase.MORNING)

        expected_keys = {
            "allowed_signal_types",
            "max_push_count",
            "urgency_boost",
            "digest_mode",
        }
        assert set(config.keys()) == expected_keys
        assert isinstance(config["allowed_signal_types"], list)
        assert isinstance(config["max_push_count"], int)
        assert isinstance(config["urgency_boost"], bool)
        assert isinstance(config["digest_mode"], bool)

    def test_phase_info_structure(self):
        """Verify get_phase_info() returns dict with expected keys."""
        engine, mock_calendar = _make_phase_engine(MarketSession.CLOSED)
        # next_trading_day is called for CLOSED phase
        from datetime import date

        mock_calendar.next_trading_day.return_value = date(2026, 2, 16)

        info = engine.get_phase_info()

        expected_keys = {
            "current_phase",
            "next_transition_time",
            "phase_config",
            "is_trading_day",
        }
        assert set(info.keys()) == expected_keys
        assert isinstance(info["current_phase"], str)
        assert isinstance(info["phase_config"], dict)
        assert isinstance(info["is_trading_day"], bool)
