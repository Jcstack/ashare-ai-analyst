"""Comprehensive load & stress test suite for all API endpoints.

Covers 50+ endpoints across 14 categories with:
- Per-endpoint latency profiling (p50/p95/p99)
- Concurrent load testing (10/25/50 workers)
- Stress escalation to find breaking point
- Error rate tracking per endpoint category

Results written to reports/perf-results.json for report generation.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch as _patch

from src.web.routes.api_v1 import router as api_v1_router

# ---------------------------------------------------------------------------
# Module-level result accumulator
# ---------------------------------------------------------------------------

PERF_RESULTS: dict[str, Any] = {
    "endpoints": {},
    "load_tests": {},
    "stress_test": {},
}

# ---------------------------------------------------------------------------
# Mock data constants
# ---------------------------------------------------------------------------

MOCK_WATCHLIST = [
    {"symbol": "000001", "name": "平安银行", "board": "main"},
    {"symbol": "600519", "name": "贵州茅台", "board": "main"},
]

MOCK_OHLCV_DF = pd.DataFrame(
    {
        "date": pd.date_range("2024-01-02", periods=10, freq="B"),
        "open": [10.0, 10.2, 10.1, 10.5, 10.3, 10.8, 10.6, 11.0, 10.9, 11.2],
        "close": [10.1, 10.0, 10.4, 10.2, 10.7, 10.5, 10.9, 10.8, 11.1, 11.0],
        "high": [10.3, 10.3, 10.5, 10.6, 10.8, 10.9, 11.0, 11.1, 11.2, 11.3],
        "low": [9.9, 9.9, 10.0, 10.1, 10.2, 10.4, 10.5, 10.7, 10.8, 10.9],
        "volume": [1e6, 1.2e6, 9e5, 1.5e6, 1.1e6, 1.3e6, 1e6, 1.4e6, 1.2e6, 1.6e6],
        "amount": [1e7, 1.2e7, 9e6, 1.5e7, 1.1e7, 1.3e7, 1e7, 1.4e7, 1.2e7, 1.6e7],
    }
)


def _make_quote_df(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        rows.append(
            {
                "symbol": sym,
                "name": f"Stock{sym}",
                "price": 10.50,
                "change": 0.30,
                "pct_change": 2.94,
                "open": 10.20,
                "high": 10.80,
                "low": 10.10,
                "prev_close": 10.20,
                "volume": 1500000,
                "amount": 1.5e7,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Mock factory functions
# ---------------------------------------------------------------------------


def _m_stock_service():
    svc = MagicMock()
    svc.get_watchlist.return_value = MOCK_WATCHLIST
    svc.get_latest_price_info.return_value = {
        "close": 10.50,
        "open": 10.20,
        "high": 10.80,
        "low": 10.10,
        "change": 0.30,
        "pct_change": 2.94,
        "volume": 1500000,
    }
    svc.get_stock_data_by_period.return_value = MOCK_OHLCV_DF.copy()
    svc.get_stock_detail.return_value = {
        "symbol": "000001",
        "name": "平安银行",
        "board": "main",
        "close": 10.50,
    }
    svc.get_indicators_summary.return_value = {"RSI_14": 55.0, "MACD": 0.05}
    svc.get_stock_with_indicators.return_value = MOCK_OHLCV_DF.copy()
    svc.get_stock_with_patterns.return_value = MOCK_OHLCV_DF.copy()
    svc.get_support_resistance.return_value = [
        {"level": 10.0, "type": "support", "strength": 3},
    ]
    svc.get_intraday_trades.return_value = {
        "buy_volume": 800000,
        "sell_volume": 600000,
        "neutral_volume": 100000,
        "total_volume": 1500000,
        "buy_ratio": 0.53,
        "sell_ratio": 0.40,
    }
    svc.get_intraday_trades_with_ticks.return_value = {
        "stats": {"buy_volume": 800000, "sell_volume": 600000},
        "ticks": [],
    }
    svc.fetcher = MagicMock()
    svc.fetcher.fetch_fund_flow.return_value = pd.DataFrame(
        [
            {
                "date": "2024-01-15",
                "main_net": 1000000,
                "retail_net": -1000000,
            }
        ]
    )
    svc.fetcher.fetch_intraday_fund_flow.return_value = pd.DataFrame(
        [
            {
                "date": "2024-01-15",
                "main_net": 500000,
                "super_large_net": 200000,
                "large_net": 300000,
                "medium_net": -100000,
                "small_net": -400000,
            }
        ]
    )
    svc.fetcher.fetch_fund_flow_detail.return_value = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "price": 10.50,
                "pct_change": 2.94,
                "inflow": 5e6,
                "outflow": 4e6,
                "net": 1e6,
                "amount": 1.5e7,
            }
        ]
    )
    svc.fetcher.fetch_dragon_tiger.return_value = pd.DataFrame()
    svc.fetcher.fetch_limit_up_pool.return_value = pd.DataFrame()
    svc.fetcher.fetch_stock_news.return_value = pd.DataFrame(
        [
            {
                "title": "平安银行发布年报",
                "time": "2024-01-15",
                "source": "东方财富",
                "url": "https://example.com/1",
            }
        ]
    )
    svc.fetcher.fetch_stock_anomalies.return_value = [
        {"type": "volume_spike", "description": "成交量异常放大", "severity": "high"},
    ]
    return svc


def _m_prediction_service():
    svc = MagicMock()
    svc.predict.return_value = {
        "status": "success",
        "symbol": "000001",
        "trend": "bullish",
        "signal": "buy",
        "confidence": 0.75,
        "risk_level": "medium",
        "reasoning": "趋势向好",
        "key_factors": ["均线金叉"],
    }
    svc.predict_enhanced.return_value = {
        "status": "success",
        "symbol": "000001",
        "trend": "bullish",
        "signal": "buy",
        "confidence": 0.75,
        "risk_level": "medium",
        "reasoning": "增强分析",
        "data_sources": ["indicators"],
    }
    svc.predict_comparison.return_value = {
        "status": "success",
        "analyses": [
            {
                "status": "success",
                "symbol": "000001",
                "trend": "bullish",
                "confidence": 0.75,
            },
            {
                "status": "success",
                "symbol": "600519",
                "trend": "neutral",
                "confidence": 0.60,
            },
        ],
        "comparison_summary": "整体看多",
        "recommendation_order": ["000001", "600519"],
    }
    return svc


def _m_backtest_service():
    svc = MagicMock()
    svc.get_available_strategies.return_value = [
        {"key": "ma_cross", "name": "均线交叉"},
        {"key": "momentum", "name": "动量策略"},
    ]
    svc.get_strategy_metadata.return_value = {
        "status": "success",
        "name": "均线交叉",
        "description": "短期均线上穿长期均线买入",
        "flow_steps": [],
        "flow_edges": [],
        "configurable_params": [],
    }
    svc.run_backtest.return_value = {
        "status": "success",
        "symbol": "000001",
        "strategy_key": "ma_cross",
        "strategy_name": "均线交叉",
        "board": "main",
        "metrics": {"annual_return": 0.15, "sharpe": 1.2, "max_drawdown": -0.08},
        "trades_count": 12,
        "equity_curve": [100000, 101000, 102500],
        "initial_capital": 100000,
        "final_capital": 115000,
    }
    return svc


def _m_portfolio_service():
    svc = MagicMock()
    svc.load_portfolio.return_value = {
        "positions": [
            {
                "symbol": "000001",
                "name": "平安银行",
                "shares": 1000,
                "cost": 10.0,
                "current_price": 10.50,
            }
        ],
        "summary": {"total_value": 10500, "total_cost": 10000, "pnl": 500},
    }
    svc.save_portfolio.return_value = {"success": True}
    svc.diagnose_portfolio.return_value = {
        "status": "success",
        "health_score": 72,
        "health_label": "良好",
        "summary": "持仓结构合理",
        "position_advice": [],
        "risk_warnings": [],
        "reasoning": ["分散度适中"],
    }
    return svc


def _m_llm_router():
    router = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        '{"summary":"回测表现良好","strategy_explain":"趋势跟踪",'
        '"strengths":["收益稳定"],"weaknesses":["回撤较大"],'
        '"improvement_suggestions":["优化止损"],"risk_analysis":"风险可控",'
        '"beginner_tips":"注意风险"}'
    )
    router.complete.return_value = mock_response
    try:
        from src.llm.base import LLMResponse, ProviderName

        router.generate.return_value = LLMResponse(
            text='{"trend": "bullish", "signal": "buy", "confidence": 0.75}',
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            latency_ms=500.0,
            cost_usd=0.003,
        )
    except ImportError:
        pass
    return router


def _m_quote_manager():
    mgr = MagicMock()
    mgr.get_quotes.side_effect = lambda symbols: _make_quote_df(symbols)
    mgr.get_single_quote.return_value = {
        "symbol": "000001",
        "price": 10.50,
        "change": 0.30,
    }
    mgr.clear_cache.return_value = None
    return mgr


def _m_news_fetcher():
    f = MagicMock()
    f.fetch_stock_news.return_value = pd.DataFrame(
        [
            {
                "title": "Test news",
                "time": "2024-01-15",
                "source": "东方财富",
                "datetime": "2024-01-15 10:00:00",
                "url": "https://example.com/1",
                "content": "Content",
            }
        ]
    )
    f.fetch_stock_anomalies.return_value = pd.DataFrame(
        [
            {
                "type": "volume_spike",
                "description": "成交量异常",
                "severity": "high",
                "datetime": "2024-01-15 09:37:09",
                "change_type": "大笔买入",
            }
        ]
    )
    f.fetch_hot_rank.return_value = pd.DataFrame(
        [{"rank": 1, "symbol": "000001", "name": "平安银行", "热度": 95}]
    )
    return f


def _m_realtime_analyzer():
    a = MagicMock()
    a.analyze_stock_realtime.return_value = {
        "status": "success",
        "symbol": "000001",
        "signal": "bullish",
        "summary": "短期看多",
        "points": ["资金流入"],
        "risks": ["大盘风险"],
    }
    a.get_quick_insight.return_value = {
        "symbol": "000001",
        "signal": "bullish",
        "confidence": 0.7,
        "summary": "技术面偏强",
        "risk_badge": "medium",
        "generated_at": "2024-01-15T10:00:00",
    }
    a.analyze_support_resistance.return_value = {
        "symbol": "000001",
        "levels": [],
        "analysis": "支撑位有效",
    }
    a.analyze_stock_move.return_value = {"symbol": "000001", "analysis": "涨幅归因分析"}
    a.analyze_dragon_tiger.return_value = {"symbol": "000001", "analysis": "机构净买入"}
    a.get_market_overview.return_value = {
        "status": "success",
        "summary": "市场整体偏强",
    }
    a.get_chart_events.return_value = []
    a.analyze_stock_unified.return_value = {
        "status": "ok",
        "symbol": "000001",
        "action": "hold",
        "action_label": "建议观望",
        "confidence": {"value": 0.65, "label": "中等"},
        "risk_level": "medium",
        "summary": "综合分析结果",
        "dimensions": [],
        "risk_warnings": [],
        "contrarian_check": "",
        "data_references": [],
        "disclaimer": "AI 分析仅供参考",
        "model_used": "mock",
        "generated_at": "2024-01-15T10:00:00",
        "message": "",
        "trend": "neutral",
        "signal": "hold",
        "confidence_number": 0.65,
        "reasoning": [],
        "quant_signals": {},
        "ai_reasoning": [],
    }
    return a


def _m_market_service():
    svc = MagicMock()
    svc.get_indices.return_value = [
        {
            "code": "sh000001",
            "name": "上证指数",
            "price": 3100.0,
            "change": 15.0,
            "pct_change": 0.49,
        }
    ]
    svc.get_market_indices.return_value = svc.get_indices.return_value
    return svc


def _m_global_market_fetcher():
    f = MagicMock()
    f.fetch_global_snapshot.return_value = {
        "indices": [
            {
                "symbol": "^GSPC",
                "name": "S&P500",
                "region": "US",
                "price": 4500.0,
                "change": 20.0,
                "pct_change": 0.45,
                "prev_close": 4480.0,
            }
        ],
        "commodities": [
            {
                "symbol": "GC=F",
                "name": "Gold",
                "unit": "USD/oz",
                "price": 2050.0,
                "change": 10.0,
                "pct_change": 0.49,
            }
        ],
        "currencies": [
            {
                "symbol": "CNY=X",
                "name": "USD/CNY",
                "price": 7.25,
                "change": 0.01,
                "pct_change": 0.14,
            }
        ],
    }
    f.fetch_global_indices.return_value = f.fetch_global_snapshot.return_value[
        "indices"
    ]
    f.fetch_commodities.return_value = f.fetch_global_snapshot.return_value[
        "commodities"
    ]
    f.fetch_currencies.return_value = f.fetch_global_snapshot.return_value["currencies"]
    return f


def _m_trading_calendar():
    cal = MagicMock()
    cal.is_trading_day.return_value = True
    cal.current_session.return_value = "afternoon"
    cal.next_trading_day.return_value = date(2026, 2, 16)
    cal.is_holiday_period.return_value = False
    cal.get_calendar_info.return_value = {
        "date": "2026-02-13",
        "is_trading_day": True,
        "current_session": "afternoon",
        "next_trading_day": "2026-02-16",
        "is_holiday_period": False,
    }
    return cal


def _m_admin_service():
    svc = MagicMock()
    svc.list_keys.return_value = [
        {"provider": "anthropic", "label": "default", "masked": "sk-...abc"}
    ]
    svc.add_key.return_value = {"status": "success"}
    svc.remove_key.return_value = {"status": "success"}
    svc.get_usage_dashboard.return_value = {
        "today": {"requests": 10, "cost": 0.15},
        "total_cost_usd": 1.50,
        "period_days": 7,
        "providers": {"anthropic": {"requests": 100, "cost": 1.50}},
    }
    svc.check_balances.return_value = [{"provider": "anthropic", "available": True}]
    svc.get_routing_config.return_value = {"strategy": "hybrid"}
    svc.update_routing_strategy.return_value = {"status": "success"}
    svc.update_analysis_params.return_value = {"status": "success"}
    return svc


def _m_advisor_service():
    svc = MagicMock()
    svc.get_stock_advice.return_value = {
        "status": "success",
        "symbol": "000001",
        "name": "平安银行",
        "action": "hold",
        "action_label": "观望",
        "confidence": 0.65,
        "risk_level": "medium",
        "quant_signals": {"technical_score": 0.5},
        "ai_reasoning": ["建议持有观望"],
        "risk_warnings": ["短期波动"],
        "disclaimer": "AI 分析仅供参考",
    }
    svc.get_watchlist_strategy.return_value = {
        "status": "success",
        "items": [
            {
                "symbol": "000001",
                "name": "平安银行",
                "action": "hold",
                "action_label": "观望",
                "confidence": 0.65,
                "risk_level": "medium",
            }
        ],
        "total": 1,
        "disclaimer": "AI 分析仅供参考",
    }
    svc.get_portfolio_advice.return_value = {
        "status": "success",
        "positions": [],
        "total": 0,
        "disclaimer": "AI 分析仅供参考",
    }
    svc.get_holiday_impact.return_value = {
        "status": "success",
        "symbol": "000001",
        "impact_score": 0.6,
        "impact_direction": "neutral",
        "factors": [],
        "ai_assessment": "假期影响有限",
        "suggested_action": "hold",
        "confidence": 0.5,
        "disclaimer": "AI 分析仅供参考",
    }
    svc.get_reopen_briefing.return_value = {
        "status": "success",
        "market_outlook": "neutral",
        "confidence": 0.5,
        "summary": "节后市场展望",
        "key_events": [],
        "position_impacts": [],
        "recommendations": [],
        "risk_warnings": [],
        "disclaimer": "AI 分析仅供参考",
    }
    return svc


def _m_sentiment_service():
    svc = MagicMock()
    svc.get_resonance_events.return_value = {
        "status": "success",
        "events": [
            {
                "event_id": "e1",
                "title": "热点",
                "resonance_level": "L2",
                "platforms": ["东财", "新浪"],
                "related_stocks": ["000001"],
                "sentiment": "positive",
                "heat_score": 85.0,
                "first_appeared": "",
                "last_updated": "",
            }
        ],
        "total": 1,
        "generated_at": "2024-01-15T10:00:00",
    }
    svc.get_sentiment_report.return_value = {
        "status": "success",
        "core_trends": [],
        "policy_signals": [],
        "global_linkage": {
            "us_market_summary": "",
            "commodity_impact": "",
            "forex_impact": "",
        },
        "risk_alerts": [],
        "sector_outlook": {"bullish": [], "bearish": [], "neutral": []},
        "overall_outlook": "偏多",
        "generated_at": "2024-01-15T10:00:00",
        "disclaimer": "AI 分析仅供参考",
    }
    svc.get_market_pulse.return_value = {
        "status": "success",
        "hot_events": [],
        "holdings_news": {},
    }
    svc.get_cross_market_analysis.return_value = {"symbol": "000001", "impact": 0.3}
    return svc


def _m_concept_analyzer():
    """Mock ConceptAnalyzer for /concept/hot."""
    from src.analysis.concept_analyzer import ConceptHeatItem

    a = MagicMock()
    a.rank_concepts.return_value = [
        ConceptHeatItem(
            code="BK0001",
            name="人工智能",
            pct_change=2.5,
            amount=1e9,
            up_count=30,
            down_count=5,
            heat_score=95.0,
            leader_symbol="000001",
            leader_name="平安银行",
            leader_pct=3.0,
        )
    ]
    return a


def _m_concept_board_service():
    svc = MagicMock()
    svc.get_hot_concepts.return_value = [
        {"board_code": "BK0001", "name": "人工智能", "heat": 95, "pct_change": 2.5}
    ]
    svc.get_constituents.return_value = [
        {"symbol": "000001", "name": "平安银行", "pct_change": 2.0}
    ]
    svc.get_concept_history.return_value = MOCK_OHLCV_DF.copy()
    svc.get_stock_concepts.return_value = {
        "concepts": [{"board_code": "BK0001", "name": "AI"}],
        "resonance_score": 0.8,
    }
    return svc


def _m_capital_flow_service():
    svc = MagicMock()
    svc.get_macro_overview.return_value = {
        "date": "2024-01-15",
        "environment_score": 35.0,
        "signal": "bullish",
        "northbound_net": 10.5,
        "southbound_net": -5.2,
        "margin_balance": 1500.0,
        "margin_balance_change": 2.3,
        "etf_net_flow": 8.0,
        "channels": [{"channel": "northbound", "value": 10.5, "direction": "up"}],
        "interpretation": "北向资金净流入",
        "updated_at": "2024-01-15T15:00:00",
    }
    svc.get_sector_ranking.return_value = {
        "type": "industry",
        "period": "today",
        "items": [
            {
                "sector_name": "银行",
                "sector_type": "industry",
                "change_pct": 1.5,
                "net_inflow": 5.0,
                "main_net_inflow": 3.0,
                "turnover": 2.5,
            }
        ],
        "interpretation": "银行板块资金流入居前",
    }
    return svc


def _m_redis():
    r = MagicMock()
    r.lrange.return_value = [
        '{"id": "n1", "type": "alert", "title": "Test", "summary": "", "timestamp": "2024-01-15", "action": "", "read": false}'
    ]
    r.llen.return_value = 1
    r.lpush.return_value = 1
    r.smembers.return_value = set()  # No read notifications
    return r


def _m_agent_service():
    """Mock AgentService for /chat/threads."""
    svc = MagicMock()
    svc.list_threads.return_value = ([], 0)
    return svc


def _m_simple_mock():
    return MagicMock()


def _m_suggestion_service():
    svc = MagicMock()
    svc.get_suggestions.return_value = [{"text": "分析平安银行", "type": "analysis"}]
    return svc


def _m_intelligence_hub_service():
    svc = MagicMock()
    svc.get_feed.return_value = {"items": [], "total": 0, "page": 1}
    svc.get_overview.return_value = {"categories": {}}
    svc.get_categories.return_value = []
    svc.get_item.return_value = None
    return svc


def _m_policy_news_fetcher():
    f = MagicMock()
    f.format_for_prompt.return_value = ""
    f.fetch_latest.return_value = []
    return f


def _m_analysis_data_validator():
    v = MagicMock()
    v._detect_board.return_value = ("main", 10.0)
    v.validate_and_enrich.return_value = MagicMock(
        quote={"symbol": "000001", "price": 10.5},
        indicators={"RSI_14": 55.0},
        news_items=[],
        anomalies=[],
        fund_flow=None,
        strategy_signals={},
        bayesian_analysis={},
        board_type="main",
        price_limit=10.0,
        data_quality_score=0.8,
        data_warnings=[],
        sector_info=None,
        intraday_trades=None,
        capital_flow_context={},
        policy_context="",
        support_resistance=[],
        dragon_tiger=None,
        fund_flow_detail=None,
        divergence_signals=[],
    )
    return v


def _m_data_health_tracker():
    t = MagicMock()
    t.get_status.return_value = {"sources": {}, "overall": "healthy"}
    return t


def _m_system_alert_engine():
    e = MagicMock()
    e.get_active_alerts.return_value = []
    e.list_rules.return_value = []
    return e


# ---------------------------------------------------------------------------
# Fixture: Full app with ALL dependency overrides
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def perf_app():
    """Create FastAPI app with all routers and dependency overrides."""
    from src.web.dependencies import (
        get_admin_service,
        get_advisor_service,
        get_agent_service,
        get_alert_engine,
        get_analysis_data_validator,
        get_backtest_service,
        get_capital_flow_service,
        get_concept_analyzer,
        get_concept_board_service,
        get_cross_market_analyzer,
        get_data_health_tracker,
        get_global_market_fetcher,
        get_keyword_matcher,
        get_llm_router,
        get_market_service,
        get_move_analyzer,
        get_news_fetcher,
        get_notification_dispatcher,
        get_paper_trade_signal_service,
        get_portfolio_service,
        get_prediction_service,
        get_prompt_manager,
        get_prompt_tester,
        get_realtime_analyzer,
        get_realtime_quote_manager,
        get_redis,
        get_resonance_detector,
        get_sentinel_config_service,
        get_sentiment_analyzer,
        get_sentiment_report_generator,
        get_sentiment_service,
        get_stock_registry,
        get_stock_service,
        get_strategy_context_service,
        get_strategy_lab_service,
        get_suggestion_service,
        get_system_alert_engine,
        get_timeline_scheduler,
        get_trading_calendar,
        get_trend_news_aggregator,
    )

    app = FastAPI()
    app.include_router(api_v1_router)

    # Core data services
    app.dependency_overrides[get_stock_service] = _m_stock_service
    app.dependency_overrides[get_stock_registry] = lambda: _m_stock_registry_impl()
    app.dependency_overrides[get_realtime_quote_manager] = _m_quote_manager
    app.dependency_overrides[get_news_fetcher] = _m_news_fetcher
    app.dependency_overrides[get_trading_calendar] = _m_trading_calendar
    app.dependency_overrides[get_market_service] = _m_market_service
    app.dependency_overrides[get_global_market_fetcher] = _m_global_market_fetcher

    # AI services
    app.dependency_overrides[get_prediction_service] = _m_prediction_service
    app.dependency_overrides[get_llm_router] = _m_llm_router
    app.dependency_overrides[get_realtime_analyzer] = _m_realtime_analyzer
    app.dependency_overrides[get_sentiment_analyzer] = _m_simple_mock
    app.dependency_overrides[get_move_analyzer] = _m_simple_mock
    app.dependency_overrides[get_advisor_service] = _m_advisor_service
    app.dependency_overrides[get_sentiment_service] = _m_sentiment_service
    app.dependency_overrides[get_sentiment_report_generator] = _m_simple_mock
    app.dependency_overrides[get_resonance_detector] = _m_simple_mock
    app.dependency_overrides[get_cross_market_analyzer] = _m_simple_mock

    # Portfolio / backtest / strategy
    app.dependency_overrides[get_backtest_service] = _m_backtest_service
    app.dependency_overrides[get_portfolio_service] = _m_portfolio_service
    app.dependency_overrides[get_strategy_lab_service] = _m_simple_mock
    app.dependency_overrides[get_paper_trade_signal_service] = _m_simple_mock
    app.dependency_overrides[get_strategy_context_service] = _m_simple_mock

    # Admin / settings / notifications
    app.dependency_overrides[get_admin_service] = _m_admin_service
    app.dependency_overrides[get_notification_dispatcher] = _m_simple_mock
    app.dependency_overrides[get_sentinel_config_service] = _m_simple_mock
    app.dependency_overrides[get_alert_engine] = _m_simple_mock
    app.dependency_overrides[get_system_alert_engine] = _m_system_alert_engine
    app.dependency_overrides[get_redis] = _m_redis

    # Scheduler / prompts / analysis
    app.dependency_overrides[get_timeline_scheduler] = lambda: (
        _m_timeline_scheduler_impl()
    )
    app.dependency_overrides[get_prompt_manager] = _m_simple_mock
    app.dependency_overrides[get_prompt_tester] = _m_simple_mock
    app.dependency_overrides[get_analysis_data_validator] = _m_simple_mock
    app.dependency_overrides[get_trend_news_aggregator] = _m_simple_mock
    app.dependency_overrides[get_keyword_matcher] = _m_simple_mock

    # Chat / agent
    app.dependency_overrides[get_agent_service] = _m_agent_service

    # Concept / capital flow / intelligence
    app.dependency_overrides[get_concept_board_service] = _m_concept_board_service
    app.dependency_overrides[get_concept_analyzer] = _m_concept_analyzer
    app.dependency_overrides[get_capital_flow_service] = _m_capital_flow_service
    app.dependency_overrides[get_suggestion_service] = _m_suggestion_service
    app.dependency_overrides[get_data_health_tracker] = _m_data_health_tracker

    # Patch direct instantiation / function calls that bypass DI overrides
    _quote_mgr_mock = _m_quote_manager()
    with (
        _patch(
            "src.web.routes.api_v1.stocks.RealtimeQuoteManager",
            return_value=_quote_mgr_mock,
        ),
        # agent.py calls get_* functions directly (bypassing DI) in _gather_analysis_data
        _patch("src.web.routes.api_v1.agent.get_stock_service", _m_stock_service),
        _patch(
            "src.web.routes.api_v1.agent.get_realtime_quote_manager", _m_quote_manager
        ),
        _patch("src.web.routes.api_v1.agent.get_news_fetcher", _m_news_fetcher),
        _patch(
            "src.web.routes.api_v1.agent.get_strategy_context_service", _m_simple_mock
        ),
        _patch(
            "src.web.routes.api_v1.agent.get_analysis_data_validator",
            _m_analysis_data_validator,
        ),
        _patch(
            "src.web.routes.api_v1.agent.get_capital_flow_service",
            _m_capital_flow_service,
        ),
        _patch(
            "src.web.routes.api_v1.agent.get_policy_news_fetcher",
            _m_policy_news_fetcher,
        ),
        _patch("src.web.routes.api_v1.agent.get_market_service", _m_market_service),
    ):
        yield app
    app.dependency_overrides.clear()


def _m_stock_registry_impl():
    r = MagicMock()
    r.search.return_value = [{"symbol": "000001", "name": "平安银行", "board": "main"}]
    r.get_stock_info.return_value = {
        "symbol": "000001",
        "name": "平安银行",
        "board": "main",
    }
    return r


def _m_timeline_scheduler_impl():
    s = MagicMock()
    s.get_status.return_value = {
        "mode": "normal",
        "active_profile": "trading_day",
        "next_execution": "2026-02-13T15:30:00",
    }
    s._config = {
        "profiles": {
            "trading_day": {"default": True, "tasks": {}},
            "holiday": {"default": False, "tasks": {}},
            "pre_market": {"default": True, "tasks": {}},
            "after_hours": {"default": True, "tasks": {}},
        }
    }
    s.update_plan.return_value = {"success": True}
    s.set_override.return_value = {"success": True}
    return s


@pytest.fixture(scope="module")
def perf_client(perf_app):
    """TestClient backed by the full mock app."""
    return TestClient(perf_app)


# ---------------------------------------------------------------------------
# Endpoint definitions by category: (method, url, body)
# ---------------------------------------------------------------------------

DATA_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/watchlist", None),
    ("GET", "/api/v1/stocks/search?q=平安", None),
    ("GET", "/api/v1/stock/000001", None),
    ("GET", "/api/v1/stock/000001/ohlcv?period=daily", None),
    ("GET", "/api/v1/stock/000001/indicators", None),
    ("GET", "/api/v1/stock/000001/indicators/full", None),
    ("GET", "/api/v1/stock/000001/patterns", None),
    ("GET", "/api/v1/stock/000001/support-resistance", None),
    ("GET", "/api/v1/stock/000001/fund-flow", None),
    ("GET", "/api/v1/stock/000001/fund-flow/intraday", None),
    ("GET", "/api/v1/stock/000001/fund-flow/detail", None),
]

MARKET_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/market/indices", None),
    ("GET", "/api/v1/market/realtime?symbols=000001", None),
    ("GET", "/api/v1/market/calendar", None),
    ("GET", "/api/v1/market/dragon-tiger", None),
    ("GET", "/api/v1/market/limit-up", None),
]

AI_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("POST", "/api/v1/predict/000001", None),
    ("POST", "/api/v1/predict/000001/enhanced", None),
    ("POST", "/api/v1/predict/compare", {"symbols": ["000001", "600519"]}),
    ("GET", "/api/v1/stock/000001/ai-analysis", None),
    ("GET", "/api/v1/stock/000001/unified-analysis", None),
    ("GET", "/api/v1/stock/000001/quick-insight", None),
    ("POST", "/api/v1/stock/000001/analyze", None),
    ("GET", "/api/v1/market/ai-overview", None),
]

PORTFOLIO_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/portfolio", None),
    (
        "POST",
        "/api/v1/portfolio/diagnose",
        {
            "positions": [
                {
                    "symbol": "000001",
                    "name": "平安银行",
                    "cost_price": 10.0,
                    "shares": 1000,
                }
            ],
        },
    ),
]

BACKTEST_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/strategies", None),
    ("POST", "/api/v1/backtest", {"symbol": "000001", "strategy": "ma_cross"}),
]

ADVISOR_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/advisor/stock/000001", None),
    ("GET", "/api/v1/advisor/watchlist", None),
    ("GET", "/api/v1/advisor/reopen-briefing", None),
]

GLOBAL_MARKET_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/global-market/snapshot", None),
    ("GET", "/api/v1/global-market/indices", None),
    ("GET", "/api/v1/global-market/commodities", None),
    ("GET", "/api/v1/global-market/currencies", None),
]

ADMIN_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/admin/keys", None),
    ("GET", "/api/v1/admin/usage", None),
]

SETTINGS_ENDPOINTS: list[tuple[str, str, dict | None]] = []

NOTIFICATION_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/notifications/recent", None),
    ("GET", "/api/v1/notifications/unread-count", None),
]

CHAT_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/chat/threads", None),
    ("GET", "/api/v1/chat/suggestions", None),
]

SENTIMENT_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/sentiment/resonance", None),
    ("GET", "/api/v1/sentiment/report", None),
    ("GET", "/api/v1/sentiment/market-pulse", None),
]

CONCEPT_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/concept/hot", None),
]

CAPITAL_FLOW_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/capital-flow/macro", None),
    ("GET", "/api/v1/capital-flow/sectors", None),
]

ALL_ENDPOINT_GROUPS: dict[str, list[tuple[str, str, dict | None]]] = {
    "data": DATA_ENDPOINTS,
    "market": MARKET_ENDPOINTS,
    "ai": AI_ENDPOINTS,
    "portfolio": PORTFOLIO_ENDPOINTS,
    "backtest": BACKTEST_ENDPOINTS,
    "advisor": ADVISOR_ENDPOINTS,
    "global_market": GLOBAL_MARKET_ENDPOINTS,
    "admin": ADMIN_ENDPOINTS,
    "settings": SETTINGS_ENDPOINTS,
    "notifications": NOTIFICATION_ENDPOINTS,
    "chat": CHAT_ENDPOINTS,
    "sentiment": SENTIMENT_ENDPOINTS,
    "concept": CONCEPT_ENDPOINTS,
    "capital_flow": CAPITAL_FLOW_ENDPOINTS,
}

ALL_ENDPOINTS: list[tuple[str, str, dict | None, str]] = []
for _cat, _eps in ALL_ENDPOINT_GROUPS.items():
    for _m, _u, _b in _eps:
        ALL_ENDPOINTS.append((_m, _u, _b, _cat))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAST_THRESHOLD_S = 0.100  # 100ms for data/market endpoints
AI_THRESHOLD_S = 2.0  # 2s for AI/LLM endpoints (mocked)

CATEGORY_THRESHOLDS: dict[str, float] = {
    "data": FAST_THRESHOLD_S,
    "market": FAST_THRESHOLD_S,
    "ai": AI_THRESHOLD_S,
    "portfolio": FAST_THRESHOLD_S,
    "backtest": FAST_THRESHOLD_S,
    "advisor": AI_THRESHOLD_S,
    "global_market": FAST_THRESHOLD_S,
    "admin": FAST_THRESHOLD_S,
    "settings": FAST_THRESHOLD_S,
    "notifications": FAST_THRESHOLD_S,
    "chat": FAST_THRESHOLD_S,
    "sentiment": FAST_THRESHOLD_S,
    "concept": FAST_THRESHOLD_S,
    "capital_flow": FAST_THRESHOLD_S,
}


# TestClient is NOT thread-safe; serialize concurrent access
_CLIENT_LOCK = threading.Lock()


def _hit(
    client: TestClient, method: str, url: str, body: dict | None = None
) -> tuple[float, int]:
    """Hit endpoint, return (latency_sec, status_code)."""
    start = time.perf_counter()
    if method == "POST":
        resp = client.post(url, json=body or {})
    elif method == "PUT":
        resp = client.put(url, json=body or {})
    else:
        resp = client.get(url)
    return time.perf_counter() - start, resp.status_code


def _hit_locked(
    client: TestClient, method: str, url: str, body: dict | None = None
) -> tuple[float, int]:
    """Thread-safe hit using lock. Measures wall time including lock wait."""
    with _CLIENT_LOCK:
        return _hit(client, method, url, body)


def _pcts(latencies: list[float]) -> dict[str, float]:
    """Compute percentiles in ms."""
    arr = np.array(latencies) * 1000
    return {
        "p50_ms": float(np.percentile(arr, 50)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "mean_ms": float(np.mean(arr)),
        "min_ms": float(np.min(arr)),
        "max_ms": float(np.max(arr)),
    }


def _err_rate(codes: list[int]) -> float:
    if not codes:
        return 0.0
    return sum(1 for c in codes if c >= 400) / len(codes)


# ===================================================================
# Test Class 1: Endpoint Latency Profile
# ===================================================================


class TestEndpointLatencyProfile:
    """Measure p50/p95/p99 latency for every endpoint category."""

    ITERATIONS = 50

    def _profile_group(
        self,
        client: TestClient,
        endpoints: list[tuple[str, str, dict | None]],
        category: str,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for method, url, body in endpoints:
            lats: list[float] = []
            codes: list[int] = []
            for _ in range(self.ITERATIONS):
                elapsed, sc = _hit(client, method, url, body)
                lats.append(elapsed)
                codes.append(sc)

            entry = {
                "method": method,
                "category": category,
                "samples": self.ITERATIONS,
                **_pcts(lats),
                "error_rate": _err_rate(codes),
                "errors": {str(c): codes.count(c) for c in set(codes) if c >= 400},
            }
            results[url] = entry
            PERF_RESULTS["endpoints"][url] = entry
        return results

    @pytest.mark.performance
    def test_data_endpoints(self, perf_client):
        results = self._profile_group(perf_client, DATA_ENDPOINTS, "data")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_market_endpoints(self, perf_client):
        results = self._profile_group(perf_client, MARKET_ENDPOINTS, "market")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_ai_endpoints(self, perf_client):
        results = self._profile_group(perf_client, AI_ENDPOINTS, "ai")
        for url, info in results.items():
            assert info["p95_ms"] < AI_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_portfolio_endpoints(self, perf_client):
        results = self._profile_group(perf_client, PORTFOLIO_ENDPOINTS, "portfolio")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_backtest_endpoints(self, perf_client):
        results = self._profile_group(perf_client, BACKTEST_ENDPOINTS, "backtest")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_advisor_endpoints(self, perf_client):
        results = self._profile_group(perf_client, ADVISOR_ENDPOINTS, "advisor")
        for url, info in results.items():
            assert info["p95_ms"] < AI_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_global_market_endpoints(self, perf_client):
        results = self._profile_group(
            perf_client, GLOBAL_MARKET_ENDPOINTS, "global_market"
        )
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_admin_endpoints(self, perf_client):
        combined = ADMIN_ENDPOINTS + SETTINGS_ENDPOINTS
        results = self._profile_group(perf_client, combined, "admin")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_notification_endpoints(self, perf_client):
        results = self._profile_group(
            perf_client, NOTIFICATION_ENDPOINTS, "notifications"
        )
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_chat_endpoints(self, perf_client):
        results = self._profile_group(perf_client, CHAT_ENDPOINTS, "chat")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_sentiment_endpoints(self, perf_client):
        results = self._profile_group(perf_client, SENTIMENT_ENDPOINTS, "sentiment")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_concept_endpoints(self, perf_client):
        results = self._profile_group(perf_client, CONCEPT_ENDPOINTS, "concept")
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )

    @pytest.mark.performance
    def test_capital_flow_endpoints(self, perf_client):
        results = self._profile_group(
            perf_client, CAPITAL_FLOW_ENDPOINTS, "capital_flow"
        )
        for url, info in results.items():
            assert info["p95_ms"] < FAST_THRESHOLD_S * 1000, (
                f"{url} p95={info['p95_ms']:.1f}ms"
            )


# ===================================================================
# Test Class 2: Concurrent Load
# ===================================================================


class TestConcurrentLoad:
    """Simulate concurrent users hitting different endpoints."""

    def _run_concurrent(
        self,
        client: TestClient,
        workers: int,
        requests_per_worker: int,
    ) -> dict[str, Any]:
        read_eps = (
            DATA_ENDPOINTS
            + MARKET_ENDPOINTS
            + GLOBAL_MARKET_ENDPOINTS
            + NOTIFICATION_ENDPOINTS
        )
        write_eps = [
            ("POST", "/api/v1/predict/000001", None),
            ("POST", "/api/v1/backtest", {"symbol": "000001", "strategy": "ma_cross"}),
        ]
        pool = read_eps * 4 + write_eps  # 80/20 mix

        all_lats: list[float] = []
        all_codes: list[int] = []
        errors_by_url: dict[str, int] = {}

        total_start = time.perf_counter()

        def _worker(wid: int) -> list[tuple[float, int, str]]:
            out: list[tuple[float, int, str]] = []
            for i in range(requests_per_worker):
                idx = (wid * requests_per_worker + i) % len(pool)
                m, u, b = pool[idx]
                e, s = _hit_locked(client, m, u, b)
                out.append((e, s, u))
            return out

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, w) for w in range(workers)]
            for f in as_completed(futures):
                for elapsed, sc, url in f.result():
                    all_lats.append(elapsed)
                    all_codes.append(sc)
                    if sc >= 400:
                        errors_by_url[url] = errors_by_url.get(url, 0) + 1

        total_time = time.perf_counter() - total_start
        total_reqs = len(all_lats)

        return {
            "workers": workers,
            "requests_per_worker": requests_per_worker,
            "total_requests": total_reqs,
            "total_time_s": round(total_time, 3),
            "requests_per_sec": round(total_reqs / total_time, 1),
            "error_rate": _err_rate(all_codes),
            **_pcts(all_lats),
            "errors_by_url": errors_by_url,
        }

    @pytest.mark.performance
    def test_concurrent_10_workers(self, perf_client):
        results = self._run_concurrent(perf_client, workers=10, requests_per_worker=20)
        PERF_RESULTS["load_tests"]["concurrent_10"] = results
        assert results["error_rate"] < 0.05, (
            f"Error rate {results['error_rate']:.2%} at 10 workers"
        )

    @pytest.mark.performance
    def test_concurrent_25_workers(self, perf_client):
        results = self._run_concurrent(perf_client, workers=25, requests_per_worker=10)
        PERF_RESULTS["load_tests"]["concurrent_25"] = results
        assert results["error_rate"] < 0.05, (
            f"Error rate {results['error_rate']:.2%} at 25 workers"
        )

    @pytest.mark.performance
    def test_concurrent_50_workers(self, perf_client):
        results = self._run_concurrent(perf_client, workers=50, requests_per_worker=5)
        PERF_RESULTS["load_tests"]["concurrent_50"] = results
        assert results["error_rate"] < 0.10, (
            f"Error rate {results['error_rate']:.2%} at 50 workers"
        )


# ===================================================================
# Test Class 3: Stress Escalation
# ===================================================================


class TestStressEscalation:
    """Gradually increase load until error rate exceeds 5%."""

    ERROR_THRESHOLD = 0.05
    MAX_CONCURRENCY = 100
    STEP = 10
    REQUESTS_PER_WORKER = 5

    @pytest.mark.performance
    def test_stress_escalation(self, perf_client):
        read_eps = DATA_ENDPOINTS + MARKET_ENDPOINTS
        levels: list[dict[str, Any]] = []
        breaking_point: int | None = None

        for concurrency in range(self.STEP, self.MAX_CONCURRENCY + 1, self.STEP):
            all_lats: list[float] = []
            all_codes: list[int] = []

            def _worker(wid: int) -> list[tuple[float, int]]:
                out: list[tuple[float, int]] = []
                for i in range(self.REQUESTS_PER_WORKER):
                    idx = (wid * self.REQUESTS_PER_WORKER + i) % len(read_eps)
                    m, u, b = read_eps[idx]
                    e, s = _hit_locked(perf_client, m, u, b)
                    out.append((e, s))
                return out

            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(_worker, w) for w in range(concurrency)]
                for f in as_completed(futures):
                    for elapsed, sc in f.result():
                        all_lats.append(elapsed)
                        all_codes.append(sc)

            total_time = time.perf_counter() - t0
            err_rate = _err_rate(all_codes)
            total_reqs = len(all_lats)

            level = {
                "concurrency": concurrency,
                "total_requests": total_reqs,
                "total_time_s": round(total_time, 3),
                "rps": round(total_reqs / total_time, 1),
                "error_rate": err_rate,
                **_pcts(all_lats),
            }
            levels.append(level)

            if err_rate > self.ERROR_THRESHOLD:
                breaking_point = concurrency
                break

        PERF_RESULTS["load_tests"]["stress_test"] = {
            "error_threshold": self.ERROR_THRESHOLD,
            "breaking_concurrency": breaking_point,
            "max_sustainable": (breaking_point - self.STEP)
            if breaking_point
            else self.MAX_CONCURRENCY,
            "break_error_rate": levels[-1]["error_rate"] if levels else 0,
        }
        PERF_RESULTS["load_tests"]["concurrency_levels"] = levels

        max_sustained = (
            (breaking_point - self.STEP) if breaking_point else self.MAX_CONCURRENCY
        )
        assert max_sustained >= 20, f"Broke at {breaking_point}, expected at least 20"


# ===================================================================
# Test Class 4: Error Rate
# ===================================================================


class TestEndpointErrorRate:
    """Track error rates across all endpoints."""

    ITERATIONS = 30

    def _check_group(
        self,
        client: TestClient,
        endpoints: list[tuple[str, str, dict | None]],
        threshold: float,
    ):
        for method, url, body in endpoints:
            codes: list[int] = []
            for _ in range(self.ITERATIONS):
                _, sc = _hit(client, method, url, body)
                codes.append(sc)
            er = _err_rate(codes)
            assert er < threshold, f"{url} error rate {er:.2%} exceeds {threshold:.0%}"

    @pytest.mark.performance
    def test_data_error_rate(self, perf_client):
        self._check_group(perf_client, DATA_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_market_error_rate(self, perf_client):
        self._check_group(perf_client, MARKET_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_ai_error_rate(self, perf_client):
        self._check_group(perf_client, AI_ENDPOINTS, 0.05)

    @pytest.mark.performance
    def test_portfolio_error_rate(self, perf_client):
        self._check_group(perf_client, PORTFOLIO_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_backtest_error_rate(self, perf_client):
        self._check_group(perf_client, BACKTEST_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_advisor_error_rate(self, perf_client):
        self._check_group(perf_client, ADVISOR_ENDPOINTS, 0.05)

    @pytest.mark.performance
    def test_global_market_error_rate(self, perf_client):
        self._check_group(perf_client, GLOBAL_MARKET_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_notification_error_rate(self, perf_client):
        self._check_group(perf_client, NOTIFICATION_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_sentiment_error_rate(self, perf_client):
        self._check_group(perf_client, SENTIMENT_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_concept_error_rate(self, perf_client):
        self._check_group(perf_client, CONCEPT_ENDPOINTS, 0.01)

    @pytest.mark.performance
    def test_capital_flow_error_rate(self, perf_client):
        self._check_group(perf_client, CAPITAL_FLOW_ENDPOINTS, 0.01)


# ===================================================================
# Session-scoped result writing
# ===================================================================


@pytest.fixture(scope="module", autouse=True)
def _write_results_on_teardown():
    """Write PERF_RESULTS to reports/perf-results.json after all tests."""
    yield

    from datetime import datetime, timezone

    PERF_RESULTS["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Build load test summary
    if PERF_RESULTS.get("load_tests"):
        lt = PERF_RESULTS["load_tests"]
        levels = lt.get("concurrency_levels", [])
        if levels:
            peak = max(levels, key=lambda x: x.get("rps", 0))
            lt["peak_rps"] = peak.get("rps", 0)
        stress = lt.get("stress_test", {})
        lt["max_concurrency"] = stress.get("max_sustainable", "N/A")

    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "perf-results.json"

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(PERF_RESULTS, f, indent=2, ensure_ascii=False, default=str)
    except Exception:
        pass
