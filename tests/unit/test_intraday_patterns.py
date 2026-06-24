"""Tests for IntradayPatternDetector — intraday pattern detection."""

from __future__ import annotations

import pandas as pd
import pytest
from datetime import datetime, timedelta


def _make_bars(n: int = 48, base: float = 10.0, trend: float = 0.0) -> pd.DataFrame:
    """Create synthetic 5-minute bars for a full trading day."""
    dates = []
    dt = datetime(2026, 3, 10, 9, 30)
    for i in range(n):
        if i < 24:
            dates.append(dt + timedelta(minutes=i * 5))
        else:
            dates.append(datetime(2026, 3, 10, 13, 0) + timedelta(minutes=(i - 24) * 5))
    prices = [base * (1 + trend * i) for i in range(n)]
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": [p * 0.999 for p in prices],
            "high": [p * 1.005 for p in prices],
            "low": [p * 0.995 for p in prices],
            "close": prices,
            "volume": [100000] * n,
            "amount": [p * 100000 for p in prices],
        }
    )


class TestIntradayPatternDetector:
    @pytest.fixture()
    def detector(self):
        from src.agent_loop.intraday_patterns import IntradayPatternDetector

        return IntradayPatternDetector()

    def test_detect_all_returns_list(self, detector):
        bars = _make_bars()
        quote = {
            "price": 10.0,
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "prev_close": 10.0,
            "volume": 1000000,
        }
        result = detector.detect_all("600519", bars, quote, prev_close=10.0)
        assert isinstance(result, list)

    def test_high_reversal_detection(self, detector):
        """Should detect 冲高回落 when price drops significantly from intraday high."""
        bars = _make_bars(trend=0.003)
        # Last bars drop sharply from high
        for i in range(-8, 0):
            bars.loc[bars.index[i], "close"] = 10.0 * 0.93
            bars.loc[bars.index[i], "high"] = 10.0 * 0.94
            bars.loc[bars.index[i], "low"] = 10.0 * 0.92

        high = bars["high"].max()
        current = bars["close"].iloc[-1]
        quote = {
            "price": current,
            "open": 10.0,
            "high": high,
            "low": current * 0.99,
            "prev_close": 10.0,
            "volume": 1000000,
        }

        patterns = detector.detect_all("600519", bars, quote, prev_close=10.0)
        types = [p.pattern_type for p in patterns]
        assert "high_reversal" in types

    def test_gap_down_rally_detection(self, detector):
        """Should detect 低开高走 — opened 3% below prev_close, rallied 3%+ from open."""
        bars = _make_bars(base=9.7, trend=0.003)
        current_price = 10.2
        quote = {
            "price": current_price,
            "open": 9.7,
            "high": 10.3,
            "low": 9.65,
            "prev_close": 10.0,
            "volume": 1000000,
        }

        patterns = detector.detect_all("600519", bars, quote, prev_close=10.0)
        types = [p.pattern_type for p in patterns]
        assert "gap_down_rally" in types

    def test_no_patterns_in_flat_market(self, detector):
        """Flat price action should produce no/few patterns."""
        bars = _make_bars(trend=0.0)
        quote = {
            "price": 10.0,
            "open": 10.0,
            "high": 10.05,
            "low": 9.95,
            "prev_close": 10.0,
            "volume": 1000000,
        }

        patterns = detector.detect_all("600519", bars, quote, prev_close=10.0)
        # Should have zero or very low-severity patterns
        significant = [p for p in patterns if p.severity > 0.3]
        assert len(significant) == 0

    def test_pattern_has_required_fields(self, detector):
        """All detected patterns must have required fields with valid values."""
        bars = _make_bars(trend=0.005)
        for i in range(-8, 0):
            bars.loc[bars.index[i], "close"] = 10.0 * 0.93
            bars.loc[bars.index[i], "high"] = 10.0 * 0.94
        high = bars["high"].max()
        quote = {
            "price": 9.3,
            "open": 10.0,
            "high": high,
            "low": 9.2,
            "prev_close": 10.0,
            "volume": 1000000,
        }

        patterns = detector.detect_all("600519", bars, quote, prev_close=10.0)
        for p in patterns:
            assert hasattr(p, "pattern_type")
            assert hasattr(p, "symbol")
            assert hasattr(p, "severity")
            assert hasattr(p, "direction")
            assert hasattr(p, "description")
            assert p.direction in ("bullish", "bearish")
            assert 0.0 <= p.severity <= 1.0
            assert p.symbol == "600519"

    def test_empty_bars(self, detector):
        """Should handle empty bars gracefully."""
        quote = {
            "price": 10.0,
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "prev_close": 10.0,
            "volume": 0,
        }
        result = detector.detect_all("600519", pd.DataFrame(), quote, prev_close=10.0)
        assert result == []

    def test_none_bars(self, detector):
        """Should handle None bars gracefully."""
        quote = {
            "price": 10.0,
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "prev_close": 10.0,
            "volume": 0,
        }
        result = detector.detect_all("600519", None, quote, prev_close=10.0)
        assert result == []

    def test_too_few_bars_returns_empty(self, detector):
        """Fewer than 6 bars should return empty list (detector threshold)."""
        bars = _make_bars(n=5)
        quote = {
            "price": 10.0,
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "prev_close": 10.0,
            "volume": 100000,
        }
        result = detector.detect_all("600519", bars, quote, prev_close=10.0)
        assert result == []

    def test_patterns_sorted_by_severity(self, detector):
        """Returned patterns should be sorted by severity descending."""
        bars = _make_bars(trend=0.005)
        # Create conditions for multiple patterns
        for i in range(-8, 0):
            bars.loc[bars.index[i], "close"] = 10.0 * 0.92
            bars.loc[bars.index[i], "high"] = 10.0 * 0.93
            bars.loc[bars.index[i], "volume"] = 50000  # volume dropping
        high = bars["high"].max()
        quote = {
            "price": 9.2,
            "open": 10.0,
            "high": high,
            "low": 9.1,
            "prev_close": 10.0,
            "volume": 800000,
        }

        patterns = detector.detect_all("600519", bars, quote, prev_close=10.0)
        if len(patterns) > 1:
            for i in range(len(patterns) - 1):
                assert patterns[i].severity >= patterns[i + 1].severity

    def test_detect_batch(self, detector):
        """detect_batch should process multiple symbols."""
        bars1 = _make_bars()
        bars2 = _make_bars(trend=0.005)
        quote1 = {
            "price": 10.0,
            "open": 10.0,
            "high": 10.05,
            "low": 9.95,
            "prev_close": 10.0,
            "volume": 100000,
        }
        quote2 = {
            "price": 10.5,
            "open": 10.0,
            "high": 10.6,
            "low": 9.9,
            "prev_close": 10.0,
            "volume": 200000,
        }
        symbols_data = {
            "600519": (bars1, quote1),
            "000001": (bars2, quote2),
        }
        result = detector.detect_batch(symbols_data)
        assert isinstance(result, dict)
        assert "600519" in result
        assert "000001" in result
        assert isinstance(result["600519"], list)
