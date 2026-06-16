"""User configuration schemas — follows, notification, and investment style preferences.

Part of v20.0 Phase 4: user follows & notification preferences.
Part of v28.0: investment style configuration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class InvestmentStyleConfig(BaseModel):
    """Full investment style configuration for smart stock recommendations."""

    styles: list[str] = Field(
        default_factory=lambda: ["value"],
        description="1-3 style keys (e.g. value, growth, momentum)",
        min_length=1,
        max_length=3,
    )
    sector_preferences: list[str] = Field(
        default_factory=list,
        description="Up to 5 preferred sector names",
        max_length=5,
    )
    blacklist: list[str] = Field(
        default_factory=list, description="Excluded stock symbols"
    )
    session_toggles: dict[str, bool] = Field(
        default_factory=lambda: {
            "pre_market": True,
            "early": True,
            "mid": True,
            "late": True,
            "post_market": True,
        },
        description="Per-session push notification on/off",
    )


class UserFollows(BaseModel):
    """User follow preferences -- 8 dimensions."""

    stocks: list[str] = Field(
        default_factory=list, description="Stock codes (e.g., ['600519', '000858'])"
    )
    sectors: list[str] = Field(default_factory=list, description="Sector names")
    concepts: list[str] = Field(default_factory=list, description="Concept/theme names")
    signal_types: list[str] = Field(
        default_factory=list, description="SignalType values to follow"
    )
    risk_levels: list[str] = Field(
        default_factory=list, description="RiskLevel thresholds"
    )
    keywords: list[str] = Field(default_factory=list, description="Free-text keywords")
    indices: list[str] = Field(default_factory=list, description="Market indices")
    macro_factors: list[str] = Field(
        default_factory=list, description="Macro factors of interest"
    )


class NotificationPrefs(BaseModel):
    """User notification preferences."""

    quiet_hours_start: str = Field(default="22:00", description="HH:MM format")
    quiet_hours_end: str = Field(default="08:00", description="HH:MM format")
    max_daily_notifications: int = Field(default=50, ge=0)
    digest_interval_minutes: int = Field(default=30, ge=1)
    enabled_channels: list[str] = Field(
        default_factory=lambda: ["app"],
        description="Notification channels: app, wecom, dingtalk, telegram",
    )
    min_confidence_threshold: float = Field(default=30.0, ge=0.0, le=100.0)
    diversity_level: str = Field(
        default="medium",
        description="Anti-silo diversity: low, medium, high",
    )
