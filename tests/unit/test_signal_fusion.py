"""Tests for SignalFusionEngine — Bayesian multi-source signal fusion."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.prediction.signal_fusion import SignalFusionEngine

_RESEARCH_CONFIG = {
    "bayesian_fusion": {
        "weights": {
            "sentinel": 0.25,
            "actuary": 0.35,
            "technical": 0.40,
        },
        "renormalize_on_missing": True,
        "thresholds": {
            "strong_buy": 0.75,
            "buy": 0.60,
            "neutral_high": 0.55,
            "neutral_low": 0.45,
            "sell": 0.40,
            "strong_sell": 0.25,
        },
        "labels": {
            "strong_buy": "强烈看多",
            "buy": "看多",
            "neutral": "中性",
            "sell": "看空",
            "strong_sell": "强烈看空",
        },
    },
    "ashare_constraints": {
        "main_board_limit": 0.10,
        "chinext_star_limit": 0.20,
        "t_plus_1": True,
        "sentiment_damping": 0.8,
    },
}


class TestFuseAllSources:
    """Test fusion when all three sources are available."""

    def test_all_sources_bullish(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        sources = {
            "sentinel": {"score": 0.8, "fallback_used": False},
            "actuary": {"score": 0.75, "available": True},
            "technical": {"p_up": 0.7, "available": True},
        }
        result = engine.fuse("600519", sources)
        assert result["symbol"] == "600519"
        fusion = result["fusion"]
        assert fusion["confidence"] > 0.6
        assert "weights_used" in fusion
        # All three sources should be weighted
        assert len(fusion["weights_used"]) == 3

    def test_all_sources_bearish(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        sources = {
            "sentinel": {"score": 0.2, "fallback_used": False},
            "actuary": {"score": 0.2, "available": True},
            "technical": {"p_up": 0.25, "available": True},
        }
        result = engine.fuse("000001", sources)
        fusion = result["fusion"]
        assert fusion["confidence"] < 0.45
        assert "看空" in fusion["signal"]


class TestMissingSources:
    """Test re-normalization when sources are unavailable."""

    def test_no_qlib(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        sources = {
            "sentinel": {"score": 0.7, "fallback_used": False},
            "actuary": {"score": None, "available": False},
            "technical": {"p_up": 0.65, "available": True},
        }
        result = engine.fuse("600519", sources)
        fusion = result["fusion"]
        # Only sentinel + technical should be used
        assert "actuary" not in fusion["weights_used"]
        assert len(fusion["weights_used"]) == 2
        # Weights should be re-normalized to sum to 1.0
        total = sum(fusion["weights_used"].values())
        assert abs(total - 1.0) < 0.01

    def test_only_technical(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        sources = {
            "sentinel": {"score": 0.5, "fallback_used": True},  # fallback → excluded
            "actuary": {"score": None, "available": False},
            "technical": {"p_up": 0.8, "available": True},
        }
        result = engine.fuse("600519", sources)
        fusion = result["fusion"]
        assert len(fusion["weights_used"]) == 1
        assert "technical" in fusion["weights_used"]
        assert fusion["confidence"] == 0.8

    def test_no_sources(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        sources = {
            "sentinel": {"score": None, "fallback_used": True},
            "actuary": {"score": None, "available": False},
            "technical": {"p_up": 0.5, "available": False},
        }
        result = engine.fuse("600519", sources)
        fusion = result["fusion"]
        assert fusion["confidence"] == 0.5
        assert fusion["signal"] == "中性"


class TestQlibSignal:
    """Test get_qlib_signal with mock QlibAdapter."""

    def test_qlib_available(self):
        mock_qlib = MagicMock()
        mock_qlib.is_available.return_value = True
        mock_qlib.predict.return_value = {
            "600519": {"score": 0.72, "ic": 0.05},
        }
        engine = SignalFusionEngine(qlib_adapter=mock_qlib, config=_RESEARCH_CONFIG)
        signal = engine.get_qlib_signal("600519")
        assert signal is not None
        assert signal["available"] is True
        assert signal["score"] == 0.72

    def test_qlib_unavailable(self):
        mock_qlib = MagicMock()
        mock_qlib.is_available.return_value = False
        engine = SignalFusionEngine(qlib_adapter=mock_qlib, config=_RESEARCH_CONFIG)
        signal = engine.get_qlib_signal("600519")
        assert signal is None

    def test_no_qlib_adapter(self):
        engine = SignalFusionEngine(qlib_adapter=None, config=_RESEARCH_CONFIG)
        signal = engine.get_qlib_signal("600519")
        assert signal is None


class TestAlphaFactors:
    """Test get_alpha_factors delegation."""

    def test_alpha_factors_available(self):
        mock_qlib = MagicMock()
        mock_qlib.is_available.return_value = True
        mock_qlib.get_alpha_factors.return_value = {
            "momentum_5d": 0.03,
            "volatility_20d": 0.15,
        }
        engine = SignalFusionEngine(qlib_adapter=mock_qlib, config=_RESEARCH_CONFIG)
        factors = engine.get_alpha_factors("600519")
        assert factors is not None
        assert "momentum_5d" in factors

    def test_alpha_factors_no_qlib(self):
        engine = SignalFusionEngine(qlib_adapter=None, config=_RESEARCH_CONFIG)
        factors = engine.get_alpha_factors("600519")
        assert factors is None


class TestConfidenceMapping:
    """Test confidence-to-signal label mapping."""

    def test_strong_buy(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        assert engine._confidence_to_signal(0.80) == "强烈看多"

    def test_buy(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        assert engine._confidence_to_signal(0.65) == "看多"

    def test_neutral(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        assert engine._confidence_to_signal(0.50) == "中性"

    def test_sell(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        assert engine._confidence_to_signal(0.42) == "看空"

    def test_strong_sell(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        assert engine._confidence_to_signal(0.20) == "强烈看空"


class TestConstraints:
    """Test A-share constraint detection."""

    def test_main_board(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        c = engine._check_constraints("600519")
        assert c["board"] == "Main"
        assert c["limit_pct"] == 0.10

    def test_chinext(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        c = engine._check_constraints("300750")
        assert c["board"] == "ChiNext/STAR"
        assert c["limit_pct"] == 0.20

    def test_star(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        c = engine._check_constraints("688981")
        assert c["board"] == "ChiNext/STAR"


class TestSentimentDamping:
    """Test sentiment damping in fusion."""

    def test_damping_applied(self):
        engine = SignalFusionEngine(config=_RESEARCH_CONFIG)
        sources = {
            "sentinel": {"score": 0.9, "fallback_used": False},
            "technical": {"p_up": 0.5, "available": True},
        }
        result = engine.fuse("600519", sources)
        # After damping: 0.5 + (0.9 - 0.5) * 0.8 = 0.82
        sentinel_score = result["sources"]["sentinel"]["score"]
        assert abs(sentinel_score - 0.82) < 0.01


class TestAutoGatherQlib:
    """Test that fuse() auto-gathers Qlib signal when not provided."""

    def test_auto_gather_qlib(self):
        mock_qlib = MagicMock()
        mock_qlib.is_available.return_value = True
        mock_qlib.predict.return_value = {
            "600519": {"score": 0.65, "ic": 0.04},
        }
        engine = SignalFusionEngine(qlib_adapter=mock_qlib, config=_RESEARCH_CONFIG)
        # Don't include actuary in sources — engine should auto-fetch
        sources = {
            "technical": {"p_up": 0.6, "available": True},
        }
        result = engine.fuse("600519", sources)
        assert result["sources"]["actuary"]["available"] is True
        assert result["sources"]["actuary"]["score"] == 0.65
