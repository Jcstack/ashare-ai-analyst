"""Signal-level confirmation gate for v20.0 Market Intelligence Phase 2.

Confirms signals via multi-source agreement before they proceed through the
intelligence pipeline.  This is distinct from the trade-level
``ConfirmationGate`` at ``src/workflow/confirmation_gate.py`` which implements
a multi-stage *trade* approval workflow.

Each ``SignalType`` has a minimum number of upstream sources required before
the signal is considered confirmed.  The gate mutates the ``MarketSignal``
in place, setting ``confirmed`` and ``confirmation_sources``.
"""

from __future__ import annotations

import logging

from src.web.schemas.market_signal import MarketSignal, SignalType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default confirmation rules (SignalType -> minimum source count)
# ---------------------------------------------------------------------------

_DEFAULT_RULES: dict[SignalType, int] = {
    SignalType.S1_TREND: 2,
    SignalType.S2_MOMENTUM_SHIFT: 2,
    SignalType.S3_SENTIMENT: 2,
    SignalType.S4_ANOMALY: 1,
    SignalType.S5_VOLATILITY: 1,
    SignalType.S6_CORRELATION_SHIFT: 0,  # auto-confirm (mathematical computation)
    SignalType.S7_POLICY_DRIVEN: 2,
    SignalType.S8_MACRO_DRIVEN: 2,
    SignalType.S9_REGIME_CHANGE: 2,
    SignalType.STOCK_ALERT: 1,
    SignalType.SYSTEM_ALERT: 0,  # auto-confirm (system-generated)
}

# Signal types that are always auto-confirmed regardless of source count.
_AUTO_CONFIRM_TYPES: frozenset[SignalType] = frozenset(
    {
        SignalType.S6_CORRELATION_SHIFT,
        SignalType.SYSTEM_ALERT,
    }
)


# ---------------------------------------------------------------------------
# SignalConfirmationGate
# ---------------------------------------------------------------------------


class SignalConfirmationGate:
    """Evaluate multi-source agreement for market signals.

    For each ``SignalType`` a minimum number of upstream ``SourceReference``
    entries is required.  Signals that meet the threshold are marked
    ``confirmed = True`` with their ``confirmation_sources`` populated from
    the provider names of the attached sources.

    Certain signal types (``S6_CORRELATION_SHIFT``, ``SYSTEM_ALERT``) are
    auto-confirmed because they are either mathematical computations or
    system-generated events that do not benefit from multi-source
    corroboration.

    Usage::

        gate = SignalConfirmationGate()
        signal = gate.check(signal)
        if signal.confirmed:
            # proceed with high-confidence handling
            ...
    """

    def __init__(self) -> None:
        """Initialize with default confirmation rules per signal type."""
        self._rules: dict[SignalType, int] = dict(_DEFAULT_RULES)

    # -- Core ---------------------------------------------------------------

    def check(self, signal: MarketSignal) -> MarketSignal:
        """Evaluate confirmation rules for the signal type.

        Sets ``signal.confirmed = True/False`` and populates
        ``signal.confirmation_sources`` based on the rules for the signal's
        type.  Returns the (mutated) signal.
        """
        signal_type = signal.signal_type

        # Auto-confirm types always pass.
        if signal_type in _AUTO_CONFIRM_TYPES:
            signal.confirmed = True
            signal.confirmation_sources = [s.provider for s in signal.sources]
            logger.debug(
                "Signal %s (%s) auto-confirmed",
                signal.signal_id,
                signal_type.value,
            )
            return signal

        min_sources = self._rules.get(signal_type, 1)
        source_count = len(signal.sources)

        if source_count >= min_sources:
            signal.confirmed = True
            signal.confirmation_sources = [s.provider for s in signal.sources]
            logger.debug(
                "Signal %s (%s) confirmed: %d/%d sources",
                signal.signal_id,
                signal_type.value,
                source_count,
                min_sources,
            )
        else:
            signal.confirmed = False
            signal.confirmation_sources = []
            logger.debug(
                "Signal %s (%s) NOT confirmed: %d/%d sources",
                signal.signal_id,
                signal_type.value,
                source_count,
                min_sources,
            )

        return signal

    # -- Rule management ----------------------------------------------------

    def get_rules(self) -> dict[str, int]:
        """Return the current confirmation rules as ``{signal_type_value: min_sources}``."""
        return {st.value: count for st, count in self._rules.items()}

    def override_rule(self, signal_type: str, min_sources: int) -> None:
        """Override the minimum source requirement for a signal type.

        Args:
            signal_type: The string value of a ``SignalType`` enum member
                (e.g. ``"S1_TREND"``).
            min_sources: New minimum number of sources required.  Must be >= 0.

        Raises:
            ValueError: If ``signal_type`` is not a valid ``SignalType`` value
                or ``min_sources`` is negative.
        """
        if min_sources < 0:
            raise ValueError(f"min_sources must be >= 0, got {min_sources}")

        try:
            st = SignalType(signal_type)
        except ValueError:
            raise ValueError(
                f"Unknown signal type: {signal_type!r}. "
                f"Valid types: {[t.value for t in SignalType]}"
            ) from None

        self._rules[st] = min_sources
        logger.info(
            "Confirmation rule override: %s now requires %d source(s)",
            signal_type,
            min_sources,
        )
