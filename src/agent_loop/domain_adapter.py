"""Domain adapter protocol and signal evidence models for convergence-based signal engine.

Defines the DomainAdapter protocol that concrete adapters implement, plus
data models for typed signal evidence and convergence results.

Part of v50.0 Trading Agent OS — Signal Engine refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class SignalDirection(Enum):
    """Direction of a signal evidence piece."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class IndependenceGroup(Enum):
    """Signals in the same group are considered correlated.

    Two signals from different groups provide genuinely independent confirmation.
    Signals within the same group are downweighted (sqrt correction).
    """

    PRICE_DERIVED = "A"  # Technical, intraday patterns (from same OHLCV)
    CAPITAL_FLOW = "B"  # 主力资金, 北向资金, sector flow
    INTELLIGENCE = "C"  # News, policy, events
    MICROSTRUCTURE = "D"  # L2, VPIN, seal data
    MACRO = "E"  # Sector correlation, reflexivity, macro regime
    MARKET_STRUCTURE = "F"  # Leader detection, limit-up analysis


@dataclass
class SignalEvidence:
    """A single piece of evidence from a domain adapter."""

    domain: str
    signal_type: str  # For Bayesian lookup (e.g. "technical/momentum_breakout")
    symbol: str
    direction: SignalDirection
    confidence: float  # 0.0-1.0
    independence_group: IndependenceGroup
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None
    source_description: str = ""


@dataclass
class ConvergenceResult:
    """Result of convergence analysis for a symbol."""

    symbol: str
    direction: SignalDirection
    signals: list[SignalEvidence]
    independence_groups: set[IndependenceGroup]
    converged: bool  # True if 2+ independence groups agree
    convergence_score: float  # Higher = more independent confirmation
    bayesian_posterior: float | None = None


@runtime_checkable
class DomainAdapter(Protocol):
    """Protocol for signal domain adapters.

    Each adapter wraps an existing signal source (technical, capital flow,
    intelligence, etc.) and produces typed :class:`SignalEvidence` objects
    with explicit independence group tags.
    """

    domain: str

    def collect_signals(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list[SignalEvidence]:
        """Collect signals for the given symbols with optional portfolio context."""
        ...

    def get_signal_types(self) -> list[str]:
        """Return signal types this adapter produces (for Bayesian table lookup)."""
        ...
