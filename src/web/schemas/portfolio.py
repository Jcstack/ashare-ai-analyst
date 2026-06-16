"""Portfolio Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PortfolioPosition(BaseModel):
    """A portfolio position for persistence (matches frontend Position type)."""

    id: str
    symbol: str
    name: str
    board: str = "main"
    costPrice: float
    shares: int
    buyDate: str = ""
    note: str | None = None


class PortfolioData(BaseModel):
    """Full portfolio payload for save/load."""

    version: int = 1
    updatedAt: str = ""
    positions: list[PortfolioPosition] = Field(default_factory=list)


class PortfolioPositionInput(BaseModel):
    """A single portfolio position submitted by the frontend."""

    symbol: str
    name: str
    board: str = "main"
    cost_price: float
    shares: int
    buy_date: str | None = None
    current_price: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None


class PortfolioDiagnosisRequest(BaseModel):
    """Request body for portfolio AI diagnosis."""

    positions: list[PortfolioPositionInput]


class PositionAdviceItem(BaseModel):
    """AI advice for a single position."""

    symbol: str
    name: str
    action: str = "hold"
    reason: str = ""
    target_price: float | None = None


class ConcentrationRisk(BaseModel):
    """Portfolio concentration risk assessment."""

    level: str = "low"
    description: str = ""
    top_holdings_pct: float | None = None


class PortfolioDiagnosisResult(BaseModel):
    """Full AI portfolio diagnosis result."""

    status: str = "success"
    health_score: int = 50
    health_label: str = "一般"
    summary: str = ""
    concentration_risk: ConcentrationRisk | None = None
    position_advice: list[PositionAdviceItem] = Field(default_factory=list)
    rebalancing: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    model_used: str | None = None
    message: str | None = None
