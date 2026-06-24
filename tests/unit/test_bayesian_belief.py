"""Comprehensive tests for BayesianBeliefEngine.

Tests cover:
- Math utilities (_logit, _sigmoid, _log_odds_pool)
- CalibrationStore (default tables, lookups, custom overrides)
- BayesianBeliefEngine.compute_prior
- BayesianBeliefEngine.update_posterior
- BayesianBeliefEngine.infer (full pipeline)
- Signal mapping (_map_signal_to_evidence, _confidence_to_bucket)
- Posterior helpers (confidence, Kelly, summary)
- Integration: Bayesian vs heuristic averaging
"""

from __future__ import annotations

import math

import pytest

from src.agent_loop.bayesian_belief import (
    BayesianBeliefEngine,
    BayesianPosterior,
    BayesianPrior,
    CalibrationStore,
    SignalEvidence,
    _confidence_to_bucket,
    _log_odds_pool,
    _logit,
    _map_signal_to_evidence,
    _sigmoid,
)


# ============================================================
# 1. Math utilities
# ============================================================


class TestLogit:
    def test_logit_half_is_zero(self):
        assert _logit(0.5) == pytest.approx(0.0)

    def test_logit_above_half_is_positive(self):
        assert _logit(0.7) > 0

    def test_logit_below_half_is_negative(self):
        assert _logit(0.3) < 0

    def test_logit_clamps_near_zero(self):
        """_logit(0) should not be -inf due to clamping."""
        result = _logit(0.0)
        assert math.isfinite(result)
        assert result < -10  # very negative but finite

    def test_logit_clamps_near_one(self):
        """_logit(1) should not be +inf due to clamping."""
        result = _logit(1.0)
        assert math.isfinite(result)
        assert result > 10  # very positive but finite

    def test_logit_negative_values_clamped(self):
        result = _logit(-0.5)
        assert math.isfinite(result)

    def test_logit_above_one_clamped(self):
        result = _logit(1.5)
        assert math.isfinite(result)


class TestSigmoid:
    def test_sigmoid_zero_is_half(self):
        assert _sigmoid(0.0) == pytest.approx(0.5)

    def test_sigmoid_large_positive(self):
        assert _sigmoid(100.0) == pytest.approx(1.0, abs=1e-6)

    def test_sigmoid_large_negative(self):
        assert _sigmoid(-100.0) == pytest.approx(0.0, abs=1e-6)

    def test_sigmoid_positive_above_half(self):
        assert _sigmoid(1.0) > 0.5

    def test_sigmoid_negative_below_half(self):
        assert _sigmoid(-1.0) < 0.5

    def test_sigmoid_overflow_protection(self):
        """Large values should not raise OverflowError."""
        assert _sigmoid(50) == pytest.approx(1.0, abs=1e-6)
        assert _sigmoid(-50) == pytest.approx(0.0, abs=1e-6)


class TestLogitSigmoidInverse:
    """logit and sigmoid are inverse functions."""

    @pytest.mark.parametrize("p", [0.1, 0.25, 0.5, 0.75, 0.9, 0.01, 0.99])
    def test_sigmoid_of_logit_is_identity(self, p: float):
        assert _sigmoid(_logit(p)) == pytest.approx(p, abs=1e-6)

    @pytest.mark.parametrize("x", [-5, -2, -1, 0, 1, 2, 5])
    def test_logit_of_sigmoid_is_identity(self, x: float):
        assert _logit(_sigmoid(x)) == pytest.approx(x, abs=1e-4)


class TestLogOddsPool:
    def test_empty_list_returns_half(self):
        assert _log_odds_pool([]) == 0.5

    def test_single_value(self):
        assert _log_odds_pool([0.7]) == pytest.approx(0.7, abs=1e-6)

    def test_two_neutral_priors(self):
        assert _log_odds_pool([0.5, 0.5]) == pytest.approx(0.5, abs=1e-6)

    def test_symmetric_cancels_out(self):
        """0.7 bullish + 0.3 bullish (=0.7 bearish) → neutral."""
        result = _log_odds_pool([0.7, 0.3])
        assert result == pytest.approx(0.5, abs=1e-6)

    def test_two_bullish_priors(self):
        """Two identical bullish priors → same (average of identical log-odds)."""
        result = _log_odds_pool([0.8, 0.8])
        assert result > 0.5
        assert result == pytest.approx(0.8, abs=1e-6)

    def test_two_different_bullish_priors_stronger(self):
        """Two bullish priors (one stronger) → between them, shifted toward stronger."""
        result = _log_odds_pool([0.8, 0.9])
        assert result > 0.8  # stronger than the weaker one
        assert result < 0.9  # weaker than the stronger one

    def test_two_bearish_priors(self):
        result = _log_odds_pool([0.3, 0.3])
        assert result < 0.5
        assert result == pytest.approx(0.3, abs=1e-6)

    def test_weighted_pooling_shifts_toward_high_weight(self):
        """Higher weight on 0.8 should shift result toward 0.8."""
        equal_weight = _log_odds_pool([0.8, 0.4])
        heavy_on_bullish = _log_odds_pool([0.8, 0.4], weights=[3.0, 1.0])
        heavy_on_bearish = _log_odds_pool([0.8, 0.4], weights=[1.0, 3.0])

        assert heavy_on_bullish > equal_weight
        assert heavy_on_bearish < equal_weight

    def test_zero_total_weight(self):
        assert _log_odds_pool([0.7, 0.3], weights=[0.0, 0.0]) == 0.5


# ============================================================
# 2. CalibrationStore
# ============================================================


class TestCalibrationStore:
    def test_default_tables_loaded(self):
        store = CalibrationStore()
        # Should have entries for all standard signal types
        for key in [
            "recommendation",
            "capital_flow",
            "technical",
            "sentiment",
            "rotation",
            "black_swan",
            "stop_loss",
            "thesis_invalidation",
            "intraday_pattern",
            "vpin",
            "reflexivity",
            "mtf_alignment",
            "global_intelligence",
        ]:
            # Should not return 0.5 for known buckets
            p = store.get_likelihood(key, list(store._tables[key].keys())[0], "bullish")
            assert p != 0.5 or key == "rotation"  # rotation neutral is 0.47

    def test_recommendation_strong_buy_bullish(self):
        store = CalibrationStore()
        p = store.get_likelihood("recommendation", "strong_buy", "bullish")
        assert p == pytest.approx(0.72, abs=0.01)

    def test_recommendation_strong_buy_bearish(self):
        store = CalibrationStore()
        p = store.get_likelihood("recommendation", "strong_buy", "bearish")
        assert p == pytest.approx(0.18, abs=0.01)

    def test_likelihood_ratio_recommendation_strong_buy(self):
        store = CalibrationStore()
        lr = store.get_likelihood_ratio("recommendation", "strong_buy")
        assert lr == pytest.approx(4.0, abs=0.1)

    def test_likelihood_ratio_stop_loss(self):
        store = CalibrationStore()
        lr = store.get_likelihood_ratio("stop_loss", "triggered")
        # 0.08 / 0.88 ≈ 0.09
        assert lr < 0.15  # strongly bearish

    def test_unknown_signal_type(self):
        store = CalibrationStore()
        assert store.get_likelihood("nonexistent", "bucket", "bullish") == 0.5

    def test_unknown_bucket(self):
        store = CalibrationStore()
        assert (
            store.get_likelihood("recommendation", "nonexistent_bucket", "bullish")
            == 0.5
        )

    def test_unknown_type_likelihood_ratio(self):
        store = CalibrationStore()
        lr = store.get_likelihood_ratio("nonexistent", "bucket")
        assert lr == pytest.approx(1.0, abs=0.01)  # uninformative

    def test_custom_tables_override(self):
        custom = {
            "recommendation": {
                "strong_buy": (0.90, 0.05),
            },
        }
        store = CalibrationStore(custom_tables=custom)
        p = store.get_likelihood("recommendation", "strong_buy", "bullish")
        assert p == pytest.approx(0.90)
        # Other default tables should still exist
        p2 = store.get_likelihood("capital_flow", "large_inflow", "bullish")
        assert p2 == pytest.approx(0.73, abs=0.01)

    def test_custom_tables_add_new_type(self):
        custom = {"my_custom_signal": {"high": (0.80, 0.20)}}
        store = CalibrationStore(custom_tables=custom)
        assert store.get_likelihood("my_custom_signal", "high", "bullish") == 0.80
        assert store.get_likelihood("my_custom_signal", "high", "bearish") == 0.20

    def test_likelihood_ratio_zero_denominator(self):
        """P(E|bear)=0 should be capped to avoid division by zero."""
        custom = {"test": {"bucket": (0.80, 0.0)}}
        store = CalibrationStore(custom_tables=custom)
        lr = store.get_likelihood_ratio("test", "bucket")
        assert lr == 10.0  # capped


# ============================================================
# 3. BayesianBeliefEngine.compute_prior
# ============================================================


class TestComputePrior:
    def setup_method(self):
        self.engine = BayesianBeliefEngine()

    def test_default_sector_regime_near_half(self):
        prior = self.engine.compute_prior(sector="default", regime="unknown")
        assert prior.p_bullish == pytest.approx(0.5, abs=0.02)
        assert prior.p_bearish == pytest.approx(1 - prior.p_bullish)

    def test_bull_regime_above_half(self):
        prior = self.engine.compute_prior(sector="default", regime="bull")
        assert prior.p_bullish > 0.5

    def test_bear_regime_below_half(self):
        prior = self.engine.compute_prior(sector="default", regime="bear")
        assert prior.p_bullish < 0.5

    def test_quant_p_up_shifts_prior(self):
        prior_without = self.engine.compute_prior(sector="default", regime="unknown")
        prior_with = self.engine.compute_prior(
            sector="default", regime="unknown", quant_p_up=0.7
        )
        assert prior_with.p_bullish > prior_without.p_bullish

    def test_quant_p_up_low_shifts_down(self):
        prior_without = self.engine.compute_prior(sector="default", regime="unknown")
        prior_with = self.engine.compute_prior(
            sector="default", regime="unknown", quant_p_up=0.3
        )
        assert prior_with.p_bullish < prior_without.p_bullish

    def test_prior_clamped_upper(self):
        """Even with very bullish inputs, prior should not exceed 0.75."""
        prior = self.engine.compute_prior(
            sector="consumer_staples", regime="bull", quant_p_up=0.95
        )
        assert prior.p_bullish <= 0.75

    def test_prior_clamped_lower(self):
        """Even with very bearish inputs, prior should not go below 0.25."""
        prior = self.engine.compute_prior(
            sector="real_estate", regime="bear", quant_p_up=0.05
        )
        assert prior.p_bullish >= 0.25

    def test_components_populated(self):
        prior = self.engine.compute_prior(
            sector="technology", regime="bull", quant_p_up=0.6, volatility_pct=70.0
        )
        assert "sector_base_rate" in prior.components
        assert "regime" in prior.components
        assert "quant_p_up" in prior.components
        assert "volatility_adj" in prior.components

    def test_volatility_high_reduces_prior(self):
        prior_normal = self.engine.compute_prior(sector="default", regime="unknown")
        prior_high_vol = self.engine.compute_prior(
            sector="default", regime="unknown", volatility_pct=90.0
        )
        # High volatility should slightly reduce prior
        assert prior_high_vol.p_bullish <= prior_normal.p_bullish

    def test_prior_probabilities_sum_to_one(self):
        prior = self.engine.compute_prior(sector="bank", regime="volatile")
        assert prior.p_bullish + prior.p_bearish == pytest.approx(1.0)

    def test_unknown_sector_uses_default(self):
        prior_unknown = self.engine.compute_prior(
            sector="nonexistent_sector", regime="unknown"
        )
        prior_default = self.engine.compute_prior(sector="default", regime="unknown")
        assert prior_unknown.p_bullish == pytest.approx(prior_default.p_bullish)


# ============================================================
# 4. BayesianBeliefEngine.update_posterior
# ============================================================


class TestUpdatePosterior:
    def setup_method(self):
        self.engine = BayesianBeliefEngine()
        self.neutral_prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)

    def test_no_signals_returns_prior(self):
        posterior = self.engine.update_posterior(self.neutral_prior, [])
        assert posterior.p_bullish == pytest.approx(0.5, abs=1e-6)
        assert posterior.evidence_count == 0

    def test_single_bullish_signal(self):
        signals = [{"source": "recommendation", "direction": "buy", "confidence": 0.8}]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        assert posterior.p_bullish > 0.5

    def test_single_bearish_signal(self):
        signals = [{"source": "recommendation", "direction": "sell", "confidence": 0.8}]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        assert posterior.p_bullish < 0.5

    def test_multiple_bullish_compound(self):
        """Multiple bullish signals compound — posterior >> prior."""
        single = [{"source": "recommendation", "direction": "buy", "confidence": 0.8}]
        double = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.8},
            {"source": "capital_flow", "direction": "buy", "confidence": 0.8},
        ]
        post_single = self.engine.update_posterior(self.neutral_prior, single)
        post_double = self.engine.update_posterior(self.neutral_prior, double)
        assert post_double.p_bullish > post_single.p_bullish

    def test_mixed_signals_between_extremes(self):
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.8},
            {"source": "capital_flow", "direction": "sell", "confidence": 0.8},
        ]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        # Mixed signals: posterior should be between pure bullish and pure bearish
        # but not necessarily exactly 0.5 due to asymmetric table values
        assert 0.3 < posterior.p_bullish < 0.7

    def test_stop_loss_strong_bearish_shift(self):
        """Stop-loss triggered should cause strong bearish shift."""
        signals = [{"source": "stop_loss", "direction": "sell", "confidence": 0.9}]
        # Start with a bullish prior
        bullish_prior = BayesianPrior(p_bullish=0.6, p_bearish=0.4)
        posterior = self.engine.update_posterior(bullish_prior, signals)
        assert posterior.p_bullish < 0.5  # should overcome bullish prior
        assert posterior.p_bullish < bullish_prior.p_bullish

    def test_llr_capping_prevents_domination(self):
        """Single signal should not push posterior to extreme values."""
        signals = [{"source": "stop_loss", "direction": "sell", "confidence": 1.0}]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        # Even with the strongest bearish signal, posterior should not be < 0.05
        assert posterior.p_bullish > 0.05
        assert posterior.p_bullish < 0.5

    def test_posterior_probabilities_sum_to_one(self):
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.7},
            {"source": "technical", "direction": "buy", "confidence": 0.6},
        ]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        assert posterior.p_bullish + posterior.p_bearish == pytest.approx(1.0)

    def test_evidence_count_matches(self):
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.7},
            {"source": "technical", "direction": "sell", "confidence": 0.6},
            {"source": "capital_flow", "direction": "buy", "confidence": 0.5},
        ]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        assert posterior.evidence_count == 3

    def test_likelihood_contributions_populated(self):
        signals = [{"source": "recommendation", "direction": "buy", "confidence": 0.8}]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        assert len(posterior.likelihood_contributions) == 1
        contrib = posterior.likelihood_contributions[0]
        assert "source" in contrib
        assert "llr" in contrib
        assert "p_e_bull" in contrib
        assert "p_e_bear" in contrib
        assert "lr" in contrib

    def test_prior_preserved_in_posterior(self):
        posterior = self.engine.update_posterior(self.neutral_prior, [])
        assert posterior.prior is self.neutral_prior

    def test_symbol_filtering(self):
        """Signals for other symbols should be skipped."""
        signals = [
            {
                "source": "recommendation",
                "direction": "buy",
                "confidence": 0.8,
                "symbol": "600519",
            },
            {
                "source": "recommendation",
                "direction": "sell",
                "confidence": 0.8,
                "symbol": "000001",
            },
        ]
        posterior = self.engine.update_posterior(
            self.neutral_prior, signals, symbol="600519"
        )
        # Only the first signal applies; bullish
        assert posterior.p_bullish > 0.5
        assert posterior.evidence_count == 1

    def test_signal_evidence_objects(self):
        """Engine should handle SignalEvidence dataclass objects."""
        signals = [
            SignalEvidence(source="recommendation", direction="buy", strength=0.8),
        ]
        posterior = self.engine.update_posterior(self.neutral_prior, signals)
        assert posterior.p_bullish > 0.5


# ============================================================
# 5. BayesianBeliefEngine.infer (full pipeline)
# ============================================================


class TestInfer:
    def setup_method(self):
        self.engine = BayesianBeliefEngine()

    def test_bull_regime_strong_buy(self):
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.8},
        ]
        posterior = self.engine.infer(
            symbol="600519", signals=signals, sector="consumer_staples", regime="bull"
        )
        assert posterior.p_bullish > 0.6

    def test_bear_regime_sell_signal(self):
        signals = [
            {"source": "recommendation", "direction": "sell", "confidence": 0.8},
        ]
        posterior = self.engine.infer(
            symbol="000001", signals=signals, sector="bank", regime="bear"
        )
        assert posterior.p_bullish < 0.3

    def test_neutral_everything(self):
        signals = [
            {"source": "technical", "direction": "buy", "confidence": 0.4},
        ]
        posterior = self.engine.infer(
            symbol="000001", signals=signals, sector="default", regime="unknown"
        )
        # Neutral prior + weak neutral signal → near 0.5
        assert 0.4 < posterior.p_bullish < 0.6

    def test_no_signals_returns_prior_only(self):
        posterior = self.engine.infer(
            symbol="600519", signals=[], sector="consumer_staples", regime="bull"
        )
        # No signals → posterior == prior
        assert posterior.p_bullish == posterior.prior.p_bullish

    def test_multiple_strong_signals(self):
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.9},
            {"source": "capital_flow", "direction": "buy", "confidence": 0.85},
            {"source": "technical", "direction": "buy", "confidence": 0.8},
        ]
        posterior = self.engine.infer(
            symbol="600519", signals=signals, sector="consumer_staples", regime="bull"
        )
        assert posterior.p_bullish > 0.8  # very bullish

    def test_quant_p_up_in_full_pipeline(self):
        signals = [{"source": "recommendation", "direction": "buy", "confidence": 0.7}]
        post_without = self.engine.infer(
            symbol="600519", signals=signals, regime="unknown"
        )
        post_with = self.engine.infer(
            symbol="600519", signals=signals, regime="unknown", quant_p_up=0.7
        )
        assert post_with.p_bullish > post_without.p_bullish


# ============================================================
# 6. Signal mapping
# ============================================================


class TestMapSignalToEvidence:
    def test_dict_signal(self):
        signal = {"source": "recommendation", "direction": "buy", "confidence": 0.8}
        evidence = _map_signal_to_evidence(signal)
        assert evidence.source == "recommendation"
        assert evidence.direction == "buy"
        assert evidence.strength == 0.8
        assert evidence.metadata["bucket"] == "strong_buy"

    def test_dict_signal_with_symbol(self):
        signal = {
            "source": "technical",
            "direction": "sell",
            "confidence": 0.6,
            "symbol": "600519",
        }
        evidence = _map_signal_to_evidence(signal)
        assert evidence.symbol == "600519"
        assert evidence.source == "technical"
        assert evidence.direction == "sell"

    def test_object_signal(self):
        class MockSignal:
            source = "capital_flow"
            direction = "buy"
            confidence = 0.75
            symbol = "000001"

        evidence = _map_signal_to_evidence(MockSignal())
        assert evidence.source == "capital_flow"
        assert evidence.direction == "buy"
        assert evidence.strength == 0.75

    def test_object_signal_with_enum_direction(self):
        """Handles direction as an enum with .value attribute."""

        class Direction:
            value = "sell"

        class MockSignal:
            source = "technical"
            direction = Direction()
            confidence = 0.7

        evidence = _map_signal_to_evidence(MockSignal())
        assert evidence.direction == "sell"

    def test_source_mapping_aliases(self):
        """Source aliases should map to canonical table keys."""
        alias_tests = [
            ("rec", "recommendation"),
            ("signal", "technical"),
            ("intraday", "intraday_pattern"),
            ("mtf", "mtf_alignment"),
            ("multi_timeframe", "mtf_alignment"),
        ]
        for alias, expected in alias_tests:
            signal = {"source": alias, "direction": "buy", "confidence": 0.5}
            evidence = _map_signal_to_evidence(signal)
            assert evidence.source == expected, f"{alias} should map to {expected}"

    def test_unknown_source_passthrough(self):
        signal = {"source": "mystery_signal", "direction": "buy", "confidence": 0.5}
        evidence = _map_signal_to_evidence(signal)
        assert evidence.source == "mystery_signal"

    def test_defaults_for_missing_fields(self):
        evidence = _map_signal_to_evidence({})
        assert evidence.source == "unknown"
        assert evidence.direction == "buy"
        assert evidence.strength == 0.5


class TestConfidenceToBucket:
    # -- recommendation --
    def test_recommendation_strong_buy(self):
        assert _confidence_to_bucket("recommendation", "buy", 0.80) == "strong_buy"

    def test_recommendation_buy(self):
        assert _confidence_to_bucket("recommendation", "buy", 0.60) == "buy"

    def test_recommendation_watch(self):
        assert _confidence_to_bucket("recommendation", "buy", 0.40) == "watch"

    def test_recommendation_sell(self):
        assert _confidence_to_bucket("recommendation", "sell", 0.80) == "sell"

    # -- capital_flow --
    def test_capital_flow_large_inflow(self):
        assert _confidence_to_bucket("capital_flow", "buy", 0.80) == "large_inflow"

    def test_capital_flow_large_outflow(self):
        assert _confidence_to_bucket("capital_flow", "sell", 0.80) == "large_outflow"

    def test_capital_flow_moderate_inflow(self):
        assert _confidence_to_bucket("capital_flow", "buy", 0.60) == "moderate_inflow"

    def test_capital_flow_neutral(self):
        assert _confidence_to_bucket("capital_flow", "buy", 0.40) == "neutral"

    # -- technical --
    def test_technical_strong_bullish(self):
        assert _confidence_to_bucket("technical", "buy", 0.80) == "strong_bullish"

    def test_technical_strong_bearish(self):
        assert _confidence_to_bucket("technical", "sell", 0.80) == "strong_bearish"

    def test_technical_bullish(self):
        assert _confidence_to_bucket("technical", "buy", 0.55) == "bullish"

    def test_technical_neutral(self):
        assert _confidence_to_bucket("technical", "buy", 0.40) == "neutral"

    # -- stop_loss / thesis --
    def test_stop_loss_always_triggered(self):
        assert _confidence_to_bucket("stop_loss", "sell", 0.5) == "triggered"

    def test_thesis_invalidation(self):
        assert (
            _confidence_to_bucket("thesis_invalidation", "sell", 0.5) == "invalidated"
        )

    # -- black_swan --
    def test_black_swan_alert(self):
        assert _confidence_to_bucket("black_swan", "sell", 0.80) == "alert"

    def test_black_swan_elevated(self):
        assert _confidence_to_bucket("black_swan", "sell", 0.50) == "elevated"

    def test_black_swan_normal(self):
        assert _confidence_to_bucket("black_swan", "sell", 0.20) == "normal"

    # -- vpin --
    def test_vpin_extreme(self):
        assert _confidence_to_bucket("vpin", "sell", 0.85) == "extreme_toxicity"

    def test_vpin_high(self):
        assert _confidence_to_bucket("vpin", "sell", 0.65) == "high_toxicity"

    def test_vpin_normal(self):
        assert _confidence_to_bucket("vpin", "sell", 0.45) == "normal"

    def test_vpin_low(self):
        assert _confidence_to_bucket("vpin", "buy", 0.30) == "low_toxicity"

    # -- intraday_pattern --
    def test_intraday_bullish_strong(self):
        assert (
            _confidence_to_bucket("intraday_pattern", "buy", 0.70) == "bullish_strong"
        )

    def test_intraday_bearish(self):
        assert _confidence_to_bucket("intraday_pattern", "sell", 0.50) == "bearish"

    # -- global_intelligence --
    def test_global_strong_positive(self):
        assert (
            _confidence_to_bucket("global_intelligence", "buy", 0.80)
            == "strong_positive"
        )

    def test_global_negative(self):
        assert _confidence_to_bucket("global_intelligence", "sell", 0.60) == "negative"

    def test_global_neutral(self):
        assert _confidence_to_bucket("global_intelligence", "buy", 0.40) == "neutral"

    # -- reflexivity --
    def test_reflexivity_strengthening(self):
        assert _confidence_to_bucket("reflexivity", "buy", 0.70) == "strengthening"

    def test_reflexivity_breaking(self):
        assert _confidence_to_bucket("reflexivity", "sell", 0.70) == "breaking"

    def test_reflexivity_exhausting(self):
        assert _confidence_to_bucket("reflexivity", "buy", 0.50) == "exhausting"

    # -- mtf_alignment --
    def test_mtf_strong_aligned(self):
        assert _confidence_to_bucket("mtf_alignment", "buy", 0.80) == "strong_aligned"

    def test_mtf_strong_opposed(self):
        assert _confidence_to_bucket("mtf_alignment", "sell", 0.80) == "strong_opposed"

    def test_mtf_conflicting(self):
        assert _confidence_to_bucket("mtf_alignment", "buy", 0.40) == "conflicting"

    # -- fallback --
    def test_unknown_type_high_confidence(self):
        assert _confidence_to_bucket("unknown_type", "buy", 0.80) == "strong_bullish"

    def test_unknown_type_bearish(self):
        assert _confidence_to_bucket("unknown_type", "sell", 0.60) == "bearish"

    def test_unknown_type_neutral(self):
        assert _confidence_to_bucket("unknown_type", "buy", 0.30) == "neutral"

    # -- direction synonyms --
    def test_reduce_is_bearish(self):
        assert _confidence_to_bucket("recommendation", "reduce", 0.80) == "sell"

    def test_avoid_is_bearish(self):
        assert _confidence_to_bucket("recommendation", "avoid", 0.80) == "sell"


# ============================================================
# 7. Posterior helpers
# ============================================================


class TestPosteriorHelpers:
    def setup_method(self):
        self.prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)
        self.posterior = BayesianPosterior(
            p_bullish=0.72,
            p_bearish=0.28,
            prior=self.prior,
            evidence_count=2,
            log_odds=0.94,
            likelihood_contributions=[
                {
                    "source": "recommendation",
                    "direction": "buy",
                    "bucket": "strong_buy",
                    "p_e_bull": 0.72,
                    "p_e_bear": 0.18,
                    "llr": 1.39,
                    "lr": 4.0,
                },
            ],
        )

    def test_confidence_buy(self):
        conf = BayesianBeliefEngine.posterior_to_confidence(self.posterior, "buy")
        assert conf == pytest.approx(0.72)

    def test_confidence_add(self):
        conf = BayesianBeliefEngine.posterior_to_confidence(self.posterior, "add")
        assert conf == pytest.approx(0.72)

    def test_confidence_sell(self):
        conf = BayesianBeliefEngine.posterior_to_confidence(self.posterior, "sell")
        assert conf == pytest.approx(0.28)

    def test_confidence_reduce(self):
        conf = BayesianBeliefEngine.posterior_to_confidence(self.posterior, "reduce")
        assert conf == pytest.approx(0.28)

    def test_confidence_hold(self):
        conf = BayesianBeliefEngine.posterior_to_confidence(self.posterior, "hold")
        assert conf == pytest.approx(0.5)

    def test_kelly_win_rate_same_as_confidence(self):
        kelly = BayesianBeliefEngine.posterior_to_kelly_win_rate(self.posterior, "buy")
        conf = BayesianBeliefEngine.posterior_to_confidence(self.posterior, "buy")
        assert kelly == pytest.approx(conf)

    def test_kelly_sell(self):
        kelly = BayesianBeliefEngine.posterior_to_kelly_win_rate(self.posterior, "sell")
        assert kelly == pytest.approx(0.28)

    def test_format_posterior_summary_nonempty(self):
        summary = BayesianBeliefEngine.format_posterior_summary(self.posterior)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_format_posterior_summary_chinese(self):
        summary = BayesianBeliefEngine.format_posterior_summary(self.posterior)
        assert "贝叶斯" in summary
        assert "先验" in summary

    def test_format_posterior_summary_contains_evidence(self):
        summary = BayesianBeliefEngine.format_posterior_summary(self.posterior)
        assert "recommendation" in summary
        assert "LR=" in summary

    def test_format_posterior_no_evidence(self):
        posterior_no_evidence = BayesianPosterior(
            p_bullish=0.5,
            p_bearish=0.5,
            prior=self.prior,
            evidence_count=0,
            log_odds=0.0,
        )
        summary = BayesianBeliefEngine.format_posterior_summary(posterior_no_evidence)
        assert "贝叶斯" in summary
        assert "证据" not in summary  # no evidence section

    def test_format_posterior_with_prior_components(self):
        prior_with_components = BayesianPrior(
            p_bullish=0.55,
            p_bearish=0.45,
            components={"sector_base_rate": 0.52, "regime": 0.58, "quant_p_up": 0.6},
        )
        posterior = BayesianPosterior(
            p_bullish=0.65,
            p_bearish=0.35,
            prior=prior_with_components,
            evidence_count=1,
            log_odds=0.62,
            likelihood_contributions=[
                {
                    "source": "technical",
                    "direction": "buy",
                    "bucket": "bullish",
                    "p_e_bull": 0.58,
                    "p_e_bear": 0.33,
                    "llr": 0.56,
                    "lr": 1.76,
                },
            ],
        )
        summary = BayesianBeliefEngine.format_posterior_summary(posterior)
        assert "行业基础胜率" in summary
        assert "市场环境" in summary
        assert "量化因子" in summary


# ============================================================
# 8. Integration: Bayesian vs heuristic averaging
# ============================================================


class TestBayesianVsHeuristic:
    """Demonstrate that Bayesian combining differs from simple averaging."""

    def test_two_bullish_signals_bayesian_exceeds_average(self):
        """Two 0.6-confidence bullish signals: avg=0.6, Bayesian posterior > 0.6."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.6},
            {"source": "technical", "direction": "buy", "confidence": 0.6},
        ]
        posterior = engine.update_posterior(prior, signals)

        # Simple average would be 0.6
        simple_avg = 0.6
        # Bayesian combining with confirming evidence should exceed simple avg
        assert posterior.p_bullish > simple_avg

    def test_three_weak_bullish_compound_beyond_any_single(self):
        """Three weak bullish signals should combine stronger than any individual."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)

        single_signal = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.56}
        ]
        post_single = engine.update_posterior(prior, single_signal)

        triple_signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.56},
            {"source": "technical", "direction": "buy", "confidence": 0.56},
            {"source": "capital_flow", "direction": "buy", "confidence": 0.56},
        ]
        post_triple = engine.update_posterior(prior, triple_signals)

        assert post_triple.p_bullish > post_single.p_bullish

    def test_opposing_signals_converge_near_neutral(self):
        """Equally strong opposing signals should roughly cancel out."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.8},
            {"source": "recommendation", "direction": "sell", "confidence": 0.8},
        ]
        posterior = engine.update_posterior(prior, signals)
        # Should be roughly neutral
        assert 0.35 < posterior.p_bullish < 0.65

    def test_strong_signal_dominates_weak(self):
        """A strong bullish signal + weak bearish → net bullish."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)
        signals = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.9},
            {"source": "technical", "direction": "sell", "confidence": 0.5},
        ]
        posterior = engine.update_posterior(prior, signals)
        assert posterior.p_bullish > 0.5

    def test_evidence_order_independent(self):
        """Bayesian update should give same result regardless of signal order."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)
        signals_ab = [
            {"source": "recommendation", "direction": "buy", "confidence": 0.8},
            {"source": "technical", "direction": "sell", "confidence": 0.6},
        ]
        signals_ba = [
            {"source": "technical", "direction": "sell", "confidence": 0.6},
            {"source": "recommendation", "direction": "buy", "confidence": 0.8},
        ]
        post_ab = engine.update_posterior(prior, signals_ab)
        post_ba = engine.update_posterior(prior, signals_ba)
        assert post_ab.p_bullish == pytest.approx(post_ba.p_bullish, abs=1e-9)

    def test_prior_matters(self):
        """Same evidence, different priors → different posteriors."""
        engine = BayesianBeliefEngine()
        signals = [{"source": "recommendation", "direction": "buy", "confidence": 0.7}]

        bullish_prior = BayesianPrior(p_bullish=0.65, p_bearish=0.35)
        bearish_prior = BayesianPrior(p_bullish=0.35, p_bearish=0.65)

        post_bull = engine.update_posterior(bullish_prior, signals)
        post_bear = engine.update_posterior(bearish_prior, signals)

        assert post_bull.p_bullish > post_bear.p_bullish

    def test_log_odds_monotonicity(self):
        """More bullish evidence → monotonically increasing posterior."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)

        posteriors = []
        for n in range(1, 5):
            signals = [
                {"source": "recommendation", "direction": "buy", "confidence": 0.7}
            ] * n
            post = engine.update_posterior(prior, signals)
            posteriors.append(post.p_bullish)

        for i in range(len(posteriors) - 1):
            assert posteriors[i + 1] > posteriors[i], (
                f"Adding more bullish evidence should increase posterior: "
                f"{posteriors[i + 1]} <= {posteriors[i]}"
            )


# ============================================================
# 9. Leader detection likelihood
# ============================================================


class TestLeaderDetectionLikelihood:
    def test_leader_detection_table_exists(self):
        store = CalibrationStore()
        p = store.get_likelihood("leader_detection", "strong_leader", "bullish")
        assert p == pytest.approx(0.70, abs=0.01)

    def test_leader_detection_strong_lr(self):
        store = CalibrationStore()
        lr = store.get_likelihood_ratio("leader_detection", "strong_leader")
        assert lr == pytest.approx(3.5, abs=0.1)

    def test_leader_detection_weak_near_neutral(self):
        store = CalibrationStore()
        lr = store.get_likelihood_ratio("leader_detection", "weak_leader")
        assert 0.9 < lr < 1.2  # near-neutral

    def test_leader_source_mapping(self):
        signal = {"source": "leader_detection", "direction": "buy", "confidence": 0.85}
        evidence = _map_signal_to_evidence(signal)
        assert evidence.source == "leader_detection"

    def test_leader_bucket_strong(self):
        assert _confidence_to_bucket("leader_detection", "buy", 0.85) == "strong_leader"

    def test_leader_bucket_medium(self):
        assert _confidence_to_bucket("leader_detection", "buy", 0.70) == "medium_leader"

    def test_leader_bucket_weak(self):
        assert _confidence_to_bucket("leader_detection", "buy", 0.50) == "weak_leader"

    def test_leader_signal_bullish_shift(self):
        """A strong leader signal should shift posterior bullish."""
        engine = BayesianBeliefEngine()
        prior = BayesianPrior(p_bullish=0.5, p_bearish=0.5)
        signals = [
            {"source": "leader_detection", "direction": "buy", "confidence": 0.85}
        ]
        posterior = engine.update_posterior(prior, signals)
        assert posterior.p_bullish > 0.6


# ============================================================
# 10. CalibrationStore persistence round-trip
# ============================================================


class TestCalibrationStorePersistence:
    """Verify empirical tables survive save→load round-trip and affect lookups."""

    def test_save_and_load_round_trip(self, tmp_path):
        db_path = str(tmp_path / "calibration.db")

        # Store 1: compute empirical tables from outcome data
        store1 = CalibrationStore()
        outcomes = [
            {
                "source": "recommendation",
                "bucket": "strong_buy",
                "direction_correct": True,
                "created_at": "2026-03-20T10:00:00+08:00",
            },
        ] * 50 + [
            {
                "source": "recommendation",
                "bucket": "strong_buy",
                "direction_correct": False,
                "created_at": "2026-03-20T10:00:00+08:00",
            },
        ] * 10
        updated = store1.update_likelihood_tables(
            outcomes, db_path=db_path, min_samples=30
        )
        assert updated == 1

        # Store 2: fresh instance loads from DB
        store2 = CalibrationStore()
        loaded = store2.load_empirical_tables(db_path=db_path)
        assert loaded == 1

        # Loaded store should use empirical values, not expert defaults
        expert_p = 0.72  # default P(strong_buy|bull) for recommendation
        empirical_p = store2.get_likelihood("recommendation", "strong_buy", "bullish")
        assert empirical_p != pytest.approx(expert_p, abs=0.01), (
            "Loaded tables should differ from expert defaults"
        )

    def test_empty_db_loads_zero(self, tmp_path):
        db_path = str(tmp_path / "nonexistent.db")
        store = CalibrationStore()
        loaded = store.load_empirical_tables(db_path=db_path)
        assert loaded == 0

    def test_loaded_tables_change_likelihood_ratio(self, tmp_path):
        db_path = str(tmp_path / "calibration.db")

        # Expert default LR for recommendation/strong_buy = 4.0
        expert_store = CalibrationStore()
        expert_lr = expert_store.get_likelihood_ratio("recommendation", "strong_buy")

        # Create skewed outcome data: 90% correct → high empirical P(signal|bull)
        outcomes = [
            {
                "source": "recommendation",
                "bucket": "strong_buy",
                "direction_correct": True,
                "created_at": "2026-03-20T10:00:00+08:00",
            },
        ] * 90 + [
            {
                "source": "recommendation",
                "bucket": "strong_buy",
                "direction_correct": False,
                "created_at": "2026-03-20T10:00:00+08:00",
            },
        ] * 10
        store1 = CalibrationStore()
        store1.update_likelihood_tables(outcomes, db_path=db_path, min_samples=30)

        # Load into fresh store
        store2 = CalibrationStore()
        store2.load_empirical_tables(db_path=db_path)
        empirical_lr = store2.get_likelihood_ratio("recommendation", "strong_buy")

        assert empirical_lr != pytest.approx(expert_lr, abs=0.1), (
            "Empirical LR should differ from expert default"
        )


# ============================================================
# 11. Portfolio-aware prior adjustments (v50.0 §4.3)
# ============================================================


class TestPortfolioAwarePrior:
    """Portfolio context should bias the Bayesian prior toward diversification."""

    def setup_method(self):
        self.engine = BayesianBeliefEngine()

    def test_no_portfolio_context_unchanged(self):
        """Without portfolio params, prior is identical to the original."""
        prior_without = self.engine.compute_prior(
            sector="technology", regime="bull", quant_p_up=0.6
        )
        prior_with = self.engine.compute_prior(
            sector="technology",
            regime="bull",
            quant_p_up=0.6,
            portfolio_sector_weight=None,
            portfolio_position_exists=False,
            portfolio_correlation=None,
        )
        assert prior_without.p_bullish == pytest.approx(prior_with.p_bullish)
        assert "sector_concentration" not in prior_with.components
        assert "position_overlap" not in prior_with.components
        assert "correlation_penalty" not in prior_with.components

    def test_high_sector_weight_reduces_prior(self):
        """35% sector allocation should reduce prior vs no allocation."""
        prior_no_alloc = self.engine.compute_prior(
            sector="technology", regime="unknown"
        )
        prior_heavy = self.engine.compute_prior(
            sector="technology", regime="unknown", portfolio_sector_weight=0.35
        )
        assert prior_heavy.p_bullish < prior_no_alloc.p_bullish
        assert "sector_concentration" in prior_heavy.components

    def test_sector_weight_below_threshold_no_penalty(self):
        """10% sector allocation (below 15% threshold) should not penalize."""
        prior_baseline = self.engine.compute_prior(
            sector="technology", regime="unknown"
        )
        prior_light = self.engine.compute_prior(
            sector="technology", regime="unknown", portfolio_sector_weight=0.10
        )
        assert prior_light.p_bullish == pytest.approx(prior_baseline.p_bullish)
        assert "sector_concentration" not in prior_light.components

    def test_sector_weight_at_boundary(self):
        """Exactly 15% should NOT trigger penalty (>0.15 required)."""
        prior_baseline = self.engine.compute_prior(
            sector="technology", regime="unknown"
        )
        prior_boundary = self.engine.compute_prior(
            sector="technology", regime="unknown", portfolio_sector_weight=0.15
        )
        assert prior_boundary.p_bullish == pytest.approx(prior_baseline.p_bullish)

    def test_position_exists_reduces_prior(self):
        """Already holding a stock should slightly reduce prior."""
        prior_no_pos = self.engine.compute_prior(sector="technology", regime="unknown")
        prior_with_pos = self.engine.compute_prior(
            sector="technology", regime="unknown", portfolio_position_exists=True
        )
        assert prior_with_pos.p_bullish < prior_no_pos.p_bullish
        assert "position_overlap" in prior_with_pos.components
        assert prior_with_pos.components["position_overlap"] == 0.45

    def test_high_correlation_reduces_prior(self):
        """0.7 correlation to existing holdings should reduce prior."""
        prior_no_corr = self.engine.compute_prior(sector="technology", regime="unknown")
        prior_high_corr = self.engine.compute_prior(
            sector="technology", regime="unknown", portfolio_correlation=0.7
        )
        assert prior_high_corr.p_bullish < prior_no_corr.p_bullish
        assert "correlation_penalty" in prior_high_corr.components

    def test_correlation_below_threshold_no_penalty(self):
        """0.3 correlation (below 0.5 threshold) should not penalize."""
        prior_baseline = self.engine.compute_prior(
            sector="technology", regime="unknown"
        )
        prior_low_corr = self.engine.compute_prior(
            sector="technology", regime="unknown", portfolio_correlation=0.3
        )
        assert prior_low_corr.p_bullish == pytest.approx(prior_baseline.p_bullish)
        assert "correlation_penalty" not in prior_low_corr.components

    def test_all_portfolio_penalties_compound(self):
        """All three penalties together should reduce prior more than any single one."""
        prior_single = self.engine.compute_prior(
            sector="technology",
            regime="unknown",
            portfolio_sector_weight=0.30,
        )
        prior_all = self.engine.compute_prior(
            sector="technology",
            regime="unknown",
            portfolio_sector_weight=0.30,
            portfolio_position_exists=True,
            portfolio_correlation=0.7,
        )
        assert prior_all.p_bullish < prior_single.p_bullish

    def test_prior_still_clamped_with_portfolio_penalties(self):
        """Even with all penalties in bear regime, prior >= 0.25."""
        prior = self.engine.compute_prior(
            sector="real_estate",
            regime="bear",
            quant_p_up=0.1,
            portfolio_sector_weight=0.40,
            portfolio_position_exists=True,
            portfolio_correlation=0.9,
        )
        assert prior.p_bullish >= 0.25

    def test_infer_forwards_portfolio_params(self):
        """infer() should forward portfolio params to compute_prior()."""
        signals = [{"source": "recommendation", "direction": "buy", "confidence": 0.7}]
        post_without = self.engine.infer(
            symbol="600519", signals=signals, regime="unknown"
        )
        post_with = self.engine.infer(
            symbol="600519",
            signals=signals,
            regime="unknown",
            portfolio_sector_weight=0.35,
            portfolio_position_exists=True,
        )
        # Portfolio penalties should reduce the posterior
        assert post_with.p_bullish < post_without.p_bullish
        assert "sector_concentration" in post_with.prior.components
        assert "position_overlap" in post_with.prior.components
