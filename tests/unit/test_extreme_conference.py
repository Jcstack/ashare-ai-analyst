"""Tests for ExtremeMarketConference trigger conditions and convene logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.orchestration.extreme_market_conference import (
    ConferenceResult,
    ExtremeMarketConference,
)


class TestVixPanicTrigger:
    def test_vix_above_threshold(self):
        fetcher = MagicMock()
        fetcher.fetch_global_snapshot.return_value = {
            "vix": {"price": 30.0},
        }
        conf = ExtremeMarketConference(global_market_fetcher=fetcher)
        should, reason = conf.should_convene(["600519"])
        assert should is True
        assert "VIX" in reason

    def test_vix_below_threshold(self):
        fetcher = MagicMock()
        fetcher.fetch_global_snapshot.return_value = {
            "vix": {"price": 18.0},
        }
        conf = ExtremeMarketConference(global_market_fetcher=fetcher)
        should, reason = conf.should_convene(["600519"])
        # VIX is fine, no other conditions → should not convene
        assert should is False

    def test_vix_fetcher_failure(self):
        fetcher = MagicMock()
        fetcher.fetch_global_snapshot.side_effect = Exception("network error")
        conf = ExtremeMarketConference(global_market_fetcher=fetcher)
        # Should gracefully return False
        should, _ = conf.should_convene(["600519"])
        assert should is False


class TestStockAmplitudeTrigger:
    def test_high_amplitude(self):
        stock_svc = MagicMock()
        stock_svc.get_realtime_data.return_value = {
            "high": 110.0,
            "low": 100.0,
            "prev_close": 105.0,
        }
        conf = ExtremeMarketConference(stock_service=stock_svc)
        should, reason = conf.should_convene(["600519"])
        assert should is True
        assert "振幅" in reason

    def test_normal_amplitude(self):
        stock_svc = MagicMock()
        stock_svc.get_realtime_data.return_value = {
            "high": 102.0,
            "low": 100.0,
            "prev_close": 101.0,
        }
        conf = ExtremeMarketConference(stock_service=stock_svc)
        should, _ = conf.should_convene(["600519"])
        assert should is False

    def test_no_realtime_data(self):
        stock_svc = MagicMock()
        stock_svc.get_realtime_data.return_value = None
        conf = ExtremeMarketConference(stock_service=stock_svc)
        should, _ = conf.should_convene(["600519"])
        assert should is False


class TestCumulativeReturnTrigger:
    def test_extreme_3d_return(self):
        import pandas as pd

        stock_svc = MagicMock()
        # Simulate 4 days of data with >10% drop
        df = pd.DataFrame({"close": [100.0, 95.0, 90.0, 88.0]})
        stock_svc.get_stock_data.return_value = df
        stock_svc.get_realtime_data.return_value = None  # skip amplitude check
        conf = ExtremeMarketConference(stock_service=stock_svc)
        should, reason = conf.should_convene(["600519"])
        assert should is True
        assert "累计涨跌" in reason

    def test_normal_3d_return(self):
        import pandas as pd

        stock_svc = MagicMock()
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0]})
        stock_svc.get_stock_data.return_value = df
        stock_svc.get_realtime_data.return_value = None
        conf = ExtremeMarketConference(stock_service=stock_svc)
        should, _ = conf.should_convene(["600519"])
        assert should is False


class TestExtremeMacroSignalTrigger:
    def test_critical_macro_signal(self):
        signal_store = MagicMock()
        signal_store.get_signals.return_value = [
            {
                "risk_level": "CRITICAL",
                "summary_short": "地缘冲突升级",
            }
        ]
        conf = ExtremeMarketConference(signal_store=signal_store)
        should, reason = conf.should_convene(["600519"])
        assert should is True
        assert "宏观极端信号" in reason

    def test_normal_macro_signal(self):
        signal_store = MagicMock()
        signal_store.get_signals.return_value = [
            {
                "risk_level": "LOW",
                "summary_short": "常规宏观变化",
            }
        ]
        conf = ExtremeMarketConference(signal_store=signal_store)
        should, _ = conf.should_convene(["600519"])
        assert should is False


class TestConvene:
    def test_convene_returns_result(self):
        conf = ExtremeMarketConference()
        result = conf.convene(
            trigger_reason="VIX=30 > 25",
            symbols=["600519", "000001"],
        )
        assert isinstance(result, ConferenceResult)
        assert result.convened is True
        assert result.trigger_reason == "VIX=30 > 25"
        assert "600519" in result.symbols

    def test_convene_default_action_is_hold(self):
        conf = ExtremeMarketConference()
        result = conf.convene(
            trigger_reason="test",
            symbols=["600519"],
        )
        assert result.action == "hold"
        assert result.risk_veto is False


class TestNoServicesGraceful:
    """Test that all checks gracefully handle None services."""

    def test_no_services(self):
        conf = ExtremeMarketConference()
        should, _ = conf.should_convene(["600519"])
        assert should is False

    def test_empty_symbols(self):
        conf = ExtremeMarketConference()
        should, _ = conf.should_convene([])
        assert should is False
