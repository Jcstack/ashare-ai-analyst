"""Unified market signal schema for v20.0 Market Intelligence.

Defines the canonical MarketSignal envelope that flows through the entire
signal pipeline: signal generation -> risk overlay -> notification gate -> push.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.web.schemas.versioning import VersionedSchema


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignalType(str, Enum):
    """Canonical signal taxonomy covering all pipeline producers."""

    S1_TREND = "S1_TREND"
    S2_MOMENTUM_SHIFT = "S2_MOMENTUM_SHIFT"
    S3_SENTIMENT = "S3_SENTIMENT"
    S4_ANOMALY = "S4_ANOMALY"
    S5_VOLATILITY = "S5_VOLATILITY"
    S6_CORRELATION_SHIFT = "S6_CORRELATION_SHIFT"
    S7_POLICY_DRIVEN = "S7_POLICY_DRIVEN"
    S8_MACRO_DRIVEN = "S8_MACRO_DRIVEN"
    S9_REGIME_CHANGE = "S9_REGIME_CHANGE"
    S10_BLACK_SWAN = "S10_BLACK_SWAN"
    STOCK_ALERT = "STOCK_ALERT"
    SYSTEM_ALERT = "SYSTEM_ALERT"


class RiskLevel(str, Enum):
    """Portfolio-aware risk classification."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"


class MarketPhase(str, Enum):
    """A-share trading session phases."""

    PRE_OPEN = "PRE_OPEN"
    CALL_AUCTION = "CALL_AUCTION"
    MORNING = "MORNING"
    MIDDAY_BREAK = "MIDDAY_BREAK"
    AFTERNOON = "AFTERNOON"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    POST_CLOSE = "POST_CLOSE"
    CLOSED = "CLOSED"


class PushDecision(str, Enum):
    """Notification gate output — controls delivery urgency."""

    URGENT = "URGENT"
    DIGEST = "DIGEST"
    BLOCK = "BLOCK"
    SUPPRESS = "SUPPRESS"


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------


class SourceReference(BaseModel):
    """Provenance record for a single upstream data source."""

    source_id: str
    provider: str = Field(
        ...,
        description='Data provider, e.g. "akshare", "sina", "xueqiu", "policy_news"',
    )
    data_type: str = Field(
        ..., description='Data category, e.g. "quote", "news", "indicator", "macro"'
    )
    timestamp: datetime
    reliability_score: float = Field(
        ..., ge=0.0, le=1.0, description="Source reliability 0-1"
    )


class RiskContext(BaseModel):
    """Risk overlay enrichment attached before notification delivery."""

    volatility_regime: str = Field(
        ..., description="Volatility regime: low / medium / high"
    )
    circuit_breaker_state: str = Field(
        ...,
        description="Circuit breaker state: NORMAL / DAILY_HALT / WEEKLY_PAUSE / ESCALATED",
    )
    var_1d_95: float | None = Field(None, description="1-day 95% VaR")
    concentration_risk: float | None = Field(
        None, ge=0.0, le=1.0, description="Portfolio concentration risk 0-1"
    )
    macro_regime: str = Field(
        ..., description="Macro regime: risk_on / risk_off / transitioning"
    )
    explanation: str = Field(
        ..., description="Chinese text explaining the current risk level"
    )
    watch_items: list[str] = Field(
        default_factory=list,
        description="Items to monitor — NOT trading instructions",
    )


# ---------------------------------------------------------------------------
# Core signal envelope
# ---------------------------------------------------------------------------


class MarketSignal(VersionedSchema):
    """Canonical signal envelope for the v20.0 intelligence pipeline.

    Every signal produced by signal_library, alert_engine, or
    system_alert_engine is wrapped in this schema before entering
    the notification gate.
    """

    _schema_version: str = "1.0.0"

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_type: SignalType
    timestamp: datetime
    assets: list[str] = Field(..., description='Affected stock codes, e.g. ["600519"]')
    phase: MarketPhase
    confidence_score: float = Field(
        ..., ge=0.0, le=100.0, description="Signal confidence 0-100"
    )

    # Risk
    risk_level: RiskLevel = RiskLevel.LOW
    risk_context: RiskContext | None = Field(
        None, description="Filled by RiskOverlayEngine before push"
    )

    # Provenance
    sources: list[SourceReference] = Field(default_factory=list)
    producer: str = Field(
        ...,
        description='Origin subsystem: "signal_library" | "alert_engine" | "system_alert_engine"',
    )

    # Summaries
    summary_short: str = Field(
        ..., max_length=50, description="Short summary, max 50 chars"
    )
    summary_detailed: str | None = None

    # Multi-source confirmation
    confirmed: bool = False
    confirmation_sources: list[str] = Field(default_factory=list)

    # Manual injection audit trail
    is_injection: bool = False
    injection_reason: str | None = None

    # Data quality metadata
    source_reliability_score: float = Field(
        0.5, ge=0.0, le=1.0, description="Aggregate source reliability 0-1"
    )
    data_freshness_ms: int = Field(0, ge=0, description="Data age in milliseconds")

    # Lineage
    lineage_node_id: str | None = None
