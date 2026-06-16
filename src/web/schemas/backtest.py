"""Backtest Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyInfo(BaseModel):
    """Available backtest strategy."""

    key: str
    name: str


class BacktestRequest(BaseModel):
    """Request body for running a backtest."""

    symbol: str
    strategy: str
    board: str = "main"


class BacktestMetrics(BaseModel):
    """Backtest performance metrics."""

    values: dict[str, float | str | None] = Field(default_factory=dict)


class BacktestResponse(BaseModel):
    """Full backtest result."""

    status: str
    symbol: str | None = None
    strategy_key: str | None = None
    strategy_name: str | None = None
    board: str | None = None
    metrics: dict | None = None
    report: str | None = None
    trades_count: int | None = None
    equity_curve: list | None = None
    initial_capital: float | None = None
    final_capital: float | None = None
    message: str | None = None


class BacktestInterpretRequest(BaseModel):
    """Request body for AI interpretation of backtest results."""

    symbol: str
    strategy_name: str
    metrics: dict[str, float | str | None] = Field(default_factory=dict)
    trades_count: int | None = None
    initial_capital: float | None = None
    final_capital: float | None = None


class BacktestInterpretResult(BaseModel):
    """AI-generated backtest interpretation."""

    status: str = "success"
    summary: str = ""
    strategy_explain: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    risk_analysis: str = ""
    beginner_tips: str = ""
    message: str | None = None


class StrategyFlowStep(BaseModel):
    """A single node in the strategy flow chart."""

    id: str = ""
    label: str = ""
    type: str = ""
    description: str = ""


class StrategyFlowEdge(BaseModel):
    """An edge in the strategy flow chart."""

    source: str = ""
    target: str = ""
    label: str = ""


class StrategyParam(BaseModel):
    """A configurable strategy parameter."""

    key: str = ""
    label: str = ""
    type: str = "float"
    min: float = 0
    max: float = 100
    step: float = 1
    default: float = 0
    current: float = 0


class StrategyMetadataResponse(BaseModel):
    """Strategy metadata with flow and params."""

    status: str = "success"
    name: str = ""
    description: str = ""
    flow_steps: list[StrategyFlowStep] = Field(default_factory=list)
    flow_edges: list[StrategyFlowEdge] = Field(default_factory=list)
    configurable_params: list[StrategyParam] = Field(default_factory=list)
    message: str | None = None


class TradeSignalItem(BaseModel):
    """A single trading signal from strategy output."""

    date: str = ""
    signal: int = 0
    strength: float = 0.0
    reason: str = ""
    close_price: float = 0.0


class RoundTripItem(BaseModel):
    """A round-trip trade record (buy + sell pair)."""

    buy_date: str = ""
    sell_date: str = ""
    buy_price: float = 0.0
    sell_price: float = 0.0
    shares: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    buy_reason: str = ""
    sell_reason: str = ""


class AttributionData(BaseModel):
    """Attribution analysis data."""

    monthly_pnl: dict[str, float] = Field(default_factory=dict)
    signal_distribution: dict[str, int] = Field(default_factory=dict)
    monthly_win_rates: dict[str, float] = Field(default_factory=dict)


class BacktestRequestV2(BaseModel):
    """Enhanced backtest request with parameter overrides."""

    symbol: str
    strategy: str
    board: str = "main"
    param_overrides: dict[str, int | float] | None = None


class BacktestResponseV2(BaseModel):
    """Enhanced backtest response with signals, round-trips, and attribution."""

    status: str
    symbol: str | None = None
    strategy_key: str | None = None
    strategy_name: str | None = None
    board: str | None = None
    metrics: dict | None = None
    report: str | None = None
    trades_count: int | None = None
    equity_curve: list | None = None
    initial_capital: float | None = None
    final_capital: float | None = None
    signals: list[dict] | None = None
    round_trips: list[dict] | None = None
    dates: list[str] | None = None
    attribution: dict | None = None
    strategy_metadata: dict | None = None
    message: str | None = None
