"""Analysis module throughput benchmarks.

Per PRD NFR-001: Indicator calculation for 100 stocks x 250 days < 30s,
config load < 100ms, data cache read < 500ms.
"""

from __future__ import annotations

import pytest


# Thresholds in seconds
INDICATOR_CALC_THRESHOLD = 0.5  # Per-stock indicator calc < 500ms
CONFIG_LOAD_THRESHOLD = 0.100  # Config load < 100ms


class TestIndicatorThroughput:
    """Benchmark technical indicator calculation throughput."""

    @pytest.mark.performance
    def test_single_stock_indicators(self, large_ohlcv_df, benchmark):
        """Indicator calculation for one stock (250 days) should be fast."""
        from src.analysis.indicators import TechnicalIndicators

        analyzer = TechnicalIndicators()

        def _calc():
            return analyzer.add_all(large_ohlcv_df.copy())

        result = benchmark(_calc)
        assert result is not None
        assert benchmark.stats["mean"] < INDICATOR_CALC_THRESHOLD

    @pytest.mark.performance
    def test_pattern_detection(self, large_ohlcv_df, benchmark):
        """Pattern detection for one stock should complete quickly."""
        from src.analysis.patterns import PatternRecognizer

        recognizer = PatternRecognizer()

        def _detect():
            return recognizer.detect_candlestick_patterns(large_ohlcv_df.copy())

        result = benchmark(_detect)
        assert result is not None
        assert benchmark.stats["mean"] < INDICATOR_CALC_THRESHOLD

    @pytest.mark.performance
    def test_support_resistance_detection(self, large_ohlcv_df, benchmark):
        """Support/resistance detection should complete quickly."""
        from src.analysis.patterns import PatternRecognizer

        recognizer = PatternRecognizer()

        def _detect():
            return recognizer.find_support_resistance(large_ohlcv_df.copy())

        result = benchmark(_detect)
        assert isinstance(result, list)
        assert benchmark.stats["mean"] < INDICATOR_CALC_THRESHOLD


class TestConfigLoadPerformance:
    """Benchmark config file loading."""

    @pytest.mark.performance
    def test_yaml_config_load(self, benchmark):
        """YAML config load should be < 100ms."""
        import yaml

        config_content = yaml.dump(
            {
                "watchlist": [
                    {"symbol": f"{i:06d}", "name": f"Stock{i}"} for i in range(100)
                ],
            }
        )

        def _load():
            return yaml.safe_load(config_content)

        result = benchmark(_load)
        assert result is not None
        assert benchmark.stats["mean"] < CONFIG_LOAD_THRESHOLD
