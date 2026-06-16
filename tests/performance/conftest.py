"""Shared fixtures for performance benchmark tests.

Provides large dataset fixtures and timing utilities based on
PRD NFR-001 performance baselines.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def large_ohlcv_df():
    """Generate a large OHLCV DataFrame: 250 trading days."""
    np.random.seed(42)
    n = 250
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    base_price = 10.0
    # Random walk for realistic price movement
    returns = np.random.normal(0.001, 0.02, n)
    prices = base_price * np.cumprod(1 + returns)

    return pd.DataFrame(
        {
            "date": dates,
            "open": prices * (1 + np.random.uniform(-0.01, 0.01, n)),
            "high": prices * (1 + np.random.uniform(0, 0.03, n)),
            "low": prices * (1 - np.random.uniform(0, 0.03, n)),
            "close": prices,
            "volume": np.random.randint(500000, 5000000, n),
            "amount": np.random.uniform(5e6, 5e7, n),
        }
    )


@pytest.fixture
def multi_stock_ohlcv(large_ohlcv_df):
    """Generate OHLCV data for 100 stocks (for throughput testing)."""
    stocks = {}
    for i in range(100):
        symbol = f"{i:06d}"
        df = large_ohlcv_df.copy()
        # Randomize prices slightly per stock
        factor = 1 + np.random.uniform(-0.5, 2.0)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * factor
        stocks[symbol] = df
    return stocks


@pytest.fixture
def sample_config():
    """Sample configuration dict for config loading tests."""
    return {
        "watchlist": [
            {"symbol": f"{i:06d}", "name": f"Stock{i}", "board": "main"}
            for i in range(100)
        ],
        "data_collection": {
            "daily": {"enabled": True, "start_date": "20230101"},
        },
    }
