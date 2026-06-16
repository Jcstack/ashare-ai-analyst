"""Tests for src.data.quality_gate — DataQualityGate validation."""

from src.data.quality_gate import DataQualityGate


class TestValidateQuote:
    def test_none_quote_scores_zero(self):
        gate = DataQualityGate()
        result = gate.validate_quote(None)
        assert result.score == 0
        assert "无行情数据" in result.warnings[0]

    def test_empty_quote_scores_zero(self):
        gate = DataQualityGate()
        result = gate.validate_quote({})
        assert result.score < 50

    def test_valid_quote_scores_high(self):
        gate = DataQualityGate()
        quote = {"price": 35.5, "volume": 1000000, "high": 36.0, "low": 35.0}
        result = gate.validate_quote(quote)
        assert result.score == 100
        assert result.warnings == []

    def test_nan_field_detected(self):
        gate = DataQualityGate()
        quote = {"price": 35.5, "volume": 1000, "change_pct": float("nan")}
        result = gate.validate_quote(quote)
        assert any("NaN" in w for w in result.warnings)

    def test_ohlc_inconsistency(self):
        gate = DataQualityGate()
        quote = {"price": 40.0, "volume": 1000, "high": 36.0, "low": 35.0}
        result = gate.validate_quote(quote)
        assert any("OHLC" in w for w in result.warnings)


class TestValidateIndicators:
    def test_none_indicators_scores_zero(self):
        gate = DataQualityGate()
        result = gate.validate_indicators(None)
        assert result.score == 0

    def test_valid_indicators_scores_high(self):
        gate = DataQualityGate()
        indicators = {
            "ma": {"ma5": 35.0, "ma10": 34.5},
            "macd": {"dif": 0.5, "dea": 0.3},
            "rsi": {"rsi6": 55.0},
            "kdj": {"k": 60.0},
        }
        result = gate.validate_indicators(indicators)
        assert result.score == 100

    def test_few_indicators_warned(self):
        gate = DataQualityGate()
        indicators = {"ma": {"ma5": 35.0}}
        result = gate.validate_indicators(indicators)
        assert any("指标不完整" in w for w in result.warnings)


class TestValidateNews:
    def test_none_news_degraded(self):
        gate = DataQualityGate()
        result = gate.validate_news(None)
        assert result.score == 50  # degraded, not critical

    def test_valid_news(self):
        import time

        gate = DataQualityGate()
        today = time.strftime("%Y-%m-%d")
        news = [
            {"title": "大盘走势", "datetime": f"{today} 10:30:00"},
            {"title": "政策利好", "datetime": f"{today} 11:00:00"},
        ]
        result = gate.validate_news(news)
        assert result.score == 100

    def test_empty_title_warned(self):
        gate = DataQualityGate()
        news = [{"title": "", "datetime": "2026-02-15 10:00:00"}]
        result = gate.validate_news(news)
        assert any("空标题" in w for w in result.warnings)


class TestValidateAll:
    def test_combined_score_weighted(self):
        gate = DataQualityGate()
        result = gate.validate_all(
            quote={"price": 35.5, "volume": 1000, "high": 36.0, "low": 35.0},
            indicators={"ma": {"ma5": 35}, "macd": {"dif": 0.5}, "rsi": {"rsi6": 55}},
            news=None,
        )
        # quote=100*0.4 + indicators=100*0.35 + news=50*0.25 = 87.5
        assert result.score >= 85
        assert result.checks_total > 0

    def test_all_none_scores_low(self):
        gate = DataQualityGate()
        result = gate.validate_all()
        assert result.score < 30
