"""Shared fixtures for integration tests.

Provides common OHLCV data, config, prediction results, and AKShare
mocks used across all integration test modules.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def realistic_ohlcv_df() -> pd.DataFrame:
    """Generate 60 trading days of realistic OHLCV data.

    Enough rows for moving averages, Bollinger Bands, and
    support/resistance pivot detection to produce meaningful results.
    """
    np.random.seed(42)
    n_days = 60
    dates = pd.date_range("2024-01-02", periods=n_days, freq="B")

    returns = np.random.normal(0.002, 0.02, n_days)
    close = 10.0 * np.cumprod(1 + returns)

    high = close * (1 + np.abs(np.random.normal(0, 0.01, n_days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n_days)))
    open_prices = close * (1 + np.random.normal(0, 0.005, n_days))
    volume = np.random.randint(500_000, 2_000_000, n_days).astype(float)
    amount = volume * close

    return pd.DataFrame(
        {
            "date": dates,
            "open": open_prices,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume.astype(int),
            "amount": amount,
        }
    )


@pytest.fixture
def stocks_config() -> dict:
    """Minimal stocks.yaml config for integration tests."""
    return {
        "watchlist": [
            {"symbol": "000001", "name": "平安银行", "board": "main"},
            {"symbol": "600519", "name": "贵州茅台", "board": "main"},
        ],
        "data_collection": {
            "daily": {
                "enabled": True,
                "start_date": "20240101",
                "end_date": "",
                "adjust": "qfq",
            },
            "market": {
                "enabled": True,
                "indices": ["000001"],
                "northbound": True,
                "margin": True,
            },
        },
        "cache": {
            "enabled": False,
            "directory": "data/raw",
            "ttl_hours": 0,
        },
        "request": {
            "interval_seconds": 0,
            "max_retries": 1,
            "retry_delay_seconds": 0,
            "timeout_seconds": 5,
        },
    }


@pytest.fixture
def prediction_result() -> dict:
    """Sample prediction result matching the output schema."""
    return {
        "trend": "bullish",
        "signal": "buy",
        "confidence": 0.75,
        "risk_level": "medium",
        "reasoning": [
            "趋势分析: 短期均线上穿长期均线",
            "技术指标分析: MACD柱状图转正",
        ],
        "target_price_range": {"low": 10.5, "high": 11.5},
        "key_factors": ["均线金叉", "成交量放大"],
        "risk_warnings": ["大盘调整风险"],
    }


@pytest.fixture
def mock_akshare(realistic_ohlcv_df: pd.DataFrame):
    """Patch ak.stock_zh_a_hist to return realistic OHLCV data."""
    chinese_df = realistic_ohlcv_df.rename(
        columns={
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
        }
    )
    chinese_df["日期"] = chinese_df["日期"].dt.strftime("%Y-%m-%d")

    with patch("akshare.stock_zh_a_hist", return_value=chinese_df) as mock:
        yield mock


PREDICTION_CONFIG: dict = {
    "model": {
        "name": "claude-sonnet-4-5-20250929",
        "max_tokens": 4096,
        "temperature": 0.3,
    },
    "retry": {
        "max_attempts": 1,
        "base_delay_seconds": 0,
        "max_delay_seconds": 0,
    },
    "output_schema": {
        "required_fields": [
            "trend",
            "signal",
            "confidence",
            "risk_level",
            "reasoning",
            "target_price_range",
            "key_factors",
            "risk_warnings",
        ],
    },
}

PROMPT_CONFIG: dict = {
    "output_schema": {
        "required_fields": ["trend", "signal", "confidence"],
    },
}

EVALUATOR_CONFIG: dict = {
    "evaluation": {
        "direction_accuracy_threshold": 0.6,
        "price_range_tolerance": 0.05,
        "min_confidence": 0.5,
    },
}


def make_mock_anthropic_response(prediction_result: dict) -> MagicMock:
    """Build a mock Anthropic API response from a prediction dict."""
    import json

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text=f"```json\n{json.dumps(prediction_result)}\n```")
    ]
    return mock_response


# ---------------------------------------------------------------------------
# LLM Layer Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_llm_config() -> dict:
    """Sample config/llm.yaml for integration tests."""
    return {
        "providers": {
            "anthropic": {
                "enabled": True,
                "default_model": "claude-sonnet-4-5-20250929",
                "models": {
                    "claude-sonnet-4-5-20250929": {
                        "cost_per_1k_input": 0.003,
                        "cost_per_1k_output": 0.015,
                        "quality_score": 0.92,
                    },
                },
                "rate_limit": {"requests_per_minute": 50},
            },
        },
        "routing": {
            "default_strategy": "quality",
            "fallback_order": ["anthropic"],
        },
        "consensus": {"enabled": False},
        "key_storage": {"method": "encrypted_file"},
    }


@pytest.fixture
def mock_llm_router(prediction_result: dict) -> MagicMock:
    """Mock LLMRouter returning prediction results."""
    import json

    from src.llm.base import LLMResponse, ProviderName

    router = MagicMock()
    router.complete.return_value = LLMResponse(
        text=json.dumps(prediction_result, ensure_ascii=False),
        provider=ProviderName.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.003,
    )
    router.available_providers = [ProviderName.ANTHROPIC]
    return router
