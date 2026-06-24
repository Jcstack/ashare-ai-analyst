"""Shared E2E test fixtures.

Provides a full FastAPI app with ALL 18 routers mounted and ALL 33+
dependencies overridden with mocks.  Only external boundaries are mocked
(AKShare, LLM APIs, Redis, yfinance) — real service logic executes
end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web.routes.api_v1 import router as api_v1_router

# ---------------------------------------------------------------------------
# Mock data constants
# ---------------------------------------------------------------------------

MOCK_WATCHLIST = [
    {"symbol": "000001", "name": "平安银行", "board": "main"},
    {"symbol": "600519", "name": "贵州茅台", "board": "main"},
]

MOCK_STOCKS_CONFIG = {
    "watchlist": MOCK_WATCHLIST,
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
    "cache": {"enabled": True, "directory": "data/raw", "ttl_hours": 12},
    "request": {
        "interval_seconds": 0,
        "max_retries": 3,
        "retry_delay_seconds": 0,
        "timeout_seconds": 10,
    },
}

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

MOCK_QUOTE_DF = pd.DataFrame(
    [
        {
            "symbol": "000001",
            "name": "平安银行",
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
    ]
)


def _make_quote_df(symbols: list[str]) -> pd.DataFrame:
    """Build a mock realtime quote DataFrame for given symbols."""
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
# Mock service factories
# ---------------------------------------------------------------------------


def _mock_stock_service():
    """Create a mock StockService with common return values."""
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
    svc.get_indicators_summary.return_value = {
        "RSI_14": 55.0,
        "MACD": 0.05,
        "MACD_signal": 0.03,
    }
    svc.get_stock_with_indicators.return_value = MOCK_OHLCV_DF.copy()
    svc.get_stock_with_patterns.return_value = MOCK_OHLCV_DF.copy()
    svc.get_support_resistance.return_value = [
        {"level": 10.0, "type": "support", "strength": 3},
        {"level": 11.0, "type": "resistance", "strength": 2},
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
                "inflow": 5000000.0,
                "outflow": 4000000.0,
                "net": 1000000.0,
                "amount": 1.5e7,
            }
        ]
    )
    svc.fetcher.fetch_dragon_tiger.return_value = pd.DataFrame()
    svc.fetcher.fetch_stock_news.return_value = pd.DataFrame(
        [
            {
                "title": "平安银行发布年报",
                "time": "2024-01-15",
                "source": "东方财富",
                "url": "https://example.com/news/1",
            }
        ]
    )
    svc.fetcher.fetch_stock_anomalies.return_value = [
        {"type": "volume_spike", "description": "成交量异常放大", "severity": "high"},
    ]
    return svc


def _mock_prediction_service():
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
        "data_sources": ["indicators", "fund_flow"],
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


def _mock_backtest_service():
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


def _mock_portfolio_service():
    svc = MagicMock()
    svc.load_portfolio.return_value = {
        "positions": [
            {
                "symbol": "000001",
                "name": "平安银行",
                "shares": 1000,
                "cost": 10.0,
                "current_price": 10.50,
            },
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


def _mock_llm_router():
    router = MagicMock()
    mock_response = MagicMock()
    mock_response.content = (
        '{"summary":"回测表现良好","strategy_explain":"趋势跟踪",'
        '"strengths":["收益稳定"],"weaknesses":["回撤较大"],'
        '"improvement_suggestions":["优化止损"],"risk_analysis":"风险可控",'
        '"beginner_tips":"注意风险"}'
    )
    router.complete.return_value = mock_response
    # Also set generate for other tests
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


def _mock_realtime_quote_manager():
    mgr = MagicMock()
    mgr.get_quotes.side_effect = lambda symbols: _make_quote_df(symbols)
    mgr.get_single_quote.return_value = {
        "symbol": "000001",
        "price": 10.50,
        "change": 0.30,
    }
    mgr.clear_cache.return_value = None
    return mgr


def _mock_news_fetcher():
    fetcher = MagicMock()
    fetcher.fetch_stock_news.return_value = pd.DataFrame(
        [
            {
                "title": "Test news",
                "time": "2024-01-15",
                "source": "东方财富",
                "datetime": "2024-01-15 10:00:00",
                "url": "https://example.com/1",
                "content": "News content",
            }
        ]
    )
    fetcher.fetch_stock_anomalies.return_value = pd.DataFrame(
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
    fetcher.fetch_hot_rank.return_value = pd.DataFrame(
        [
            {
                "rank": 1,
                "symbol": "000001",
                "name": "平安银行",
                "热度": 95,
            }
        ]
    )
    return fetcher


def _mock_realtime_analyzer():
    analyzer = MagicMock()
    analyzer.analyze_stock_realtime.return_value = {
        "status": "success",
        "symbol": "000001",
        "signal": "bullish",
        "summary": "短期看多",
        "points": ["资金流入"],
        "risks": ["大盘风险"],
    }
    analyzer.get_quick_insight.return_value = {
        "symbol": "000001",
        "signal": "bullish",
        "confidence": 0.7,
        "summary": "技术面偏强",
        "risk_badge": "medium",
        "generated_at": "2024-01-15T10:00:00",
    }
    analyzer.analyze_support_resistance.return_value = {
        "symbol": "000001",
        "levels": [],
        "analysis": "支撑位有效",
    }
    analyzer.analyze_stock_move.return_value = {
        "symbol": "000001",
        "analysis": "涨幅归因分析",
    }
    analyzer.analyze_dragon_tiger.return_value = {
        "symbol": "000001",
        "analysis": "机构净买入",
    }
    analyzer.get_market_overview.return_value = {
        "status": "success",
        "summary": "市场整体偏强",
    }
    analyzer.get_chart_events.return_value = []
    return analyzer


def _mock_sentiment_analyzer():
    analyzer = MagicMock()
    analyzer.analyze.return_value = {
        "sentiment": "positive",
        "score": 0.7,
    }
    analyzer.analyze_batch.return_value = {
        "overall": "positive",
        "score": 0.7,
        "positive_count": 1,
        "negative_count": 0,
        "neutral_count": 0,
        "total_count": 1,
        "summary": "整体偏正面",
    }
    return analyzer


def _mock_alert_engine():
    engine = MagicMock()
    engine.get_alerts.return_value = []
    return engine


def _mock_admin_service():
    svc = MagicMock()
    svc.list_keys.return_value = [
        {"provider": "anthropic", "label": "default", "masked": "sk-...abc"},
    ]
    svc.add_key.return_value = {"status": "success", "message": "Key added"}
    svc.remove_key.return_value = {"status": "success", "message": "Key removed"}
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
    svc.update_watchlist.return_value = {
        "status": "success",
        "message": "Watchlist updated",
    }
    return svc


def _mock_strategy_lab_service():
    svc = MagicMock()
    svc.create_from_nl.return_value = {
        "status": "success",
        "strategy_key": "custom_1",
        "params": {"fast": 5, "slow": 20},
        "explanation": "基于均线交叉策略",
        "confidence": 0.8,
    }
    svc.optimize_params.return_value = {
        "status": "success",
        "suggested_params": {"fast": 3, "slow": 15},
        "reasoning": ["短周期更敏感"],
        "param_explanations": {"fast": "快线周期"},
    }
    svc.analyze_attribution.return_value = {
        "status": "success",
        "summary": "策略归因分析",
        "key_findings": [],
        "win_factors": [],
        "loss_factors": [],
        "improvement_suggestions": [],
    }
    return svc


def _mock_paper_trade_signal_service():
    svc = MagicMock()
    svc.get_latest_signals.return_value = []
    svc.check_signals.return_value = {"signals": []}
    return svc


def _mock_strategy_context_service():
    svc = MagicMock()
    return svc


def _mock_prompt_manager():
    mgr = MagicMock()
    mgr.list_prompts.return_value = [
        {"id": "p1", "name": "Default", "template": "Analyze {symbol}"},
    ]
    mgr.get_prompt.return_value = {
        "id": "p1",
        "name": "Default",
        "template": "Analyze {symbol}",
    }
    mgr.create_prompt.return_value = {"id": "p2", "name": "New"}
    mgr.update_prompt.return_value = {"success": True}
    mgr.delete_prompt.return_value = {"success": True}
    return mgr


def _mock_prompt_tester():
    tester = MagicMock()
    tester.test_prompt.return_value = {
        "result": "Analysis output",
        "tokens": 300,
    }
    tester.optimize_prompt.return_value = {
        "optimized": "Improved prompt template",
    }
    return tester


def _mock_move_analyzer():
    analyzer = MagicMock()
    analyzer.analyze.return_value = {
        "symbol": "000001",
        "analysis": "涨跌归因",
    }
    return analyzer


def _mock_market_service():
    svc = MagicMock()
    svc.get_indices.return_value = [
        {
            "symbol": "000001",
            "name": "上证指数",
            "price": 3100.0,
            "change": 15.0,
            "pct_change": 0.49,
        },
    ]
    return svc


def _mock_stock_registry():
    registry = MagicMock()
    registry.search.return_value = [
        {"symbol": "000001", "name": "平安银行", "board": "main"},
    ]
    registry.get_stock_info.return_value = {
        "symbol": "000001",
        "name": "平安银行",
        "board": "main",
    }
    return registry


def _mock_trading_calendar():
    from datetime import date

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


def _mock_global_market_fetcher():
    fetcher = MagicMock()
    fetcher.fetch_global_snapshot.return_value = {
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
    fetcher.fetch_global_indices.return_value = (
        fetcher.fetch_global_snapshot.return_value["indices"]
    )
    fetcher.fetch_commodities.return_value = fetcher.fetch_global_snapshot.return_value[
        "commodities"
    ]
    fetcher.fetch_currencies.return_value = fetcher.fetch_global_snapshot.return_value[
        "currencies"
    ]
    return fetcher


def _mock_timeline_scheduler():
    scheduler = MagicMock()
    scheduler.get_status.return_value = {
        "mode": "normal",
        "active_profile": "trading_day",
        "next_execution": "2026-02-13T15:30:00",
    }
    # _config must be a real dict so _build_plans() can call .get() on it
    scheduler._config = {
        "profiles": {
            "trading_day": {"default": True, "tasks": {}},
            "holiday": {"default": False, "tasks": {}},
            "pre_market": {"default": True, "tasks": {}},
            "after_hours": {"default": True, "tasks": {}},
        }
    }
    scheduler.update_plan.return_value = {"success": True}
    scheduler.set_override.return_value = {"success": True}
    scheduler.get_calendar.return_value = [
        {"date": "2026-02-13", "is_trading": True, "session": "afternoon"},
    ]
    return scheduler


def _mock_trend_news_aggregator():
    agg = MagicMock()
    agg.fetch_all.return_value = [
        {"title": "热点新闻", "source": "东方财富", "heat": 95, "time": "2024-01-15"},
    ]
    return agg


def _mock_keyword_matcher():
    matcher = MagicMock()
    matcher.match.return_value = [
        {"keyword": "银行", "relevance": 0.8, "category": "industry"},
    ]
    return matcher


def _mock_advisor_service():
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
            },
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


def _mock_resonance_detector():
    detector = MagicMock()
    detector.detect.return_value = [
        {
            "title": "热点事件",
            "level": "L2",
            "sources": ["东方财富", "新浪"],
            "related_stocks": ["000001"],
            "sentiment": "positive",
        },
    ]
    return detector


def _mock_cross_market_analyzer():
    analyzer = MagicMock()
    analyzer.analyze.return_value = {
        "symbol": "000001",
        "peers": [],
        "global_impact": {"score": 0.3, "factors": []},
    }
    return analyzer


def _mock_sentiment_report_generator():
    gen = MagicMock()
    gen.generate.return_value = {
        "core_trends": "市场情绪偏多",
        "policy_signals": "政策面利好",
        "global_linkage": "外盘走强",
        "risk_warnings": "注意调整",
        "sector_outlook": "科技板块领涨",
        "overall_assessment": "短期看多",
    }
    return gen


def _mock_sentiment_service():
    svc = MagicMock()
    svc.get_resonance_events.return_value = [
        {"title": "热点", "level": "L2", "sources": 2},
    ]
    svc.get_sentiment_report.return_value = {
        "summary": "市场情绪偏多",
    }
    svc.get_market_pulse.return_value = {
        "sentiment": "positive",
        "score": 0.7,
    }
    svc.get_cross_market_analysis.return_value = {
        "symbol": "000001",
        "impact": 0.3,
    }
    return svc


def _mock_notification_dispatcher():
    dispatcher = MagicMock()
    dispatcher.dispatch.return_value = {"sent": True}
    return dispatcher


def _mock_sentinel_config_service():
    svc = MagicMock()
    svc.get_config.return_value = {
        "data_sources": {"global_markets": True},
        "notification_channels": {"wecom": {"enabled": False}},
    }
    svc.update_config.return_value = {"success": True}
    return svc


def _mock_analysis_data_validator():
    validator = MagicMock()
    validator.validate.return_value = {"valid": True, "errors": []}
    return validator


def _mock_redis():
    """Mock Redis client for notification storage."""
    r = MagicMock()
    r.lrange.return_value = [
        '{"id": "n1", "type": "alert", "title": "Test", "read": false, "time": "2024-01-15"}',
    ]
    r.llen.return_value = 1
    r.lpush.return_value = 1
    return r


# ---------------------------------------------------------------------------
# DB-backed service mocks (prevent real data/agent.db writes — I-030 fix)
# ---------------------------------------------------------------------------


def _mock_portfolio_store():
    """Mock PortfolioStore to prevent writes to real data/agent.db."""
    store = MagicMock()
    store.get_portfolio_data.return_value = {
        "version": 1,
        "updatedAt": "",
        "positions": [],
    }
    store.list_positions.return_value = []
    store.get_position.return_value = None
    store.add_position.return_value = {
        "id": "test-pos-001",
        "symbol": "000001",
        "name": "平安银行",
        "board": "main",
        "cost_price": 10.0,
        "shares": 1000,
        "buy_date": "",
        "note": "",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    store.update_position.return_value = store.add_position.return_value
    store.remove_position.return_value = True
    store.save_portfolio_data.return_value = None
    store.liquidate_position.return_value = {
        "id": "tx-001",
        "type": "position_liquidation",
        "amount": 10000.0,
        "balance_after": 10000.0,
        "trade_id": None,
        "symbol": "000001",
        "description": "test liquidation",
        "created_at": "2024-01-01T00:00:00",
    }
    return store


def _mock_capital_service():
    """Mock CapitalService to prevent writes to real data/agent.db."""
    svc = MagicMock()
    svc.get_balance.return_value = 100000.0
    svc.get_balance_info.return_value = MagicMock(
        available_cash=100000.0,
        total_transactions=1,
        has_initial_deposit=True,
    )
    svc.get_breakdown.return_value = MagicMock(
        available_cash=100000.0,
        position_value=0.0,
        total_assets=100000.0,
        utilization_rate=0.0,
        positions=[],
        has_initial_deposit=True,
    )
    svc.get_history.return_value = []
    svc.get_transaction_count.return_value = 0
    svc.deposit.return_value = MagicMock(
        id="tx-test",
        type="deposit",
        amount=100000.0,
        balance_after=100000.0,
        trade_id=None,
        symbol=None,
        description="test",
        created_at="2024-01-01T00:00:00",
    )
    svc.record_position_liquidation.return_value = MagicMock(
        id="tx-liq",
        type="position_liquidation",
        amount=10000.0,
        balance_after=110000.0,
        trade_id=None,
        symbol="000001",
        description="test",
        created_at="2024-01-01T00:00:00",
    )
    return svc


def _mock_watchlist_service_db():
    """Mock WatchlistService to prevent writes to real data/agent.db."""
    svc = MagicMock()
    svc.list_all.return_value = MOCK_WATCHLIST
    svc.contains.return_value = True
    svc.add.return_value = MOCK_WATCHLIST[0]
    svc.remove.return_value = True
    svc.bulk_replace.return_value = MOCK_WATCHLIST
    return svc


def _mock_trade_service():
    """Mock TradeService to prevent writes to real data/agent.db."""
    svc = MagicMock()
    svc.list_trades.return_value = []
    svc.get_trade.return_value = None
    svc.get_trade_count.return_value = 0
    return svc


def _mock_user_config_service():
    """Mock UserConfigService to prevent writes to real data/agent.db."""
    svc = MagicMock()
    svc.get.return_value = None
    svc.get_all.return_value = {}
    svc.set.return_value = None
    svc.delete.return_value = True
    return svc


def _mock_agent_service():
    """Mock AgentService to prevent writes to real data/agent.db."""
    svc = MagicMock()
    svc.list_threads.return_value = []
    svc.create_thread.return_value = {"id": "test-thread", "title": "Test"}
    svc.get_messages.return_value = []
    return svc


def _mock_intelligence_hub_service():
    """Mock IntelligenceHubService to prevent writes to real data/info_items.db."""
    svc = MagicMock()
    svc.get_feed.return_value = []
    svc.get_overview.return_value = {
        "total_items": 0,
        "sources_count": 0,
        "categories": {},
    }
    svc.refresh.return_value = {"new_items": 0, "new_item_ids": [], "status": "ok"}
    svc.get_category_counts.return_value = {}
    svc.toggle_bookmark.return_value = True
    svc.mark_read.return_value = True
    return svc


# ---------------------------------------------------------------------------
# Full-app fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a FastAPI app with all routers and dependency overrides."""
    from src.web.dependencies import (
        get_admin_service,
        get_advisor_service,
        get_agent_service,
        get_alert_engine,
        get_analysis_data_validator,
        get_backtest_service,
        get_capital_service,
        get_cross_market_analyzer,
        get_global_market_fetcher,
        get_intelligence_hub_service,
        get_keyword_matcher,
        get_llm_router,
        get_market_service,
        get_move_analyzer,
        get_news_fetcher,
        get_notification_dispatcher,
        get_portfolio_service,
        get_portfolio_store,
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
        get_timeline_scheduler,
        get_trade_service,
        get_trading_calendar,
        get_trend_news_aggregator,
        get_user_config_service,
        get_watchlist_service,
        get_paper_trade_signal_service,
    )

    test_app = FastAPI()
    test_app.include_router(api_v1_router)

    # Override all 33+ dependencies
    test_app.dependency_overrides[get_stock_service] = _mock_stock_service
    test_app.dependency_overrides[get_prediction_service] = _mock_prediction_service
    test_app.dependency_overrides[get_backtest_service] = _mock_backtest_service
    test_app.dependency_overrides[get_portfolio_service] = _mock_portfolio_service
    test_app.dependency_overrides[get_admin_service] = _mock_admin_service
    test_app.dependency_overrides[get_llm_router] = _mock_llm_router
    test_app.dependency_overrides[get_stock_registry] = _mock_stock_registry
    test_app.dependency_overrides[get_realtime_quote_manager] = (
        _mock_realtime_quote_manager
    )
    test_app.dependency_overrides[get_news_fetcher] = _mock_news_fetcher
    test_app.dependency_overrides[get_alert_engine] = _mock_alert_engine
    test_app.dependency_overrides[get_realtime_analyzer] = _mock_realtime_analyzer
    test_app.dependency_overrides[get_sentiment_analyzer] = _mock_sentiment_analyzer
    test_app.dependency_overrides[get_move_analyzer] = _mock_move_analyzer
    test_app.dependency_overrides[get_strategy_lab_service] = _mock_strategy_lab_service
    test_app.dependency_overrides[get_paper_trade_signal_service] = (
        _mock_paper_trade_signal_service
    )
    test_app.dependency_overrides[get_strategy_context_service] = (
        _mock_strategy_context_service
    )
    test_app.dependency_overrides[get_portfolio_service] = _mock_portfolio_service
    test_app.dependency_overrides[get_prompt_manager] = _mock_prompt_manager
    test_app.dependency_overrides[get_prompt_tester] = _mock_prompt_tester
    test_app.dependency_overrides[get_market_service] = _mock_market_service
    test_app.dependency_overrides[get_analysis_data_validator] = (
        _mock_analysis_data_validator
    )
    test_app.dependency_overrides[get_trading_calendar] = _mock_trading_calendar
    test_app.dependency_overrides[get_global_market_fetcher] = (
        _mock_global_market_fetcher
    )
    test_app.dependency_overrides[get_timeline_scheduler] = _mock_timeline_scheduler
    test_app.dependency_overrides[get_trend_news_aggregator] = (
        _mock_trend_news_aggregator
    )
    test_app.dependency_overrides[get_keyword_matcher] = _mock_keyword_matcher
    test_app.dependency_overrides[get_advisor_service] = _mock_advisor_service
    test_app.dependency_overrides[get_resonance_detector] = _mock_resonance_detector
    test_app.dependency_overrides[get_cross_market_analyzer] = (
        _mock_cross_market_analyzer
    )
    test_app.dependency_overrides[get_sentiment_report_generator] = (
        _mock_sentiment_report_generator
    )
    test_app.dependency_overrides[get_sentiment_service] = _mock_sentiment_service
    test_app.dependency_overrides[get_notification_dispatcher] = (
        _mock_notification_dispatcher
    )
    test_app.dependency_overrides[get_sentinel_config_service] = (
        _mock_sentinel_config_service
    )
    test_app.dependency_overrides[get_redis] = _mock_redis
    # DB-backed services — prevent writes to real data/agent.db (I-030 fix)
    test_app.dependency_overrides[get_portfolio_store] = _mock_portfolio_store
    test_app.dependency_overrides[get_capital_service] = _mock_capital_service
    test_app.dependency_overrides[get_watchlist_service] = _mock_watchlist_service_db
    test_app.dependency_overrides[get_trade_service] = _mock_trade_service
    test_app.dependency_overrides[get_user_config_service] = _mock_user_config_service
    test_app.dependency_overrides[get_agent_service] = _mock_agent_service
    test_app.dependency_overrides[get_intelligence_hub_service] = (
        _mock_intelligence_hub_service
    )
    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    """FastAPI TestClient backed by the full mock app."""
    return TestClient(app)
