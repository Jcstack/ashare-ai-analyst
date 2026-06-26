"""Shared test fixtures for the A-share analysis test suite.

Per PRD Section 6.3: Mock external dependencies, use realistic data structures.
"""

import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shared-singleton isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_source_router():
    """Reset the process-wide DataSourceRouter before/after each test.

    Source health is in-memory and shared; resetting keeps tests that exercise
    the fetcher cascade from leaking health state into one another.
    """
    from src.data.source_router import reset_source_router

    reset_source_router()
    yield
    reset_source_router()


# ---------------------------------------------------------------------------
# Database isolation — prevent ALL tests from touching production databases
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _isolate_test_databases(tmp_path_factory):
    """Redirect every SQLite ``_DB_PATH`` to a temp directory.

    This is the safety net that prevents **any** test (unit or e2e) from
    writing to the real ``data/agent.db``, ``data/info_items.db``,
    ``data/recommendations.db``, or ``data/lineage.db``.

    Works regardless of whether the code goes through FastAPI dependency
    injection or directly instantiates a service class.
    """
    tmp = tmp_path_factory.mktemp("testdb")

    # Import all modules that declare a module-level _DB_PATH
    import src.web.services.portfolio_store as _m_ps
    import src.web.services.capital_service as _m_cs
    import src.web.services.trade_service as _m_ts
    import src.web.services.watchlist_service as _m_ws
    import src.web.services.user_config_service as _m_ucs
    import src.web.services.agent_service as _m_as
    import src.web.services.lineage_service as _m_ls
    import src.intelligence_hub.info_store as _m_is
    import src.intelligence_hub.report_store as _m_irs
    import src.intelligence_hub.delivery_tracker as _m_dt
    import src.market_intelligence.signal_store as _m_ss
    import src.market_intelligence.notification_log as _m_nl

    _modules = [
        _m_ps,
        _m_cs,
        _m_ts,
        _m_ws,
        _m_ucs,
        _m_as,
        _m_ls,
        _m_is,
        _m_irs,
        _m_dt,
        _m_ss,
        _m_nl,
    ]

    # Save originals and patch to temp paths
    originals: dict = {}
    for mod in _modules:
        originals[mod] = mod._DB_PATH
        # Preserve the original filename (agent.db / info_items.db / etc.)
        mod._DB_PATH = tmp / mod._DB_PATH.name

    # Clear any @lru_cache singletons that may have captured old paths
    try:
        from src.web import dependencies as _deps

        for name in dir(_deps):
            fn = getattr(_deps, name, None)
            if callable(getattr(fn, "cache_clear", None)):
                fn.cache_clear()
    except Exception:
        pass

    yield

    # Restore originals
    for mod, orig in originals.items():
        mod._DB_PATH = orig


@pytest.fixture
def sample_ohlcv_df():
    """Fixed sample OHLCV data for testing (10 trading days)."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 10.2, 10.1, 10.5, 10.3, 10.8, 10.6, 11.0, 10.9, 11.2],
            "close": [10.1, 10.0, 10.4, 10.2, 10.7, 10.5, 10.9, 10.8, 11.1, 11.0],
            "high": [10.3, 10.3, 10.5, 10.6, 10.8, 10.9, 11.0, 11.1, 11.2, 11.3],
            "low": [9.9, 9.9, 10.0, 10.1, 10.2, 10.4, 10.5, 10.7, 10.8, 10.9],
            "volume": [
                1000000,
                1200000,
                900000,
                1500000,
                1100000,
                1300000,
                1000000,
                1400000,
                1200000,
                1600000,
            ],
            "amount": [1e7, 1.2e7, 9e6, 1.5e7, 1.1e7, 1.3e7, 1e7, 1.4e7, 1.2e7, 1.6e7],
        }
    )


@pytest.fixture
def sample_ohlcv_with_suspension(sample_ohlcv_df):
    """Sample data with a suspended trading day (volume=0)."""
    df = sample_ohlcv_df.copy()
    df.loc[3, "volume"] = 0
    df.loc[3, "amount"] = 0
    return df


@pytest.fixture
def sample_akshare_response():
    """Mock AKShare ak.stock_zh_a_hist() response with Chinese column names."""
    return pd.DataFrame(
        {
            "日期": pd.date_range("2024-01-02", periods=10, freq="B").strftime(
                "%Y-%m-%d"
            ),
            "开盘": [10.0, 10.2, 10.1, 10.5, 10.3, 10.8, 10.6, 11.0, 10.9, 11.2],
            "收盘": [10.1, 10.0, 10.4, 10.2, 10.7, 10.5, 10.9, 10.8, 11.1, 11.0],
            "最高": [10.3, 10.3, 10.5, 10.6, 10.8, 10.9, 11.0, 11.1, 11.2, 11.3],
            "最低": [9.9, 9.9, 10.0, 10.1, 10.2, 10.4, 10.5, 10.7, 10.8, 10.9],
            "成交量": [
                1000000,
                1200000,
                900000,
                1500000,
                1100000,
                1300000,
                1000000,
                1400000,
                1200000,
                1600000,
            ],
            "成交额": [1e7, 1.2e7, 9e6, 1.5e7, 1.1e7, 1.3e7, 1e7, 1.4e7, 1.2e7, 1.6e7],
        }
    )


@pytest.fixture
def sample_stocks_config():
    """Sample stocks.yaml config dict for testing."""
    return {
        "watchlist": [
            {"symbol": "000001", "name": "\u5e73\u5b89\u94f6\u884c", "board": "main"},
            {"symbol": "600519", "name": "\u8d35\u5dde\u8305\u53f0", "board": "main"},
        ],
        "data_collection": {
            "daily": {
                "enabled": True,
                "start_date": "20240101",
                "end_date": "",
                "adjust": "qfq",
            },
            "fundamental": {"enabled": True, "metrics": ["pe_ttm", "pb"]},
            "market": {
                "enabled": True,
                "indices": ["000001", "399001"],
                "northbound": True,
                "margin": True,
            },
        },
        "cache": {
            "enabled": True,
            "directory": "data/raw",
            "ttl_hours": 12,
        },
        "request": {
            "interval_seconds": 0,  # No delay in tests
            "max_retries": 3,
            "retry_delay_seconds": 0,  # No delay in tests
            "timeout_seconds": 10,
        },
    }


# ---------------------------------------------------------------------------
# Prediction Layer Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_prediction_result():
    """Sample Claude prediction output for testing."""
    return {
        "trend": "bullish",
        "signal": "buy",
        "confidence": 0.75,
        "risk_level": "medium",
        "reasoning": [
            "趋势分析: 短期均线上穿长期均线，形成金叉",
            "技术指标分析: MACD柱状图转正，RSI处于中性偏强区间",
            "形态分析: 出现锤子线反转形态",
            "综合研判: 多头信号确认，建议轻仓试探",
        ],
        "target_price_range": {"low": 10.50, "high": 11.80},
        "key_factors": ["均线金叉", "MACD转正", "成交量放大"],
        "risk_warnings": ["大盘调整风险", "板块轮动不确定性"],
    }


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client that returns a preset JSON response."""
    client = MagicMock()
    response = MagicMock()
    response.content = [
        MagicMock(
            text="```json\n"
            '{"trend": "bullish", "signal": "buy", "confidence": 0.75, '
            '"risk_level": "medium", "reasoning": ["趋势向好"], '
            '"target_price_range": {"low": 10.5, "high": 11.8}, '
            '"key_factors": ["均线金叉"], "risk_warnings": ["调整风险"]}\n```'
        )
    ]
    response.usage = MagicMock(input_tokens=100, output_tokens=200)
    client.messages.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# Strategy / Backtest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_strategy_signals():
    """Sample strategy signal DataFrame for testing."""
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "signal": [0, 0, 1, 0, 0, 0, -1, 0, 0, 0],
            "strength": [0, 0, 0.8, 0, 0, 0, 0.6, 0, 0, 0],
            "reason": [
                "",
                "",
                "金叉信号",
                "",
                "",
                "",
                "死叉信号",
                "",
                "",
                "",
            ],
        }
    )


@pytest.fixture
def mock_discord_webhook():
    """Mock requests.post for Discord webhook testing."""
    with patch("src.utils.notifier.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response
        yield mock_post


# ---------------------------------------------------------------------------
# LLM Layer Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_llm_config():
    """Sample config/llm.yaml config dict for testing."""
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
            "openai": {
                "enabled": True,
                "default_model": "gpt-4o",
                "models": {
                    "gpt-4o": {
                        "cost_per_1k_input": 0.0025,
                        "cost_per_1k_output": 0.01,
                        "quality_score": 0.90,
                    },
                },
                "rate_limit": {"requests_per_minute": 60},
            },
        },
        "routing": {
            "default_strategy": "hybrid",
            "hybrid_weights": {"cost": 0.4, "quality": 0.6},
            "fallback_order": ["anthropic", "openai"],
        },
        "consensus": {"enabled": False},
        "key_storage": {"method": "encrypted_file"},
    }


@pytest.fixture
def mock_llm_response():
    """Mock LLMResponse for testing."""
    from src.llm.base import LLMResponse, ProviderName

    return LLMResponse(
        text='{"trend": "bullish", "signal": "buy", "confidence": 0.75}',
        provider=ProviderName.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
        input_tokens=100,
        output_tokens=200,
        latency_ms=500.0,
        cost_usd=0.003,
    )
