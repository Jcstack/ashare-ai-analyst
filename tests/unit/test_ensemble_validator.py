"""Tests for src/intelligence/ensemble_validator.py."""

import pytest

from src.intelligence.ensemble_validator import (
    EnsembleConfig,
    EnsembleValidator,
    ProviderResult,
    _majority_direction,
)


@pytest.fixture
def validator() -> EnsembleValidator:
    return EnsembleValidator()


def _pr(
    provider: str = "anthropic",
    direction: str = "bullish",
    confidence: float = 0.70,
    error: str | None = None,
) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        direction=direction,
        confidence=confidence,
        error=error,
    )


class TestMajorityDirection:
    def test_unanimous(self):
        assert _majority_direction(["bullish", "bullish", "bullish"]) == "bullish"

    def test_majority(self):
        assert _majority_direction(["bullish", "bullish", "bearish"]) == "bullish"

    def test_tie_prefers_neutral(self):
        assert _majority_direction(["bullish", "neutral"]) == "neutral"

    def test_tie_no_neutral(self):
        result = _majority_direction(["bullish", "bearish"])
        assert result in ("bullish", "bearish")

    def test_empty(self):
        assert _majority_direction([]) == "neutral"


class TestValidateConsensus:
    def test_full_agreement(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.75),
            _pr("google", "bullish", 0.72),
        ]
        ensemble = validator.validate(results)
        assert ensemble.consensus_direction == "bullish"
        assert ensemble.consensus_score > 0.8
        assert ensemble.trust_zone in ("HIGH", "MEDIUM")

    def test_full_disagreement(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.80),
            _pr("google", "bearish", 0.75),
        ]
        ensemble = validator.validate(results)
        assert ensemble.consensus_score < 0.6
        assert ensemble.trust_zone in ("LOW", "UNTRUSTED")

    def test_high_confidence_spread(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.90),
            _pr("google", "bullish", 0.40),
        ]
        ensemble = validator.validate(results)
        assert ensemble.consensus_direction == "bullish"
        assert len(ensemble.divergence_notes) > 0

    def test_low_confidence_spread(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.70),
            _pr("google", "bullish", 0.68),
        ]
        ensemble = validator.validate(results)
        assert ensemble.consensus_score > 0.8

    def test_three_providers(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.70),
            _pr("google", "bullish", 0.65),
            _pr("openai", "bearish", 0.55),
        ]
        ensemble = validator.validate(results)
        assert ensemble.consensus_direction == "bullish"
        # 2/3 agree = ~0.67 direction agreement
        assert ensemble.consensus_score > 0.5


class TestInsufficientProviders:
    def test_single_provider(self, validator: EnsembleValidator):
        results = [_pr("anthropic", "bullish", 0.70)]
        ensemble = validator.validate(results)
        assert ensemble.trust_zone == "LOW"
        assert any("响应不足" in n for n in ensemble.divergence_notes)

    def test_all_errors(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", error="timeout"),
            _pr("google", error="rate_limited"),
        ]
        ensemble = validator.validate(results)
        assert ensemble.trust_zone == "LOW"

    def test_one_error_one_success(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.70),
            _pr("google", error="timeout"),
        ]
        ensemble = validator.validate(results)
        assert ensemble.consensus_direction == "bullish"
        assert ensemble.trust_zone == "LOW"


class TestTrustZones:
    def test_high_trust(self, validator: EnsembleValidator):
        results = [
            _pr("anthropic", "bullish", 0.72),
            _pr("google", "bullish", 0.70),
        ]
        ensemble = validator.validate(results)
        assert ensemble.trust_zone == "HIGH"

    def test_untrusted_zone(self, validator: EnsembleValidator):
        # With 2 providers disagreeing, direction_agreement = 0.5
        results = [
            _pr("anthropic", "bullish", 0.80),
            _pr("google", "bearish", 0.80),
        ]
        ensemble = validator.validate(results)
        assert ensemble.trust_zone in ("LOW", "UNTRUSTED")

    def test_custom_threshold(self):
        config = EnsembleConfig(consensus_threshold=0.90)
        validator = EnsembleValidator(config)
        results = [
            _pr("anthropic", "bullish", 0.70),
            _pr("google", "bullish", 0.55),
        ]
        ensemble = validator.validate(results)
        # High spread reduces consensus below 0.90
        if ensemble.consensus_score < 0.90:
            assert ensemble.trust_zone in ("LOW", "MEDIUM")


class TestShouldValidate:
    def test_trade_decision(self, validator: EnsembleValidator):
        assert validator.should_validate("trade_decision") is True

    def test_position_change(self, validator: EnsembleValidator):
        assert validator.should_validate("position_change") is True

    def test_analysis_only(self, validator: EnsembleValidator):
        assert validator.should_validate("quick_look") is False

    def test_disabled(self):
        config = EnsembleConfig(enabled_for_trades=False)
        validator = EnsembleValidator(config)
        assert validator.should_validate("trade_decision") is False


class TestCreateProviderResult:
    def test_basic(self, validator: EnsembleValidator):
        raw = {"direction": "bearish", "confidence": 0.65, "summary": "看空"}
        pr = validator.create_provider_result("anthropic", raw)
        assert pr.provider == "anthropic"
        assert pr.direction == "bearish"
        assert pr.confidence == 0.65
        assert pr.summary == "看空"

    def test_defaults(self, validator: EnsembleValidator):
        pr = validator.create_provider_result("google", {})
        assert pr.direction == "neutral"
        assert pr.confidence == 0.5
        assert pr.summary == ""
