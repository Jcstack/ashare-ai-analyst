"""Tests for the v14.0 ValidationFramework and V01-V07 rules.

Validates that:
- Each rule works independently
- The framework orchestrates rules correctly
- Auto-fixes produce correct results
- Edge cases are handled
"""

import pytest

from src.web.services.validation_framework import (
    V01ConfidenceNormalization,
    V02LowConfidenceWatch,
    V03MediumConfidenceRestriction,
    V04HighRiskNoAggressive,
    V05ActionValidation,
    V06JSONRepair,
    V07DataReferences,
    V08NumericalCrossValidation,
    V09TrustZoneEnforcement,
    ValidationFramework,
    ValidationReport,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# V01: Confidence normalization
# ---------------------------------------------------------------------------


class TestV01ConfidenceNormalization:
    def test_normalizes_float_in_range(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": 0.75}
        result = rule.validate(data, {"data_quality_score": 100})
        assert result.passed
        assert result.rule_id == "V01"

    def test_normalizes_100x_value(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": 72.5}
        rule.validate(data, {"data_quality_score": 100})
        assert data["confidence"] == pytest.approx(0.725, abs=0.01)

    def test_clamps_negative(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": -0.5}
        rule.validate(data, {"data_quality_score": 100})
        assert data["confidence"] == 0.0

    def test_clamps_above_one(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": 1.5}
        rule.validate(data, {"data_quality_score": 100})
        # 1.5 > 1.0 → divided by 100 → 0.015
        assert data["confidence"] == pytest.approx(0.015, abs=0.001)

    def test_handles_dict_confidence(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": {"score": 0.8, "basis": ["tech"]}}
        rule.validate(data, {"data_quality_score": 100})
        assert data["confidence"]["score"] == pytest.approx(0.8, abs=0.01)

    def test_invalid_type_defaults_to_half(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": "invalid"}
        rule.validate(data, {"data_quality_score": 100})
        assert data["confidence"] == 0.5

    def test_data_quality_clamp_low(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": 0.9}
        rule.validate(data, {"data_quality_score": 30})
        # dq < 40 → clamped to 0.3
        assert data["confidence"] == pytest.approx(0.3, abs=0.01)

    def test_data_quality_clamp_medium(self):
        rule = V01ConfidenceNormalization()
        data = {"confidence": 0.9}
        rule.validate(data, {"data_quality_score": 50})
        # dq 40-60 → clamped to 0.5
        assert data["confidence"] == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# V02: Low confidence → watch
# ---------------------------------------------------------------------------


class TestV02LowConfidenceWatch:
    def test_forces_watch_when_low(self):
        rule = V02LowConfidenceWatch()
        data = {"confidence": 0.1, "action": "buy"}
        result = rule.validate(data, {})
        assert result.passed
        assert result.auto_fixed
        assert data["action"] == "watch"

    def test_passes_when_confidence_ok(self):
        rule = V02LowConfidenceWatch()
        data = {"confidence": 0.5, "action": "buy"}
        result = rule.validate(data, {})
        assert result.passed
        assert not result.auto_fixed

    def test_passes_when_already_watch(self):
        rule = V02LowConfidenceWatch()
        data = {"confidence": 0.1, "action": "watch"}
        result = rule.validate(data, {})
        assert result.passed

    def test_handles_dict_confidence(self):
        rule = V02LowConfidenceWatch()
        data = {"confidence": {"score": 0.15}, "action": "buy"}
        result = rule.validate(data, {})
        assert result.auto_fixed
        assert data["action"] == "watch"


# ---------------------------------------------------------------------------
# V03: Medium confidence restriction
# ---------------------------------------------------------------------------


class TestV03MediumConfidenceRestriction:
    def test_restricts_buy_to_watch(self):
        rule = V03MediumConfidenceRestriction()
        data = {"confidence": 0.4, "action": "buy"}
        result = rule.validate(data, {})
        assert result.auto_fixed
        assert data["action"] == "watch"

    def test_restricts_add_to_hold(self):
        rule = V03MediumConfidenceRestriction()
        data = {"confidence": 0.35, "action": "add"}
        result = rule.validate(data, {})
        assert result.auto_fixed
        assert data["action"] == "hold"

    def test_allows_hold_at_medium(self):
        rule = V03MediumConfidenceRestriction()
        data = {"confidence": 0.4, "action": "hold"}
        result = rule.validate(data, {})
        assert result.passed

    def test_no_restriction_above_threshold(self):
        rule = V03MediumConfidenceRestriction()
        data = {"confidence": 0.7, "action": "buy"}
        result = rule.validate(data, {})
        assert result.passed
        assert data["action"] == "buy"


# ---------------------------------------------------------------------------
# V04: High risk → no buy/add
# ---------------------------------------------------------------------------


class TestV04HighRiskNoAggressive:
    def test_blocks_buy_on_high_risk(self):
        rule = V04HighRiskNoAggressive()
        data = {"risk_level": "high", "action": "buy"}
        result = rule.validate(data, {"symbol": "600519"})
        assert result.auto_fixed
        assert data["action"] == "watch"

    def test_blocks_add_on_high_risk(self):
        rule = V04HighRiskNoAggressive()
        data = {"risk_level": "high", "action": "add"}
        result = rule.validate(data, {"symbol": "600519"})
        assert result.auto_fixed
        assert data["action"] == "watch"

    def test_allows_sell_on_high_risk(self):
        rule = V04HighRiskNoAggressive()
        data = {"risk_level": "high", "action": "sell"}
        result = rule.validate(data, {})
        assert result.passed
        assert data["action"] == "sell"

    def test_allows_buy_on_low_risk(self):
        rule = V04HighRiskNoAggressive()
        data = {"risk_level": "low", "action": "buy"}
        result = rule.validate(data, {})
        assert result.passed
        assert data["action"] == "buy"


# ---------------------------------------------------------------------------
# V05: Action validation
# ---------------------------------------------------------------------------


class TestV05ActionValidation:
    def test_valid_action_passes(self):
        rule = V05ActionValidation()
        data = {"action": "buy"}
        result = rule.validate(data, {})
        assert result.passed
        assert data["action"] == "buy"

    def test_maps_chinese_action(self):
        rule = V05ActionValidation()
        data = {"action": "买入"}
        result = rule.validate(data, {})
        assert result.passed
        assert data["action"] == "buy"

    def test_maps_chinese_hold(self):
        rule = V05ActionValidation()
        data = {"action": "持有"}
        rule.validate(data, {})
        assert data["action"] == "hold"

    def test_invalid_action_defaults_to_watch(self):
        rule = V05ActionValidation()
        data = {"action": "yolo"}
        result = rule.validate(data, {})
        assert result.auto_fixed
        assert data["action"] == "watch"

    def test_all_valid_actions(self):
        rule = V05ActionValidation()
        for action in ("buy", "add", "hold", "reduce", "sell", "watch"):
            data = {"action": action}
            result = rule.validate(data, {})
            assert result.passed
            assert data["action"] == action


# ---------------------------------------------------------------------------
# V06: JSON repair
# ---------------------------------------------------------------------------


class TestV06JSONRepair:
    def test_non_empty_data_passes(self):
        rule = V06JSONRepair()
        result = rule.validate({"action": "buy"}, {})
        assert result.passed

    def test_empty_data_fails(self):
        rule = V06JSONRepair()
        result = rule.validate({}, {})
        assert not result.passed


# ---------------------------------------------------------------------------
# V07: Data references
# ---------------------------------------------------------------------------


class TestV07DataReferences:
    def test_with_references_passes(self):
        rule = V07DataReferences()
        data = {"data_references": [{"field": "MACD", "value": "金叉"}]}
        result = rule.validate(data, {"symbol": "600519"})
        assert result.passed

    def test_empty_references_fails(self):
        rule = V07DataReferences()
        data = {"data_references": []}
        result = rule.validate(data, {"symbol": "600519"})
        assert not result.passed

    def test_missing_references_fails(self):
        rule = V07DataReferences()
        data = {}
        result = rule.validate(data, {"symbol": "600519"})
        assert not result.passed

    def test_non_list_references_fails(self):
        rule = V07DataReferences()
        data = {"data_references": "none"}
        result = rule.validate(data, {"symbol": "600519"})
        assert not result.passed


# ---------------------------------------------------------------------------
# ValidationFramework integration
# ---------------------------------------------------------------------------


class TestValidationFramework:
    def test_default_rules_count(self):
        fw = ValidationFramework()
        assert len(fw.rules) == 12

    def test_all_pass_clean_data(self):
        fw = ValidationFramework()
        data = {
            "action": "buy",
            "confidence": 0.8,
            "risk_level": "low",
            "data_references": [{"field": "MA5", "value": "上穿MA20"}],
        }
        report = fw.validate(data, {"symbol": "600519", "data_quality_score": 100})
        assert report.all_passed
        assert report.pass_rate == 1.0
        assert len(report.rules_passed) == 12

    def test_high_risk_buy_autofix(self):
        fw = ValidationFramework()
        data = {
            "action": "buy",
            "confidence": 0.8,
            "risk_level": "high",
            "data_references": [{"field": "RSI", "value": "90"}],
        }
        report = fw.validate(data, {"symbol": "600519", "data_quality_score": 100})
        assert data["action"] == "watch"
        assert "V04" in report.rules_passed

    def test_low_confidence_cascade(self):
        """V01 normalizes, V02 forces watch, V03 skips, V04 doesn't trigger."""
        fw = ValidationFramework()
        data = {
            "action": "buy",
            "confidence": 0.15,
            "risk_level": "low",
            "data_references": [{"field": "test", "value": "1"}],
        }
        fw.validate(data, {"symbol": "600519", "data_quality_score": 100})
        assert data["action"] == "watch"

    def test_add_custom_rule(self):
        fw = ValidationFramework()
        initial_count = len(fw.rules)

        class CustomRule(V06JSONRepair):
            rule_id = "CUSTOM01"
            description = "Custom test rule"

        fw.add_rule(CustomRule())
        assert len(fw.rules) == initial_count + 1

    def test_report_properties(self):
        report = ValidationReport(
            results=[
                ValidationResult(rule_id="A", passed=True),
                ValidationResult(rule_id="B", passed=False),
                ValidationResult(rule_id="C", passed=True),
            ]
        )
        assert not report.all_passed
        assert report.pass_rate == pytest.approx(2 / 3, abs=0.01)
        assert report.rules_passed == ["A", "C"]
        assert report.rules_failed == ["B"]

    def test_empty_report(self):
        report = ValidationReport()
        assert report.all_passed
        assert report.pass_rate == 1.0
        assert report.rules_passed == []
        assert report.rules_failed == []

    def test_rule_exception_handled(self):
        """Rules that raise exceptions should not crash the framework."""

        class BrokenRule(V06JSONRepair):
            rule_id = "BROKEN"

            def validate(self, data, context):
                raise RuntimeError("kaboom")

        fw = ValidationFramework(rules=[BrokenRule()])
        report = fw.validate({"action": "buy"}, {})
        assert len(report.results) == 1
        assert not report.results[0].passed
        assert "kaboom" in report.results[0].message

    def test_chinese_action_with_all_rules(self):
        """Chinese action mapped then validated through full pipeline."""
        fw = ValidationFramework()
        data = {
            "action": "加仓",
            "confidence": 0.9,
            "risk_level": "low",
            "data_references": [{"field": "概念板块", "value": "AI概念+5.2%"}],
        }
        report = fw.validate(data, {"symbol": "300750", "data_quality_score": 90})
        assert data["action"] == "add"
        assert report.all_passed


# ---------------------------------------------------------------------------
# V08: Numerical cross-validation
# ---------------------------------------------------------------------------


class TestV08NumericalCrossValidation:
    def test_no_reference_data_passes(self):
        rule = V08NumericalCrossValidation()
        data = {"reasoning": ["price is 25.5"]}
        result = rule.validate(data, {})
        assert result.passed

    def test_matched_number_passes(self):
        rule = V08NumericalCrossValidation()
        data = {"reasoning": ["price is 25.50"]}
        result = rule.validate(data, {"quote": {"price": 25.50}})
        assert result.passed

    def test_unmatched_number_fails(self):
        rule = V08NumericalCrossValidation()
        data = {"reasoning": ["price is 999.99"]}
        result = rule.validate(data, {"quote": {"price": 25.50}})
        assert not result.passed
        assert "data_gaps" in data
        assert any("999.99" in gap for gap in data["data_gaps"])

    def test_tolerant_match(self):
        """1% tolerance for rounding."""
        rule = V08NumericalCrossValidation()
        data = {"reasoning": ["price is 25.48"]}
        # 25.48 vs 25.50 = 0.08% difference, within 1% tolerance
        result = rule.validate(data, {"quote": {"price": 25.50}})
        assert result.passed

    def test_small_numbers_ignored(self):
        """Numbers <= 1.0 are not cross-validated."""
        rule = V08NumericalCrossValidation()
        data = {"reasoning": ["confidence is 0.85, score is 0.9"]}
        result = rule.validate(data, {"quote": {"price": 25.50}})
        assert result.passed

    def test_nested_reference_data(self):
        rule = V08NumericalCrossValidation()
        data = {"reasoning": ["MACD is 3.45"]}
        result = rule.validate(
            data,
            {"indicators": {"macd": {"value": 3.45, "signal": 2.10}}},
        )
        assert result.passed

    def test_string_text_fields(self):
        rule = V08NumericalCrossValidation()
        data = {"analysis": "Stock at 150.25 with volume 1000000"}
        result = rule.validate(data, {"quote": {"price": 150.25, "volume": 1000000}})
        assert result.passed

    def test_caps_unmatched_at_five(self):
        """At most 5 unverified numbers added to data_gaps."""
        rule = V08NumericalCrossValidation()
        data = {
            "reasoning": ["111.1 222.2 333.3 444.4 555.5 666.6 777.7"],
        }
        result = rule.validate(data, {"quote": {"price": 10.0}})
        assert not result.passed
        assert len(data["data_gaps"]) <= 5


# ---------------------------------------------------------------------------
# V09: Trust zone enforcement
# ---------------------------------------------------------------------------


class TestV09TrustZoneEnforcement:
    def test_high_zone_passes(self):
        rule = V09TrustZoneEnforcement()
        data = {"confidence": 0.9, "action": "buy"}
        result = rule.validate(data, {"data_quality_score": 100})
        assert result.passed
        assert data["trust_zone"] == "HIGH"
        assert data["action"] == "buy"  # not modified

    def test_medium_zone_passes(self):
        rule = V09TrustZoneEnforcement()
        data = {"confidence": 0.5, "action": "hold"}
        # composite = 0.4*0.5 + 0.3*0.6 + 0.3*0.8 = 0.20 + 0.18 + 0.24 = 0.62 → MEDIUM
        result = rule.validate(
            data, {"data_quality_score": 60, "validation_pass_rate": 0.8}
        )
        assert result.passed
        assert data["trust_zone"] == "MEDIUM"

    def test_low_zone_adds_confirmation(self):
        rule = V09TrustZoneEnforcement()
        data = {"confidence": 0.3, "action": "hold"}
        result = rule.validate(
            data, {"data_quality_score": 50, "validation_pass_rate": 0.5}
        )
        assert result.passed
        assert result.auto_fixed
        assert data["trust_zone"] == "LOW"
        assert data["require_user_confirmation"] is True

    def test_untrusted_strips_trade(self):
        rule = V09TrustZoneEnforcement()
        data = {"confidence": 0.1, "action": "buy"}
        result = rule.validate(
            data, {"data_quality_score": 10, "validation_pass_rate": 0.1}
        )
        assert result.passed
        assert result.auto_fixed
        assert data["trust_zone"] == "UNTRUSTED"
        assert data["action"] == "watch"

    def test_untrusted_no_trade_no_fix(self):
        """UNTRUSTED zone with action=watch doesn't need auto-fix."""
        rule = V09TrustZoneEnforcement()
        data = {"confidence": 0.05, "action": "watch"}
        result = rule.validate(
            data, {"data_quality_score": 5, "validation_pass_rate": 0.0}
        )
        assert result.passed
        assert not result.auto_fixed
        assert data["trust_zone"] == "UNTRUSTED"

    def test_default_validation_pass_rate(self):
        """Missing validation_pass_rate defaults to 1.0."""
        rule = V09TrustZoneEnforcement()
        data = {"confidence": 0.9, "action": "buy"}
        result = rule.validate(data, {"data_quality_score": 100})
        assert result.passed
        assert data["trust_zone"] == "HIGH"
