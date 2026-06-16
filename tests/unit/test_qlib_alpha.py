"""Tests for QlibAlphaEngine — alpha factor computation."""

from unittest.mock import MagicMock

from src.quant.qlib_alpha import AlphaFactors, QlibAlphaEngine


class TestAlphaFactors:
    def test_default_scores(self):
        f = AlphaFactors(symbol="600519")
        assert f.momentum_score == 0.5
        assert f.volatility_score == 0.5
        assert f.liquidity_score == 0.5
        assert f.composite_score == 0.5
        assert f.available is False

    def test_with_factors(self):
        f = AlphaFactors(
            symbol="600519",
            factors={
                "momentum_5d": 0.7,
                "momentum_20d": 0.6,
                "volatility_20d": 0.3,
                "turnover_ratio": 0.8,
                "quality_score": 0.9,
            },
            available=True,
        )
        assert abs(f.momentum_score - 0.65) < 1e-9
        assert abs(f.volatility_score - 0.7) < 1e-9
        assert abs(f.liquidity_score - 0.8) < 1e-9
        assert f.composite_score > 0.5

    def test_to_dict(self):
        f = AlphaFactors(symbol="600519", available=True, factors={"momentum_5d": 0.6})
        d = f.to_dict()
        assert d["symbol"] == "600519"
        assert d["available"] is True
        assert "composite_score" in d


class TestQlibAlphaEngine:
    def test_no_adapter(self):
        engine = QlibAlphaEngine(qlib_adapter=None)
        result = engine.compute_factors("600519")
        assert result.available is False

    def test_adapter_unavailable(self):
        mock = MagicMock()
        mock.is_available.return_value = False
        engine = QlibAlphaEngine(qlib_adapter=mock)
        result = engine.compute_factors("600519")
        assert result.available is False

    def test_adapter_returns_factors(self):
        mock = MagicMock()
        mock.is_available.return_value = True
        mock.get_alpha_factors.return_value = {
            "momentum_5d": 0.03,
            "momentum_20d": -0.01,
            "volatility_20d": 0.15,
            "turnover_ratio": 1.2,
            "price_to_ma20": 0.02,
        }
        engine = QlibAlphaEngine(qlib_adapter=mock)
        result = engine.compute_factors("600519")
        assert result.available is True
        assert "momentum_5d" in result.factors
        assert "quality_score" in result.factors
        assert 0 <= result.composite_score <= 1

    def test_adapter_returns_none(self):
        mock = MagicMock()
        mock.is_available.return_value = True
        mock.get_alpha_factors.return_value = None
        engine = QlibAlphaEngine(qlib_adapter=mock)
        result = engine.compute_factors("600519")
        assert result.available is False

    def test_compute_batch(self):
        mock = MagicMock()
        mock.is_available.return_value = True
        mock.get_alpha_factors.return_value = {"momentum_5d": 0.05}
        engine = QlibAlphaEngine(qlib_adapter=mock)
        batch = engine.compute_batch(["600519", "000001"])
        assert len(batch) == 2
        assert "600519" in batch
        assert "000001" in batch

    def test_adapter_exception(self):
        mock = MagicMock()
        mock.is_available.return_value = True
        mock.get_alpha_factors.side_effect = RuntimeError("connection lost")
        engine = QlibAlphaEngine(qlib_adapter=mock)
        result = engine.compute_factors("600519")
        assert result.available is False
