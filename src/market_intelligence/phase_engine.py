"""PhaseEngine — maps TradingCalendar's 6-value MarketSession to the 8-value MarketPhase model.

Provides phase-aware signal rules that control which signal types are allowed,
notification limits, urgency boosting, and digest batching for each phase of
the A-share trading day.

Phase config is loaded from ``config/phases.yaml`` with built-in defaults as
fallback.  See ``config/phases.yaml`` for the full schema.

Part of v20.0 Market Intelligence Phase 3.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from src.data.trading_calendar import MarketSession, TradingCalendar
from src.utils.config import load_config
from src.utils.logger import get_logger
from src.web.schemas.market_signal import MarketPhase

logger = get_logger("market_intelligence.phase_engine")

# ---------------------------------------------------------------------------
# Time boundaries for sub-phase refinement within TradingCalendar sessions
# ---------------------------------------------------------------------------

_CALL_AUCTION_START = time(9, 15)
_CALL_AUCTION_END = time(9, 25)
_CLOSING_AUCTION_START = time(14, 57)
_CLOSING_AUCTION_END = time(15, 0)

# ---------------------------------------------------------------------------
# Built-in default phase configs (used when config/phases.yaml is absent)
# ---------------------------------------------------------------------------

_ALL_SIGNAL_TYPES: list[str] = [
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

_DEFAULT_PHASE_CONFIGS: dict[str, dict[str, Any]] = {
    "PRE_OPEN": {
        "allowed_signal_types": ["SYSTEM_ALERT", "S8_MACRO_DRIVEN"],
        "max_push_count": 5,
        "urgency_boost": False,
        "digest_mode": True,
    },
    "CALL_AUCTION": {
        "allowed_signal_types": ["S4_ANOMALY", "S5_VOLATILITY", "STOCK_ALERT"],
        "max_push_count": 10,
        "urgency_boost": True,
        "digest_mode": False,
    },
    "MORNING": {
        "allowed_signal_types": list(_ALL_SIGNAL_TYPES),
        "max_push_count": 20,
        "urgency_boost": False,
        "digest_mode": False,
    },
    "MIDDAY_BREAK": {
        "allowed_signal_types": ["S3_SENTIMENT", "S7_POLICY_DRIVEN", "SYSTEM_ALERT"],
        "max_push_count": 5,
        "urgency_boost": False,
        "digest_mode": True,
    },
    "AFTERNOON": {
        "allowed_signal_types": list(_ALL_SIGNAL_TYPES),
        "max_push_count": 20,
        "urgency_boost": False,
        "digest_mode": False,
    },
    "CLOSING_AUCTION": {
        "allowed_signal_types": ["S4_ANOMALY", "S5_VOLATILITY", "STOCK_ALERT"],
        "max_push_count": 10,
        "urgency_boost": True,
        "digest_mode": False,
    },
    "POST_CLOSE": {
        "allowed_signal_types": [
            "S3_SENTIMENT",
            "S7_POLICY_DRIVEN",
            "S8_MACRO_DRIVEN",
            "SYSTEM_ALERT",
        ],
        "max_push_count": 10,
        "urgency_boost": False,
        "digest_mode": True,
    },
    "CLOSED": {
        "allowed_signal_types": ["SYSTEM_ALERT"],
        "max_push_count": 3,
        "urgency_boost": False,
        "digest_mode": True,
    },
}

# ---------------------------------------------------------------------------
# Session-to-phase base mapping (before time-of-day refinement)
# ---------------------------------------------------------------------------

_SESSION_TO_PHASE: dict[MarketSession, MarketPhase] = {
    MarketSession.PRE_MARKET: MarketPhase.PRE_OPEN,
    MarketSession.MORNING: MarketPhase.MORNING,
    MarketSession.LUNCH_BREAK: MarketPhase.MIDDAY_BREAK,
    MarketSession.AFTERNOON: MarketPhase.AFTERNOON,
    MarketSession.AFTER_HOURS: MarketPhase.POST_CLOSE,
    MarketSession.CLOSED: MarketPhase.CLOSED,
}

# ---------------------------------------------------------------------------
# Next-transition time table (approximate boundaries for each phase)
# ---------------------------------------------------------------------------

_PHASE_END_TIMES: dict[MarketPhase, time] = {
    MarketPhase.PRE_OPEN: _CALL_AUCTION_START,
    MarketPhase.CALL_AUCTION: time(9, 30),
    MarketPhase.MORNING: time(11, 30),
    MarketPhase.MIDDAY_BREAK: time(13, 0),
    MarketPhase.AFTERNOON: _CLOSING_AUCTION_START,
    MarketPhase.CLOSING_AUCTION: _CLOSING_AUCTION_END,
    MarketPhase.POST_CLOSE: time(17, 0),
}


class PhaseEngine:
    """Wraps TradingCalendar with 8-phase model and phase-aware signal rules.

    The A-share market has nuanced sub-phases (call auction, closing auction)
    that the 6-value ``MarketSession`` enum does not capture.  ``PhaseEngine``
    adds time-of-day refinement on top of ``TradingCalendar.current_session()``
    to produce the finer-grained 8-value ``MarketPhase`` and associates each
    phase with configurable signal delivery rules.

    Parameters
    ----------
    trading_calendar:
        An existing ``TradingCalendar`` instance.  If *None*, a new one is
        created internally.
    """

    def __init__(self, trading_calendar: TradingCalendar | None = None) -> None:
        """Wraps TradingCalendar with 8-phase model and phase-aware signal rules."""
        self._calendar = trading_calendar or TradingCalendar()
        self._phase_configs = self._load_phase_configs()
        logger.info(
            "PhaseEngine initialized with %d phase configs", len(self._phase_configs)
        )

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_phase_configs(self) -> dict[str, dict[str, Any]]:
        """Load phase configs from ``config/phases.yaml``, falling back to defaults."""
        try:
            raw = load_config("phases")
            phases_raw = raw.get("phases", {})
            if not phases_raw:
                logger.warning("phases.yaml has no 'phases' key; using defaults")
                return dict(_DEFAULT_PHASE_CONFIGS)

            configs: dict[str, dict[str, Any]] = {}
            for phase_name, cfg in phases_raw.items():
                if phase_name not in _DEFAULT_PHASE_CONFIGS:
                    logger.warning("Unknown phase in config: %s — skipping", phase_name)
                    continue
                configs[phase_name] = {
                    "allowed_signal_types": cfg.get(
                        "allowed_signal_types",
                        _DEFAULT_PHASE_CONFIGS[phase_name]["allowed_signal_types"],
                    ),
                    "max_push_count": cfg.get(
                        "max_push_count",
                        _DEFAULT_PHASE_CONFIGS[phase_name]["max_push_count"],
                    ),
                    "urgency_boost": cfg.get(
                        "urgency_boost",
                        _DEFAULT_PHASE_CONFIGS[phase_name]["urgency_boost"],
                    ),
                    "digest_mode": cfg.get(
                        "digest_mode",
                        _DEFAULT_PHASE_CONFIGS[phase_name]["digest_mode"],
                    ),
                }

            # Fill in any phases missing from the YAML with defaults
            for phase_name, default_cfg in _DEFAULT_PHASE_CONFIGS.items():
                if phase_name not in configs:
                    configs[phase_name] = dict(default_cfg)

            return configs

        except FileNotFoundError:
            logger.warning("config/phases.yaml not found; using built-in defaults")
            return dict(_DEFAULT_PHASE_CONFIGS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_current_phase(self, now: datetime | None = None) -> MarketPhase:
        """Determine the current 8-value MarketPhase.

        Uses ``TradingCalendar.current_session()`` for the coarse session,
        then refines with time-of-day checks:

        - **PRE_MARKET** is split into ``PRE_OPEN`` (before 09:15) and
          ``CALL_AUCTION`` (09:15 -- 09:25).
        - **AFTERNOON** is split at 14:57 into ``AFTERNOON`` and
          ``CLOSING_AUCTION``.

        Parameters
        ----------
        now:
            The reference timestamp.  Defaults to ``datetime.now()``.

        Returns
        -------
        MarketPhase
            The current phase of the trading day.
        """
        if now is None:
            now = datetime.now()

        session = self._calendar.current_session(now)
        t = now.time()

        # Refine PRE_MARKET into PRE_OPEN vs CALL_AUCTION
        if session == MarketSession.PRE_MARKET:
            if _CALL_AUCTION_START <= t < _CALL_AUCTION_END:
                return MarketPhase.CALL_AUCTION
            return MarketPhase.PRE_OPEN

        # Refine AFTERNOON into AFTERNOON vs CLOSING_AUCTION
        if session == MarketSession.AFTERNOON:
            if _CLOSING_AUCTION_START <= t < _CLOSING_AUCTION_END:
                return MarketPhase.CLOSING_AUCTION
            return MarketPhase.AFTERNOON

        # All other sessions map directly
        return _SESSION_TO_PHASE[session]

    def get_phase_config(self, phase: MarketPhase) -> dict[str, Any]:
        """Return the signal-delivery config for the given phase.

        Returns
        -------
        dict
            Keys: ``allowed_signal_types`` (list[str]),
            ``max_push_count`` (int), ``urgency_boost`` (bool),
            ``digest_mode`` (bool).
        """
        phase_name = phase.value
        if phase_name in self._phase_configs:
            return dict(self._phase_configs[phase_name])

        # Should never happen if _DEFAULT_PHASE_CONFIGS covers all phases
        logger.error(
            "No config for phase %s; returning restrictive fallback", phase_name
        )
        return {
            "allowed_signal_types": ["SYSTEM_ALERT"],
            "max_push_count": 1,
            "urgency_boost": False,
            "digest_mode": True,
        }

    def is_signal_allowed(self, signal_type: str, phase: MarketPhase) -> bool:
        """Check whether *signal_type* is permitted during *phase*.

        Parameters
        ----------
        signal_type:
            A ``SignalType`` value string, e.g. ``"S4_ANOMALY"``.
        phase:
            The market phase to check against.

        Returns
        -------
        bool
            *True* if the signal type is in the phase's allowed list.
        """
        config = self.get_phase_config(phase)
        return signal_type in config["allowed_signal_types"]

    def get_phase_info(self) -> dict[str, Any]:
        """Return a summary dict describing the current phase state.

        Useful for dashboard widgets and debugging.

        Returns
        -------
        dict
            Keys: ``current_phase`` (str), ``next_transition_time`` (str | None),
            ``phase_config`` (dict), ``is_trading_day`` (bool).
        """
        now = datetime.now()
        current_phase = self.get_current_phase(now)
        config = self.get_phase_config(current_phase)
        next_transition = self._next_transition_time(current_phase, now)

        return {
            "current_phase": current_phase.value,
            "next_transition_time": (
                next_transition.isoformat() if next_transition else None
            ),
            "phase_config": config,
            "is_trading_day": self._calendar.is_trading_day(now.date()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_transition_time(
        self, current_phase: MarketPhase, now: datetime
    ) -> datetime | None:
        """Estimate the next phase transition timestamp.

        Returns *None* for CLOSED (next transition is next trading day open).
        """
        end_time = _PHASE_END_TIMES.get(current_phase)
        if end_time is None:
            # CLOSED — next transition is next trading day's PRE_OPEN (09:00)
            next_day = self._calendar.next_trading_day(now.date())
            return datetime.combine(next_day, time(9, 0))
        return datetime.combine(now.date(), end_time)
