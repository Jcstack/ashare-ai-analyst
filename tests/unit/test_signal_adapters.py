"""Tests for IntelReportAdapter, RecommendationAdapter, and SignalBridge."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.market_intelligence.signal_bridge import SignalBridge
from src.market_intelligence.signal_bus import (
    IntelReportAdapter,
    RecommendationAdapter,
)
from src.web.schemas.market_signal import SignalType


class TestIntelReportAdapter:
    def test_convert_bullish_report(self):
        report = {
            "symbol": "600519",
            "signal": "bullish",
            "confidence": 0.8,
            "summary": "贵州茅台受益于消费复苏预期",
            "intel_summary": "多条利好消息",
        }
        signal = IntelReportAdapter.convert(report)
        assert signal.signal_type == SignalType.S7_POLICY_DRIVEN
        assert "600519" in signal.assets
        assert signal.confidence_score == 80.0
        assert signal.producer == "intel_report"

    def test_convert_macro_report_no_assets(self):
        report = {
            "symbol": "MACRO",
            "signal": "bearish",
            "confidence": 0.6,
            "summary": "宏观风险事件",
        }
        signal = IntelReportAdapter.convert(report)
        assert signal.assets == []
        assert signal.confidence_score == 60.0

    def test_convert_neutral_report(self):
        report = {
            "symbol": "000001",
            "signal": "neutral",
            "confidence": 0.5,
            "summary": "平安银行无明显方向",
        }
        signal = IntelReportAdapter.convert(report)
        assert signal.signal_type == SignalType.S7_POLICY_DRIVEN


class TestRecommendationAdapter:
    def test_convert_buy_recommendation(self):
        rec = {
            "symbol": "600036",
            "action": "buy",
            "confidence": 0.75,
            "style": "growth",
            "reason": "成长股优选",
        }
        signal = RecommendationAdapter.convert(rec)
        assert signal.signal_type == SignalType.S1_TREND
        assert "600036" in signal.assets
        assert signal.confidence_score == 75.0
        assert signal.producer == "recommendation"

    def test_convert_sell_recommendation(self):
        rec = {
            "symbol": "601398",
            "action": "sell",
            "confidence": 0.6,
            "style": "value",
        }
        signal = RecommendationAdapter.convert(rec)
        assert "sell" in signal.summary_short
        assert signal.confidence_score == 60.0


class TestSignalBridge:
    def test_publish_with_redis(self):
        redis_mock = MagicMock()
        bridge = SignalBridge(redis_client=redis_mock)
        result = bridge.publish({"test": "data"})
        assert result is True
        redis_mock.publish.assert_called_once()

    def test_publish_without_redis(self):
        bridge = SignalBridge(redis_client=None)
        result = bridge.publish({"test": "data"})
        assert result is False

    def test_publish_from_report(self):
        redis_mock = MagicMock()
        bridge = SignalBridge(redis_client=redis_mock)
        result = bridge.publish_from_report({
            "symbol": "600519",
            "signal": "bullish",
            "confidence": 0.8,
            "summary": "test",
            "action": "buy",
        })
        assert result is True

    def test_publish_from_recommendation(self):
        redis_mock = MagicMock()
        bridge = SignalBridge(redis_client=redis_mock)
        result = bridge.publish_from_recommendation({
            "symbol": "600036",
            "action": "buy",
            "confidence": 0.7,
            "style": "growth",
        })
        assert result is True

    def test_publish_failure_graceful(self):
        redis_mock = MagicMock()
        redis_mock.publish.side_effect = Exception("connection error")
        bridge = SignalBridge(redis_client=redis_mock)
        result = bridge.publish({"test": "data"})
        assert result is False
