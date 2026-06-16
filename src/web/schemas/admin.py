"""Admin Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiKeyInfo(BaseModel):
    """Masked API key information."""

    provider: str
    label: str
    masked_key: str | None = None
    status: str | None = None
    expires_at: str | None = None
    created_at: str | None = None


class AddKeyRequest(BaseModel):
    """Request body for adding an API key."""

    provider: str
    key: str
    label: str
    expires_at: str | None = None


class UsageDashboard(BaseModel):
    """Usage stats dashboard data."""

    today: dict | None = None
    total_cost_usd: float | None = None
    period_days: int = 7
    providers: dict | None = None


class RoutingConfig(BaseModel):
    """LLM routing configuration."""

    available_providers: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)


class UpdateRoutingRequest(BaseModel):
    """Request to update routing strategy."""

    strategy: str
