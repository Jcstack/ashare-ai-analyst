"""Market data Pydantic models (dragon-tiger, limit-up, indices, hot rank)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DragonTigerItem(BaseModel):
    """Dragon-tiger list entry."""

    rank: int | None = None
    symbol: str
    name: str
    date: str | None = None
    reason: str | None = None
    close: float | None = None
    pct_change: float | None = None
    net_buy: float | None = None
    buy_amount: float | None = None
    sell_amount: float | None = None
    total_amount: float | None = None
    turnover: float | None = None
    float_mv: float | None = None


class LimitUpItem(BaseModel):
    """Limit-up pool entry."""

    rank: int | None = None
    symbol: str
    name: str
    pct_change: float | None = None
    price: float | None = None
    amount: float | None = None
    float_mv: float | None = None
    total_mv: float | None = None
    turnover: float | None = None
    seal_amount: float | None = None
    first_seal_time: str | None = None
    last_seal_time: str | None = None
    break_count: int | None = None
    consecutive: int | None = None
    industry: str | None = None


class MarketIndex(BaseModel):
    """Major market index data point."""

    name: str
    code: str
    price: float
    change: float
    pct_change: float


class HotRankItem(BaseModel):
    """Hot stock ranking entry."""

    rank: int = 0
    symbol: str
    name: str
    price: float | None = None
    pct_change: float | None = None


class DragonTigerSeatItem(BaseModel):
    """A single dragon-tiger trading seat entry."""

    seat_name: str = ""
    seat_type: str = "普通营业部"
    buy_amount: float | None = None
    sell_amount: float | None = None
    net_amount: float | None = None


class DragonTigerStockStats(BaseModel):
    """Historical dragon-tiger statistics for a stock."""

    appearances_3m: int = 0
    institution_net_buy: float = 0.0
    avg_return_5d: float = 0.0
    win_rate_5d: float = 0.0


class GlobalIndexItem(BaseModel):
    """Global stock market index entry."""

    symbol: str
    name: str
    region: str = ""
    price: float | None = None
    change: float | None = None
    pct_change: float | None = None
    prev_close: float | None = None


class GlobalCommodityItem(BaseModel):
    """Global commodity price entry."""

    symbol: str
    name: str
    unit: str = ""
    price: float | None = None
    change: float | None = None
    pct_change: float | None = None


class GlobalCurrencyItem(BaseModel):
    """Currency exchange rate entry."""

    symbol: str
    name: str
    price: float | None = None
    change: float | None = None
    pct_change: float | None = None


class GlobalMarketSnapshot(BaseModel):
    """Complete global market snapshot."""

    indices: list[GlobalIndexItem] = Field(default_factory=list)
    commodities: list[GlobalCommodityItem] = Field(default_factory=list)
    currencies: list[GlobalCurrencyItem] = Field(default_factory=list)


class TradingCalendarInfo(BaseModel):
    """Trading calendar information for a given date."""

    date: str
    is_trading_day: bool
    current_session: str
    next_trading_day: str
    is_holiday_period: bool
    holiday_name: str | None = None
    holiday_end_date: str | None = None
    days_until_open: int = 0
    is_emergency_closure: bool = False


class DragonTigerAIResult(BaseModel):
    """AI analysis of dragon-tiger data."""

    status: str = "success"
    symbol: str = ""
    summary: str = ""
    signal: str = "neutral"
    confidence: float = 0.0
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    historical_performance: DragonTigerStockStats | None = None
    reasoning: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    model_used: str | None = None
    message: str | None = None
