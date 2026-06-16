"""Stock-related Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WatchlistItem(BaseModel):
    """A single stock in the watchlist with latest price info."""

    symbol: str
    name: str
    board: str = "main"
    close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    change: float | None = None
    pct_change: float | None = None
    volume: int | None = None
    date: str | None = None


class StockDetail(BaseModel):
    """Full stock detail including name and board type."""

    symbol: str
    name: str
    board: str = "main"
    close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    change: float | None = None
    pct_change: float | None = None
    volume: int | None = None
    date: str | None = None


class OHLCVRecord(BaseModel):
    """Single OHLCV data point for client-side charting."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class IndicatorsSummary(BaseModel):
    """Latest technical indicator values as a flat dict."""

    values: dict[str, float | None] = Field(default_factory=dict)


class IndicatorsFullRecord(BaseModel):
    """Single row of OHLCV + indicator data for chart overlays."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    indicators: dict[str, float | None] = Field(default_factory=dict)


class PatternDetection(BaseModel):
    """A single detected candlestick pattern."""

    name: str
    value: int


class SupportResistanceLevel(BaseModel):
    """A single support or resistance price level."""

    level: float
    type: str
    touches: int = 0


class RealtimeQuote(BaseModel):
    """Real-time stock quote."""

    symbol: str
    name: str = ""
    price: float | None = None
    change: float | None = None
    pct_change: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None


class StockSearchItem(BaseModel):
    """A single stock search result."""

    symbol: str
    name: str
    board: str = "main"


class IntradayTradesStats(BaseModel):
    """Aggregated buy/sell volume from intraday tick data."""

    buy_volume: float = 0
    sell_volume: float = 0
    neutral_volume: float = 0
    total_volume: float = 0
    buy_ratio: float = 0
    sell_ratio: float = 0
    is_historical: bool = False


class TickRecord(BaseModel):
    """A single intraday tick (trade) record."""

    time: str
    price: float
    volume: int
    change: float | None = None
    direction: str = "neutral"  # "buy" | "sell" | "neutral"


class IntradayTradesSnapshot(BaseModel):
    """Aggregated stats plus recent individual tick records."""

    stats: IntradayTradesStats = Field(default_factory=IntradayTradesStats)
    recent_ticks: list[TickRecord] = Field(default_factory=list)
    is_historical: bool = False


class QuoteSnapshot(BaseModel):
    """Realtime quote data for the composite snapshot."""

    price: float | None = None
    change: float | None = None
    pct_change: float | None = None
    volume: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    amount: float | None = None


class FundFlowSnapshot(BaseModel):
    """Fund flow net amounts from rank API (intraday)."""

    date: str = ""
    main_net: float | None = None
    super_large_net: float | None = None
    large_net: float | None = None
    medium_net: float | None = None
    small_net: float | None = None


class FundFlowDetailSnapshot(BaseModel):
    """Inflow/outflow detail for a single stock."""

    inflow: float | None = None
    outflow: float | None = None
    net: float | None = None


class RealtimeSnapshot(BaseModel):
    """Composite realtime data for a single stock.

    Aggregates quote, trades, fund flow, and fund flow detail into a
    single response to reduce frontend polling requests.
    """

    symbol: str
    timestamp: str
    quote: QuoteSnapshot | None = None
    trades: IntradayTradesSnapshot | None = None
    fund_flow: FundFlowSnapshot | None = None
    fund_flow_detail: FundFlowDetailSnapshot | None = None
