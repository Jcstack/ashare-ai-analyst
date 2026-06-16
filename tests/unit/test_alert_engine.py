"""Unit tests for src/analysis/alerts.py — AlertEngine.

Tests volume_spike, price_limit, rsi_extreme, ma_crossover, and
bollinger_breakout alert detection with configurable thresholds.

Per PRD v2.0 FR-AD002: Rule-based alert engine.
Mock strategy: Only mock load_config (external config dependency).
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Sample config matching config/agent.yaml anomaly section
# ---------------------------------------------------------------------------
SAMPLE_AGENT_CONFIG: dict = {
    "anomaly": {
        "volume_spike_threshold": 2.0,
        "price_limit_proximity": 0.02,
        "rsi_overbought": 80,
        "rsi_oversold": 20,
        "ma_cross_periods": [5, 20],
        "bollinger_period": 20,
        "bollinger_std": 2.0,
    },
}


@pytest.fixture
def alert_engine():
    """Create an AlertEngine with test config."""
    with patch("src.analysis.alerts.load_config") as mock_cfg:
        mock_cfg.return_value = SAMPLE_AGENT_CONFIG
        from src.analysis.alerts import AlertEngine

        yield AlertEngine(config_name="agent")


@pytest.fixture
def sample_ohlcv_30d():
    """30-day OHLCV DataFrame for volume spike testing."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=30, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * 30,
            "close": [10.1] * 30,
            "high": [10.3] * 30,
            "low": [9.9] * 30,
            "volume": [1000000] * 30,
            "amount": [1e7] * 30,
        }
    )


class TestCheckAlerts:
    """Tests for AlertEngine.check_alerts() dispatch."""

    def test_returns_list(self, alert_engine):
        """check_alerts should always return a list."""
        result = alert_engine.check_alerts(
            symbol="000001",
            name="平安银行",
        )
        assert isinstance(result, list)

    def test_no_data_returns_empty(self, alert_engine):
        """No input data should produce no alerts."""
        result = alert_engine.check_alerts(
            symbol="000001",
            name="平安银行",
        )
        assert len(result) == 0

    def test_alert_has_required_fields(self, alert_engine, sample_ohlcv_30d):
        """Each alert should have standard fields (id, type, severity, etc.)."""
        quote = {"price": 10.50, "volume": 3000000, "prev_close": 10.20}
        result = alert_engine.check_alerts(
            symbol="000001",
            name="平安银行",
            quote=quote,
            ohlcv_df=sample_ohlcv_30d,
        )
        if result:
            alert = result[0]
            assert "id" in alert
            assert "alert_type" in alert
            assert "severity" in alert
            assert "title" in alert
            assert "description" in alert


class TestVolumeSpike:
    """Tests for volume spike detection."""

    def test_volume_spike_detected(self, alert_engine, sample_ohlcv_30d):
        """Volume 3x above 20-day average should trigger alert."""
        quote = {"volume": 3000000}  # 3x the 1M average
        alerts = alert_engine._check_volume_spike(
            "000001",
            "平安银行",
            quote,
            sample_ohlcv_30d,
        )
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "volume_spike"

    def test_normal_volume_no_alert(self, alert_engine, sample_ohlcv_30d):
        """Volume within normal range should not trigger alert."""
        quote = {"volume": 1200000}  # 1.2x, below 2.0 threshold
        alerts = alert_engine._check_volume_spike(
            "000001",
            "平安银行",
            quote,
            sample_ohlcv_30d,
        )
        assert len(alerts) == 0

    def test_critical_severity_at_3x(self, alert_engine, sample_ohlcv_30d):
        """Volume 3x+ should be critical severity, not just warning."""
        quote = {"volume": 3500000}  # 3.5x
        alerts = alert_engine._check_volume_spike(
            "000001",
            "平安银行",
            quote,
            sample_ohlcv_30d,
        )
        assert alerts[0]["severity"] == "critical"

    def test_insufficient_history_no_alert(self, alert_engine):
        """DataFrame with <20 rows should not produce volume spike alert."""
        short_df = pd.DataFrame({"volume": [1000000] * 10})
        quote = {"volume": 5000000}
        alerts = alert_engine._check_volume_spike(
            "000001",
            "平安银行",
            quote,
            short_df,
        )
        assert len(alerts) == 0


class TestPriceLimit:
    """Tests for price limit proximity detection."""

    def test_near_limit_up_detected(self, alert_engine):
        """Price within 2% of limit-up should trigger alert (main board)."""
        # prev_close=10, limit_up=11, price=10.85 => distance ~1.4%
        quote = {"price": 10.85, "prev_close": 10.0}
        alerts = alert_engine._check_price_limit("000001", "平安银行", quote, "main")
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "near_limit_up"
        assert alerts[0]["severity"] == "critical"

    def test_near_limit_down_detected(self, alert_engine):
        """Price within 2% of limit-down should trigger alert."""
        # prev_close=10, limit_down=9, price=9.10 => distance ~1.1%
        quote = {"price": 9.10, "prev_close": 10.0}
        alerts = alert_engine._check_price_limit("000001", "平安银行", quote, "main")
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "near_limit_down"

    def test_chinext_uses_20pct_limit(self, alert_engine):
        """ChiNext board should use +-20% limits."""
        # prev_close=10, limit_up=12, price=11.80 => distance ~1.7%
        quote = {"price": 11.80, "prev_close": 10.0}
        alerts = alert_engine._check_price_limit("300001", "创业板股", quote, "chinext")
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "near_limit_up"

    def test_no_alert_when_far_from_limit(self, alert_engine):
        """Price far from limits should not trigger alert."""
        quote = {"price": 10.50, "prev_close": 10.0}
        alerts = alert_engine._check_price_limit("000001", "平安银行", quote, "main")
        assert len(alerts) == 0

    def test_missing_price_no_alert(self, alert_engine):
        """Missing price fields should not trigger alert."""
        quote = {"price": None, "prev_close": 10.0}
        alerts = alert_engine._check_price_limit("000001", "平安银行", quote, "main")
        assert len(alerts) == 0


class TestRSIExtreme:
    """Tests for RSI overbought/oversold detection."""

    def test_rsi_overbought_detected(self, alert_engine):
        """RSI >= 80 should trigger overbought alert."""
        indicators = {"rsi": 85.0}
        alerts = alert_engine._check_rsi_extreme("000001", "平安银行", indicators)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "rsi_overbought"

    def test_rsi_oversold_detected(self, alert_engine):
        """RSI <= 20 should trigger oversold alert."""
        indicators = {"rsi": 15.0}
        alerts = alert_engine._check_rsi_extreme("000001", "平安银行", indicators)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "rsi_oversold"

    def test_rsi_normal_no_alert(self, alert_engine):
        """RSI in normal range (30-70) should not trigger alert."""
        indicators = {"rsi": 55.0}
        alerts = alert_engine._check_rsi_extreme("000001", "平安银行", indicators)
        assert len(alerts) == 0

    def test_rsi_14_key_also_works(self, alert_engine):
        """Should also check 'rsi_14' indicator key."""
        indicators = {"rsi_14": 85.0}
        alerts = alert_engine._check_rsi_extreme("000001", "平安银行", indicators)
        assert len(alerts) == 1


class TestMACrossover:
    """Tests for MA golden/death cross detection."""

    def test_golden_cross_detected(self, alert_engine):
        """MA5 slightly above MA20 should trigger golden cross."""
        indicators = {"sma_5": 10.05, "sma_20": 10.00}
        alerts = alert_engine._check_ma_crossover("000001", "平安银行", indicators)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "golden_cross"

    def test_death_cross_detected(self, alert_engine):
        """MA5 slightly below MA20 should trigger death cross."""
        indicators = {"sma_5": 9.95, "sma_20": 10.00}
        alerts = alert_engine._check_ma_crossover("000001", "平安银行", indicators)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "death_cross"

    def test_wide_gap_no_alert(self, alert_engine):
        """MAs far apart (>1%) should not trigger crossover alert."""
        indicators = {"sma_5": 10.50, "sma_20": 10.00}
        alerts = alert_engine._check_ma_crossover("000001", "平安银行", indicators)
        assert len(alerts) == 0


class TestBollingerBreakout:
    """Tests for Bollinger Band breakout detection."""

    def test_upper_breakout_detected(self, alert_engine):
        """Price above upper band should trigger breakout alert."""
        indicators = {"bb_upper": 11.0, "bb_lower": 9.0}
        quote = {"price": 11.50}
        alerts = alert_engine._check_bollinger_breakout(
            "000001",
            "平安银行",
            indicators,
            quote,
        )
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "bb_breakout_upper"

    def test_lower_breakout_detected(self, alert_engine):
        """Price below lower band should trigger breakout alert."""
        indicators = {"bb_upper": 11.0, "bb_lower": 9.0}
        quote = {"price": 8.50}
        alerts = alert_engine._check_bollinger_breakout(
            "000001",
            "平安银行",
            indicators,
            quote,
        )
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "bb_breakout_lower"

    def test_within_bands_no_alert(self, alert_engine):
        """Price within Bollinger bands should not trigger alert."""
        indicators = {"bb_upper": 11.0, "bb_lower": 9.0}
        quote = {"price": 10.0}
        alerts = alert_engine._check_bollinger_breakout(
            "000001",
            "平安银行",
            indicators,
            quote,
        )
        assert len(alerts) == 0
