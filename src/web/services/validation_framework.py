"""Extensible validation framework for AI analysis outputs.

Migrates the existing V01-V07 validation rules from hardcoded logic in
``realtime_analyzer._parse_unified_result()`` into a pluggable rule
system. Each rule is a self-contained class with ``validate()`` and
``fix()`` methods.

Part of v14.0 Institutional Contracts layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("web.validation_framework")


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Outcome of applying a single validation rule.

    Attributes:
        rule_id: Unique rule identifier (e.g. "V01", "V04").
        passed: Whether the data passed the rule.
        message: Human-readable description of the result.
        auto_fixed: Whether the framework applied an automatic fix.
        fix_description: Description of the auto-fix applied (if any).
    """

    rule_id: str
    passed: bool
    message: str = ""
    auto_fixed: bool = False
    fix_description: str = ""


@dataclass
class ValidationReport:
    """Aggregated result of running all validation rules.

    Attributes:
        results: Individual rule results.
        all_passed: True if every rule passed (possibly after auto-fix).
        pass_rate: Fraction of rules that passed (0.0-1.0).
        rules_passed: List of rule IDs that passed.
        rules_failed: List of rule IDs that failed.
    """

    results: list[ValidationResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 1.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def rules_passed(self) -> list[str]:
        return [r.rule_id for r in self.results if r.passed]

    @property
    def rules_failed(self) -> list[str]:
        return [r.rule_id for r in self.results if not r.passed]


class ValidationRule(ABC):
    """Abstract base class for a validation rule.

    Subclasses must implement ``validate`` which inspects the data dict
    and returns a ValidationResult.  Rules may also mutate the data dict
    in-place to apply auto-fixes.
    """

    rule_id: str = ""
    description: str = ""

    @abstractmethod
    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        """Validate and optionally fix the data dict.

        Args:
            data: The analysis output dict (mutable).
            context: Additional context (symbol, data_quality_score, etc.).

        Returns:
            ValidationResult indicating pass/fail and any fix applied.
        """
        ...


# ---------------------------------------------------------------------------
# V01-V07 rule implementations
# ---------------------------------------------------------------------------


class V01ConfidenceNormalization(ValidationRule):
    """V01: Normalize confidence to float in [0, 1]."""

    rule_id = "V01"
    description = "Confidence must be a float in [0.0, 1.0]"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        raw_conf = data.get("confidence", 0.5)
        if isinstance(raw_conf, dict):
            conf_score = raw_conf.get("score", 0.5)
        else:
            conf_score = raw_conf

        try:
            conf_score = float(conf_score)
            if conf_score > 1.0:
                conf_score = conf_score / 100.0
            conf_score = max(0.0, min(1.0, conf_score))
        except (TypeError, ValueError):
            conf_score = 0.5

        # Apply data quality clamping (FR-PR006)
        dq = context.get("data_quality_score", 100)
        conf_score = _clamp_confidence(conf_score, dq)

        # Write back normalized value
        if isinstance(data.get("confidence"), dict):
            data["confidence"]["score"] = conf_score
        else:
            data["confidence"] = conf_score

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message=f"Confidence normalized to {conf_score:.3f}",
            auto_fixed=True,
        )


class V02LowConfidenceWatch(ValidationRule):
    """V02: Confidence < 0.3 forces action = 'watch'."""

    rule_id = "V02"
    description = "Confidence < 0.3 must force action to watch"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        conf = _extract_confidence(data)
        action = str(data.get("action", "watch")).lower()

        if conf < 0.3 and action != "watch":
            data["action"] = "watch"
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Low confidence ({conf:.2f}) forced action to watch",
                auto_fixed=True,
                fix_description=f"action {action} -> watch (confidence {conf:.2f} < 0.3)",
            )

        passed = conf >= 0.3 or action == "watch"
        return ValidationResult(
            rule_id=self.rule_id,
            passed=passed,
            message="Low confidence constraint satisfied"
            if passed
            else "Constraint violated",
        )


class V03MediumConfidenceRestriction(ValidationRule):
    """V03: Confidence < 0.5 restricts aggressive actions."""

    rule_id = "V03"
    description = "Confidence 0.3-0.5 restricts buy/sell/add/reduce"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        conf = _extract_confidence(data)
        action = str(data.get("action", "watch")).lower()

        if 0.3 <= conf < 0.5 and action in ("buy", "sell", "add", "reduce"):
            new_action = "hold" if action in ("add", "hold") else "watch"
            data["action"] = new_action
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Medium-low confidence ({conf:.2f}) restricted action",
                auto_fixed=True,
                fix_description=f"action {action} -> {new_action} (confidence {conf:.2f} < 0.5)",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message="Medium confidence constraint satisfied",
        )


class V04HighRiskNoAggressive(ValidationRule):
    """V04 (FR-PR007): High risk level prevents buy/add actions."""

    rule_id = "V04"
    description = "High risk level cannot have buy or add action"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        risk_level = str(data.get("risk_level", "medium")).strip().lower()
        action = str(data.get("action", "watch")).strip().lower()

        if risk_level == "high" and action in ("buy", "add"):
            data["action"] = "watch"
            symbol = context.get("symbol", "?")
            logger.info(
                "V04: high risk override action %s -> watch for %s", action, symbol
            )
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"High risk prevented {action} action",
                auto_fixed=True,
                fix_description=f"action {action} -> watch (risk_level=high)",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message="Risk-action constraint satisfied",
        )


class V05ActionValidation(ValidationRule):
    """V05: Action must be one of the valid action set."""

    rule_id = "V05"
    description = "Action must be in {buy, add, hold, reduce, sell, watch}"

    VALID_ACTIONS = {"buy", "add", "hold", "reduce", "sell", "watch"}

    ACTION_MAP = {
        "买入": "buy",
        "建仓": "buy",
        "加仓": "add",
        "增持": "add",
        "持有": "hold",
        "继续持有": "hold",
        "减仓": "reduce",
        "减持": "reduce",
        "卖出": "sell",
        "清仓": "sell",
        "观望": "watch",
        "等待": "watch",
    }

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        raw_action = str(data.get("action", "watch")).strip().lower()
        action = self.ACTION_MAP.get(raw_action, raw_action)

        if action not in self.VALID_ACTIONS:
            data["action"] = "watch"
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Invalid action '{raw_action}' normalized to watch",
                auto_fixed=True,
                fix_description=f"action '{raw_action}' -> watch",
            )

        if action != raw_action:
            data["action"] = action
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Action mapped: {raw_action} -> {action}",
                auto_fixed=True,
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message=f"Action '{action}' is valid",
        )


class V06JSONRepair(ValidationRule):
    """V06: Attempt multi-level JSON repair for malformed LLM output.

    This rule operates on the raw text and is handled before other rules.
    In the framework context, it validates that the data dict is non-empty.
    """

    rule_id = "V06"
    description = "Analysis output must parse as valid JSON"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        if not data:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=False,
                message="Failed to parse analysis output as JSON",
            )
        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message="JSON parsed successfully",
        )


class V07DataReferences(ValidationRule):
    """V07 (FR-PR005): Analysis must include data references."""

    rule_id = "V07"
    description = "Analysis must include at least one data reference"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        data_refs = data.get("data_references", [])
        has_refs = isinstance(data_refs, list) and len(data_refs) > 0

        if not has_refs:
            symbol = context.get("symbol", "?")
            logger.warning("V07: data_references is empty for %s", symbol)
            return ValidationResult(
                rule_id=self.rule_id,
                passed=False,
                message="No data references in analysis output",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message=f"Found {len(data_refs)} data reference(s)",
        )


class V08NumericalCrossValidation(ValidationRule):
    """V08: Cross-validate numerical values in LLM output against input data.

    Extracts prices, percentages, and volumes from the analysis text or
    structured output and checks them against the context data (quotes,
    indicators).  Unmatched fabricated values are flagged in ``data_gaps``.
    """

    rule_id = "V08"
    description = "Numerical values in output must match source data"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        import re

        # Collect reference numbers from context
        ref_numbers: set[float] = set()
        self._collect_numbers(context.get("quote", {}), ref_numbers)
        self._collect_numbers(context.get("indicators", {}), ref_numbers)

        # If no reference data, skip validation
        if not ref_numbers:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="No reference data for cross-validation",
            )

        # Extract numbers from output text fields
        output_numbers: set[float] = set()
        text_fields = [
            "reasoning", "analysis", "report_markdown", "executive_summary",
            "summary", "contrarian_check",
        ]
        for field_name in text_fields:
            val = data.get(field_name)
            if isinstance(val, str):
                for match in re.findall(r"[\d]+\.?\d*", val):
                    try:
                        output_numbers.add(float(match))
                    except ValueError:
                        pass
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        for match in re.findall(r"[\d]+\.?\d*", item):
                            try:
                                output_numbers.add(float(match))
                            except ValueError:
                                pass

        # P2-3: Also scan dimensions[].reasoning and risk_warnings[].description
        for dim in data.get("dimensions", []):
            if isinstance(dim, dict):
                r = dim.get("reasoning", "")
                if isinstance(r, str):
                    for match in re.findall(r"[\d]+\.?\d*", r):
                        try:
                            output_numbers.add(float(match))
                        except ValueError:
                            pass
        for rw in data.get("risk_warnings", []):
            desc = rw.get("description", "") if isinstance(rw, dict) else (rw if isinstance(rw, str) else "")
            if isinstance(desc, str):
                for match in re.findall(r"[\d]+\.?\d*", desc):
                    try:
                        output_numbers.add(float(match))
                    except ValueError:
                        pass

        # Filter out trivially small numbers (indices, percentages like 0-100)
        significant = {n for n in output_numbers if n > 1.0}

        # Check which output numbers have no reference match
        unmatched: list[float] = []
        for num in significant:
            # Allow 1% tolerance for rounding
            matched = any(
                abs(num - ref) / max(abs(ref), 1e-9) < 0.01 for ref in ref_numbers
            )
            if not matched:
                unmatched.append(num)

        if unmatched:
            # Add to data_gaps
            gaps = data.get("data_gaps", [])
            if not isinstance(gaps, list):
                gaps = []
            for num in unmatched[:5]:  # cap at 5
                gaps.append(f"V08: unverified number {num} in output")
            data["data_gaps"] = gaps

            return ValidationResult(
                rule_id=self.rule_id,
                passed=False,
                message=f"Found {len(unmatched)} unverified numerical value(s)",
                auto_fixed=True,
                fix_description="Flagged unverified numbers in data_gaps",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message="All significant numbers verified against source data",
        )

    @staticmethod
    def _collect_numbers(obj: Any, target: set[float], depth: int = 0) -> None:
        """Recursively collect numeric values from a dict/list."""
        if depth > 5:
            return
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            target.add(float(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                V08NumericalCrossValidation._collect_numbers(v, target, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                V08NumericalCrossValidation._collect_numbers(v, target, depth + 1)


class V10SignalTrendConsistency(ValidationRule):
    """V10: Cap tech_score when it contradicts clear MA trend.

    If MAs form a bearish arrangement (MA5 < MA10 < MA20 < MA60) but
    tech_score > 60, cap it to 40.  Conversely, if MAs form a bullish
    arrangement and tech_score < 40, floor it to 60.
    """

    rule_id = "V10"
    description = "Technical signal must be consistent with MA trend"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        indicators = context.get("indicators", {})
        if not indicators:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="No indicators for trend consistency check",
            )

        # Extract MAs
        ma_keys = [
            ("MA_5", "ma5", "MA5"),
            ("MA_10", "ma10", "MA10"),
            ("MA_20", "ma20", "MA20"),
            ("MA_60", "ma60", "MA60"),
        ]
        mas: list[float | None] = []
        for keys in ma_keys:
            val = None
            for k in keys:
                v = indicators.get(k)
                if isinstance(v, dict):
                    v = v.get("value")
                if v is not None:
                    try:
                        val = float(v)
                    except (TypeError, ValueError):
                        pass
                    break
            mas.append(val)

        valid = [v for v in mas if v is not None]
        if len(valid) < 3:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="Insufficient MA data for trend check",
            )

        # Check bearish arrangement: each shorter MA < longer MA
        pairs = [(mas[i], mas[i + 1]) for i in range(3) if mas[i] is not None and mas[i + 1] is not None]
        bearish_arr = all(a < b for a, b in pairs) if pairs else False
        bullish_arr = all(a > b for a, b in pairs) if pairs else False

        # Get tech_score from precomputed_quant in data
        precomputed = data.get("precomputed_quant", {})
        tech_score = precomputed.get("technical_score")
        if tech_score is None:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="No tech_score to validate",
            )

        symbol = context.get("symbol", "?")

        if bearish_arr and tech_score > 60:
            old = tech_score
            precomputed["technical_score"] = 40.0
            logger.warning(
                "V10: bearish MA arrangement but tech_score=%.1f for %s, capped to 40",
                old, symbol,
            )
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Bearish MA arrangement: tech_score {old:.1f} → 40",
                auto_fixed=True,
                fix_description=f"tech_score {old:.1f} → 40 (bearish MA arrangement)",
            )

        if bullish_arr and tech_score < 40:
            old = tech_score
            precomputed["technical_score"] = 60.0
            logger.warning(
                "V10: bullish MA arrangement but tech_score=%.1f for %s, floored to 60",
                old, symbol,
            )
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Bullish MA arrangement: tech_score {old:.1f} → 60",
                auto_fixed=True,
                fix_description=f"tech_score {old:.1f} → 60 (bullish MA arrangement)",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message="Signal-trend consistency OK",
        )


class V11HighConfidenceDimensionAgreement(ValidationRule):
    """V11: High confidence (>=0.8) requires >=3 dimensions agreeing on direction.

    Per CONFIDENCE_GRADING_TABLE, 0.80+ needs "≥3维度一致".  If the LLM
    outputs confidence >= 0.8 but fewer than 3 dimensions have signals
    consistent with the recommended action, auto-cap to 0.75.
    """

    rule_id = "V11"
    description = "High confidence requires >=3 dimensions agreeing with action direction"

    # Map actions to the expected bullish/bearish signal direction
    _ACTION_DIRECTION: dict[str, str] = {
        "buy": "bullish",
        "add": "bullish",
        "hold": "neutral",  # neutral is always "agreeing" for hold
        "reduce": "bearish",
        "sell": "bearish",
        "watch": "neutral",
    }

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        conf = _extract_confidence(data)
        if conf < 0.80:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="Confidence below 0.80, V11 not applicable",
            )

        action = str(data.get("action", "watch")).lower()
        expected = self._ACTION_DIRECTION.get(action, "neutral")

        dimensions = data.get("dimensions", [])
        if not isinstance(dimensions, list):
            dimensions = []

        # Count dimensions whose signal agrees with the action direction
        # For hold/watch, both bullish and bearish count as "not disagreeing"
        agreeing = 0
        for dim in dimensions:
            if not isinstance(dim, dict):
                continue
            key = dim.get("key", "")
            # confidence_basis is meta, skip it
            if key == "confidence_basis":
                continue
            signal = str(dim.get("signal", "neutral")).lower()
            if expected == "neutral":
                # For hold/watch, any signal is acceptable
                agreeing += 1
            elif signal == expected:
                agreeing += 1

        if agreeing < 3:
            # Auto-cap confidence to 0.75
            new_conf = 0.75
            if isinstance(data.get("confidence"), dict):
                data["confidence"]["score"] = new_conf
            else:
                data["confidence"] = new_conf
            symbol = context.get("symbol", "?")
            logger.info(
                "V11: confidence %.2f capped to 0.75 for %s "
                "(only %d/%d dimensions agree with %s)",
                conf, symbol, agreeing, len(dimensions), action,
            )
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"High confidence capped: only {agreeing} dimensions agree",
                auto_fixed=True,
                fix_description=f"confidence {conf:.2f} -> 0.75 ({agreeing} agreeing dims < 3)",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message=f"High confidence validated: {agreeing} dimensions agree",
        )


class V12StopLossReasonableness(ValidationRule):
    """V12: Validate stop-loss distance is reasonable.

    Checks that stop_loss is not too tight (<2% from current price, where
    normal volatility would trigger it) or too loose (>15%, losing protective
    purpose).  Does NOT auto-fix — only adds warnings to data_warnings.
    """

    rule_id = "V12"
    description = "Stop-loss distance must be between 2% and 15%"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        stop_loss_data = data.get("stop_loss")
        if not stop_loss_data:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="No stop_loss to validate",
            )

        # Extract stop_loss price
        if isinstance(stop_loss_data, dict):
            sl_price = stop_loss_data.get("price")
        else:
            sl_price = stop_loss_data

        if sl_price is None:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="No stop_loss price to validate",
            )

        try:
            sl = float(sl_price)
        except (TypeError, ValueError):
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="Stop_loss price not numeric, skipping",
            )

        # Get current price from context
        quote = context.get("quote", {})
        current_price = quote.get("price") if isinstance(quote, dict) else None
        if current_price is None:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="No current price for stop-loss distance check",
            )

        try:
            cp = float(current_price)
        except (TypeError, ValueError):
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="Current price not numeric",
            )

        if cp <= 0:
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="Current price is zero/negative",
            )

        distance_pct = (cp - sl) / cp * 100

        warnings: list[str] = data.get("data_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        added = False

        if 0 < distance_pct < 2.0:
            warnings.append(
                f"V12: 止损距离仅{distance_pct:.1f}%，过于紧密，正常日内波动即可触发。"
                "建议设置在3-8%区间。"
            )
            added = True
        elif distance_pct > 15.0:
            warnings.append(
                f"V12: 止损距离{distance_pct:.1f}%，过于宽松，失去风险保护意义。"
                "建议控制在5-10%区间。"
            )
            added = True

        if added:
            data["data_warnings"] = warnings
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message=f"Stop-loss distance {distance_pct:.1f}% flagged",
                auto_fixed=True,
                fix_description=f"Added stop-loss distance warning ({distance_pct:.1f}%)",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message=f"Stop-loss distance {distance_pct:.1f}% is reasonable",
        )


class V09TrustZoneEnforcement(ValidationRule):
    """V09: Compute trust zone and enforce zone policies.

    Uses composite score from (confidence, data_quality, validation_pass_rate)
    to determine trust zone.  Applies zone_policies:
    - UNTRUSTED: strips trade recommendations (action → watch)
    - LOW: adds confirmation requirement flag
    """

    rule_id = "V09"
    description = "Trust zone enforcement based on composite score"

    def validate(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        from src.web.schemas.versioning import compute_trust_zone

        confidence = _extract_confidence(data)
        data_quality = context.get("data_quality_score", 100)
        # Compute pass rate from prior validation results if available
        validation_pass_rate = context.get("validation_pass_rate", 1.0)

        trust_zone = compute_trust_zone(confidence, data_quality, validation_pass_rate)
        data["trust_zone"] = trust_zone

        if trust_zone == "UNTRUSTED":
            action = str(data.get("action", "watch")).lower()
            if action in ("buy", "sell", "add", "reduce"):
                data["action"] = "watch"
                return ValidationResult(
                    rule_id=self.rule_id,
                    passed=True,
                    message=f"UNTRUSTED zone: stripped trade recommendation ({action} -> watch)",
                    auto_fixed=True,
                    fix_description=f"action {action} -> watch (trust_zone=UNTRUSTED)",
                )
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="UNTRUSTED zone: no trade recommendation to strip",
            )

        if trust_zone == "LOW":
            data["require_user_confirmation"] = True
            return ValidationResult(
                rule_id=self.rule_id,
                passed=True,
                message="LOW trust zone: added confirmation requirement",
                auto_fixed=True,
                fix_description="require_user_confirmation = true",
            )

        return ValidationResult(
            rule_id=self.rule_id,
            passed=True,
            message=f"Trust zone: {trust_zone}",
        )


# ---------------------------------------------------------------------------
# Framework orchestrator
# ---------------------------------------------------------------------------


class ValidationFramework:
    """Orchestrates validation rules against analysis output data.

    Usage::

        framework = ValidationFramework()
        report = framework.validate(data, context={"symbol": "600519"})
        if not report.all_passed:
            logger.warning("Validation issues: %s", report.rules_failed)
    """

    def __init__(self, rules: list[ValidationRule] | None = None) -> None:
        if rules is not None:
            self._rules = rules
        else:
            self._rules = self._default_rules()

    @staticmethod
    def _default_rules() -> list[ValidationRule]:
        """Return the standard V01-V12 rule set in execution order."""
        return [
            V06JSONRepair(),
            V05ActionValidation(),
            V01ConfidenceNormalization(),
            V02LowConfidenceWatch(),
            V03MediumConfidenceRestriction(),
            V04HighRiskNoAggressive(),
            V07DataReferences(),
            V08NumericalCrossValidation(),
            V11HighConfidenceDimensionAgreement(),
            V12StopLossReasonableness(),
            V09TrustZoneEnforcement(),
            V10SignalTrendConsistency(),
        ]

    @property
    def rules(self) -> list[ValidationRule]:
        """Return the current rule set."""
        return list(self._rules)

    def add_rule(self, rule: ValidationRule) -> None:
        """Add a custom validation rule to the framework."""
        self._rules.append(rule)

    def validate(
        self,
        data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ValidationReport:
        """Run all validation rules against the data.

        Rules may mutate `data` in place to apply auto-fixes.

        Args:
            data: Analysis output dict (mutable).
            context: Additional context (symbol, data_quality_score, etc.).

        Returns:
            ValidationReport with per-rule results.
        """
        ctx = context or {}
        report = ValidationReport()

        for rule in self._rules:
            try:
                result = rule.validate(data, ctx)
                report.results.append(result)
            except Exception as exc:
                logger.warning(
                    "Validation rule %s raised an exception: %s",
                    rule.rule_id,
                    exc,
                )
                report.results.append(
                    ValidationResult(
                        rule_id=rule.rule_id,
                        passed=False,
                        message=f"Rule raised exception: {exc}",
                    )
                )

        return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_confidence(data: dict[str, Any]) -> float:
    """Extract confidence score from data dict (handles both dict and float)."""
    raw = data.get("confidence", 0.5)
    if isinstance(raw, dict):
        score = raw.get("score", 0.5)
    else:
        score = raw
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.5


def _clamp_confidence(score: float, data_quality_score: int) -> float:
    """Clamp confidence based on data quality (FR-PR006).

    Mirrors ``analysis_frameworks.clamp_confidence``.
    """
    if data_quality_score >= 80:
        return score
    if data_quality_score >= 60:
        return min(score, 0.7)
    if data_quality_score >= 40:
        return min(score, 0.5)
    return min(score, 0.3)
