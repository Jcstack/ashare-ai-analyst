"""Shared fixtures for data source fallback chain tests.

Provides mock factories for Sina, Xueqiu, adata, yfinance, and AKShare
so each test can simulate various failure/success scenarios.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Sina mock data
# ---------------------------------------------------------------------------


def make_sina_spot_df(symbols: list[str]) -> pd.DataFrame:
    """Build a mock ak.stock_zh_a_spot() DataFrame (Chinese columns)."""
    rows = []
    for sym in symbols:
        rows.append(
            {
                "代码": sym,
                "名称": f"股票{sym}",
                "最新价": 10.50,
                "涨跌额": 0.30,
                "涨跌幅": 2.94,
                "今开": 10.20,
                "最高": 10.80,
                "最低": 10.10,
                "昨收": 10.20,
                "成交量": 1500000,
                "成交额": 1.5e7,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Xueqiu mock data
# ---------------------------------------------------------------------------


def make_xueqiu_response(symbols: list[str]) -> dict:
    """Build a mock Xueqiu batch API JSON response."""
    data = []
    for sym in symbols:
        prefix = "SZ" if sym.startswith(("0", "3")) else "SH"
        data.append(
            {
                "symbol": f"{prefix}{sym}",
                "current": 10.50,
                "chg": 0.30,
                "percent": 2.94,
                "name": f"股票{sym}",
                "high": 10.80,
                "low": 10.10,
                "open": 10.20,
                "last_close": 10.20,
                "volume": 1500000,
                "amount": 1.5e7,
            }
        )
    return {"data": data}


def make_xueqiu_session(symbols: list[str]) -> MagicMock:
    """Create a mock requests.Session that returns Xueqiu data."""
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = make_xueqiu_response(symbols)
    session.get.return_value = resp
    return session


# ---------------------------------------------------------------------------
# adata mock data
# ---------------------------------------------------------------------------


def make_adata_df(symbols: list[str]) -> pd.DataFrame:
    """Build a mock adata market current DataFrame."""
    rows = []
    for sym in symbols:
        rows.append(
            {
                "stock_code": sym,
                "short_name": f"股票{sym}",
                "price": 11.20,
                "change": 0.50,
                "change_pct": 4.67,
                "volume": 2000000,
                "amount": 2.2e7,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# yfinance mock data
# ---------------------------------------------------------------------------


def make_yfinance_ticker(symbol: str, price: float = 4500.0) -> MagicMock:
    """Create a mock yfinance Ticker object."""
    ticker = MagicMock()
    ticker.info = {
        "symbol": symbol,
        "regularMarketPrice": price,
        "regularMarketChange": 20.0,
        "regularMarketChangePercent": 0.45,
        "regularMarketPreviousClose": price - 20.0,
        "shortName": f"Index {symbol}",
    }
    hist_df = pd.DataFrame(
        {
            "Open": [price - 10],
            "High": [price + 10],
            "Low": [price - 20],
            "Close": [price],
            "Volume": [1000000],
        },
        index=pd.DatetimeIndex(["2024-01-15"]),
    )
    ticker.history.return_value = hist_df
    return ticker


# ---------------------------------------------------------------------------
# AKShare index mock data
# ---------------------------------------------------------------------------


def make_akshare_index_df() -> pd.DataFrame:
    """Build a mock AKShare index spot DataFrame."""
    return pd.DataFrame(
        [
            {
                "代码": "000001",
                "名称": "上证指数",
                "最新价": 3100.0,
                "涨跌额": 15.0,
                "涨跌幅": 0.49,
            }
        ]
    )


# ---------------------------------------------------------------------------
# Realtime config fixtures
# ---------------------------------------------------------------------------

SAMPLE_STOCKS_CONFIG: dict = {
    "data_sources": {
        "proxy_blocked_domains": [],
        "preferred_realtime": "sina",
        "fallback_enabled": True,
    },
}

SAMPLE_AGENT_CONFIG: dict = {
    "realtime": {
        "cache_ttl_seconds": 5,
        "batch_size": 50,
        "rate_limit_per_second": 100,
    },
}


@pytest.fixture
def stocks_config():
    return SAMPLE_STOCKS_CONFIG.copy()


@pytest.fixture
def agent_config():
    return SAMPLE_AGENT_CONFIG.copy()
