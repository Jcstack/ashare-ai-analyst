"""Tests for MacroRadarService — keyword matching, threshold breaches, signal generation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.market_intelligence.macro_radar import MacroRadarService
from src.web.schemas.market_signal import RiskLevel, SignalType


@pytest.fixture()
def config():
    return {
        "commodity_sector_map": {
            "gold": {
                "yf_symbol": "GC=F",
                "display": "国际金价",
                "sectors": ["黄金", "贵金属"],
                "representative_stocks": ["600489"],
                "threshold_pct": 2.0,
            },
            "crude_oil": {
                "yf_symbol": "CL=F",
                "display": "WTI原油",
                "sectors": ["石油石化"],
                "representative_stocks": ["600028"],
                "inverse_sectors": ["航空运输"],
                "threshold_pct": 3.0,
            },
        },
        "index_sentiment_map": {
            "vix": {
                "yf_symbol": "^VIX",
                "display": "恐慌指数",
                "extreme_threshold": 25.0,
            },
            "sp500": {
                "yf_symbol": "^GSPC",
                "display": "标普500",
                "impact": "A股整体情绪",
                "threshold_pct": 2.0,
            },
        },
        "macro_keywords": {
            "geopolitical": ["战争", "制裁", "tariff"],
            "monetary_policy": ["降息", "加息", "Fed"],
            "systemic_risk": ["黑天鹅", "暴雷"],
        },
        "trigger_rules": {
            "min_keyword_matches": 1,
            "min_source_weight": 0.60,
            "cooldown_minutes": 0,  # disable cooldown for testing
        },
    }


@pytest.fixture()
def mock_global_fetcher():
    fetcher = MagicMock()
    fetcher.fetch_global_snapshot.return_value = {
        "indices": [
            {"symbol": "^VIX", "price": 30.0, "pct_change": 10.0},
            {"symbol": "^GSPC", "price": 5000.0, "pct_change": -3.0},
        ],
        "commodities": [
            {"symbol": "GC=F", "price": 2100.0, "pct_change": 3.5},
            {"symbol": "CL=F", "price": 80.0, "pct_change": 1.0},
        ],
        "currencies": [],
    }
    return fetcher


@pytest.fixture()
def mock_info_store():
    store = MagicMock()
    store.get_feed.return_value = [
        {
            "title": "美联储宣布降息25个基点",
            "summary": "Fed降息利好全球市场",
            "category": "macro",
            "source_name": "Reuters",
            "published_at": "2026-03-03 10:00:00",
        },
        {
            "title": "中东制裁升级引发油价波动",
            "summary": "地缘政治紧张加剧",
            "category": "global",
            "source_name": "Bloomberg",
            "published_at": "2026-03-03 09:00:00",
        },
        {
            "title": "某公司发布新产品",
            "summary": "技术创新推动增长",
            "category": "company",
            "source_name": "Sina",
            "published_at": "2026-03-03 08:00:00",
        },
    ]
    return store


@pytest.fixture()
def service(config, mock_global_fetcher, mock_info_store):
    return MacroRadarService(
        global_fetcher=mock_global_fetcher,
        info_store=mock_info_store,
        config=config,
    )


class TestScanGlobalMarkets:
    def test_commodity_threshold_breach(self, service):
        """Gold +3.5% exceeds 2% threshold → signal generated."""
        signals = service.scan_global_markets()
        gold_signals = [
            s for s in signals
            if "金价" in (s.summary_short or "")
        ]
        assert len(gold_signals) == 1
        assert gold_signals[0].signal_type == SignalType.S8_MACRO_DRIVEN
        assert gold_signals[0].producer == "macro_radar"
        assert "600489" in gold_signals[0].assets

    def test_commodity_below_threshold_no_signal(self, service):
        """Oil +1.0% below 3% threshold → no signal."""
        signals = service.scan_global_markets()
        oil_signals = [
            s for s in signals
            if "原油" in (s.summary_short or "")
        ]
        assert len(oil_signals) == 0

    def test_vix_extreme(self, service):
        """VIX=30 > 25 threshold → extreme risk signal."""
        signals = service.scan_global_markets()
        vix_signals = [
            s for s in signals
            if "VIX" in (s.summary_short or "")
        ]
        assert len(vix_signals) == 1
        assert vix_signals[0].risk_level == RiskLevel.EXTREME

    def test_index_threshold_breach(self, service):
        """S&P 500 -3% exceeds 2% threshold → signal generated."""
        signals = service.scan_global_markets()
        sp_signals = [
            s for s in signals
            if "标普" in (s.summary_short or "")
        ]
        assert len(sp_signals) == 1

    def test_global_fetcher_failure_returns_empty(self, service, mock_global_fetcher):
        """Fetcher failure → returns empty list gracefully."""
        mock_global_fetcher.fetch_global_snapshot.side_effect = Exception("timeout")
        signals = service.scan_global_markets()
        assert signals == []


class TestScanMacroIntel:
    def test_keyword_matching(self, service):
        """Macro keywords should match geopolitical and monetary_policy items."""
        signals = service.scan_macro_intel()
        categories_found = set()
        for s in signals:
            if "货币政策" in (s.summary_short or ""):
                categories_found.add("monetary_policy")
            if "地缘政治" in (s.summary_short or ""):
                categories_found.add("geopolitical")
        assert "monetary_policy" in categories_found
        assert "geopolitical" in categories_found

    def test_company_category_filtered_out(self, service):
        """Company-category items should not produce macro signals."""
        signals = service.scan_macro_intel()
        for s in signals:
            assert "新产品" not in (s.summary_detailed or "")

    def test_info_store_failure_returns_empty(self, service, mock_info_store):
        """InfoStore failure → returns empty list gracefully."""
        mock_info_store.get_feed.side_effect = Exception("db error")
        signals = service.scan_macro_intel()
        assert signals == []


class TestScanAll:
    def test_scan_all_returns_counts(self, service):
        """scan_all() returns dict with category counts."""
        result = service.scan_all()
        assert "global_market" in result
        assert "macro_intel" in result
        assert "total" in result
        assert result["total"] == result["global_market"] + result["macro_intel"]

    def test_scan_all_with_signals_returns_objects(self, service):
        """scan_all_with_signals() returns MarketSignal objects."""
        signals = service.scan_all_with_signals()
        assert len(signals) > 0
        for s in signals:
            assert s.signal_type == SignalType.S8_MACRO_DRIVEN


class TestCooldown:
    def test_cooldown_prevents_duplicate_signals(self, config, mock_global_fetcher, mock_info_store):
        """Same commodity breach should not generate duplicate signals within cooldown."""
        config["trigger_rules"]["cooldown_minutes"] = 999
        svc = MacroRadarService(
            global_fetcher=mock_global_fetcher,
            info_store=mock_info_store,
            config=config,
        )
        first = svc.scan_global_markets()
        second = svc.scan_global_markets()
        # First scan generates signals, second is suppressed by cooldown
        assert len(first) > 0
        assert len(second) == 0


class TestConfigLoading:
    def test_empty_config_graceful(self):
        """Service should work with empty config — no crashes."""
        svc = MacroRadarService(
            global_fetcher=MagicMock(),
            info_store=MagicMock(),
            config={},
        )
        result = svc.scan_all()
        assert result["total"] == 0
