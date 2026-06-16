"""Reflection agent — meta-agent that reviews other agents' outputs.

Part of v18.0 Intelligence Loop.

Audits key assumptions, checks consistency with historical predictions,
and adjusts confidence levels based on reflection analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    """Result of a reflection review."""

    original_confidence: float
    adjusted_confidence: float
    confidence_delta: float
    issues_found: list[str] = field(default_factory=list)
    assumptions_checked: int = 0
    assumptions_valid: int = 0
    consistency_score: float | None = None  # vs historical predictions
    recommendation: str = ""  # "accept", "reduce_confidence", "flag_for_review"


@dataclass
class ReflectionConfig:
    """Configuration for reflection agent."""

    max_assumptions_to_check: int = 5
    max_confidence_reduction: float = 0.20
    # Confidence thresholds for automatic flagging
    low_confidence_threshold: float = 0.40
    high_confidence_threshold: float = 0.90
    enabled: bool = True


class ReflectionAgent:
    """Reviews analysis outputs for quality and consistency.

    Checks:
    1. Key assumptions plausibility
    2. Internal consistency of signals
    3. Confidence calibration (penalize overconfidence)
    4. Historical prediction consistency
    """

    def __init__(self, config: ReflectionConfig | None = None):
        self.config = config or ReflectionConfig()

    def reflect(
        self,
        analysis: dict[str, Any],
        historical_accuracy: dict[str, Any] | None = None,
    ) -> ReflectionResult:
        """Run reflection on an analysis result.

        Args:
            analysis: The analysis output to review. Expected keys:
                - confidence: float (0-1)
                - key_assumptions: list[str]
                - dimensions: list[dict] with signal/confidence per dimension
                - risk_level: str
                - direction: str ("bullish"/"bearish"/"neutral")
            historical_accuracy: Optional accuracy summary from ModelMonitor.

        Returns:
            ReflectionResult with adjusted confidence and issues.
        """
        if not self.config.enabled:
            conf = analysis.get("confidence", 0.5)
            return ReflectionResult(
                original_confidence=conf,
                adjusted_confidence=conf,
                confidence_delta=0.0,
                recommendation="accept",
            )

        original_conf = analysis.get("confidence", 0.5)
        issues: list[str] = []
        penalty = 0.0

        # 1. Check assumptions
        assumptions = analysis.get("key_assumptions", [])
        checked, valid = self._check_assumptions(assumptions)

        if checked > 0 and valid < checked * 0.5:
            p = 0.05 * (checked - valid)
            penalty += p
            issues.append(
                f"假设验证通过率低: {valid}/{checked} ({valid / checked:.0%})"
            )

        # 2. Check signal consistency
        consistency_penalty = self._check_signal_consistency(analysis)
        if consistency_penalty > 0:
            penalty += consistency_penalty
            issues.append("维度信号存在矛盾")

        # 3. Check confidence calibration
        cal_penalty = self._check_calibration(original_conf, analysis)
        if cal_penalty > 0:
            penalty += cal_penalty

        # 4. Check historical accuracy
        consistency_score = None
        if historical_accuracy:
            acc = historical_accuracy.get("accuracy_t5")
            if acc is not None:
                consistency_score = acc
                if acc < 0.4:
                    p = 0.10
                    penalty += p
                    issues.append(f"历史准确率偏低: T+5 {acc:.0%}")
                elif acc < 0.5:
                    p = 0.05
                    penalty += p
                    issues.append(f"历史准确率低于基线: T+5 {acc:.0%}")

        # Apply penalty (capped)
        penalty = min(penalty, self.config.max_confidence_reduction)
        adjusted = max(original_conf - penalty, 0.1)
        delta = adjusted - original_conf

        # Determine recommendation
        if penalty >= 0.15:
            recommendation = "flag_for_review"
        elif penalty > 0:
            recommendation = "reduce_confidence"
        else:
            recommendation = "accept"

        return ReflectionResult(
            original_confidence=round(original_conf, 4),
            adjusted_confidence=round(adjusted, 4),
            confidence_delta=round(delta, 4),
            issues_found=issues,
            assumptions_checked=checked,
            assumptions_valid=valid,
            consistency_score=consistency_score,
            recommendation=recommendation,
        )

    def _check_assumptions(self, assumptions: list[str]) -> tuple[int, int]:
        """Check plausibility of key assumptions.

        Uses heuristic rules to flag problematic assumptions.
        Returns (checked, valid) counts.
        """
        if not assumptions:
            return 0, 0

        to_check = assumptions[: self.config.max_assumptions_to_check]
        valid = 0

        for assumption in to_check:
            if self._is_assumption_valid(assumption):
                valid += 1

        return len(to_check), valid

    def _is_assumption_valid(self, assumption: str) -> bool:
        """Heuristic check for assumption plausibility."""
        # Flag common weak assumptions
        weak_patterns = [
            "一定",  # "definitely" — too certain
            "必然",  # "inevitably"
            "肯定",  # "certainly"
            "不可能",  # "impossible"
            "永远",  # "forever"
            "100%",
            "零风险",  # "zero risk"
        ]
        for pattern in weak_patterns:
            if pattern in assumption:
                return False

        # Assumptions that are too short are suspicious
        if len(assumption) < 5:
            return False

        return True

    def _check_signal_consistency(self, analysis: dict[str, Any]) -> float:
        """Check if dimension signals are internally consistent.

        Returns penalty amount (0 = consistent).
        """
        dimensions = analysis.get("dimensions", [])
        if len(dimensions) < 2:
            return 0.0

        direction = analysis.get("direction", "neutral")

        # Count how many dimensions agree vs disagree with overall direction
        agree = 0
        disagree = 0
        for dim in dimensions:
            dim_signal = dim.get("signal", "neutral")
            if dim_signal == "neutral":
                continue
            if (direction == "bullish" and dim_signal == "bullish") or (
                direction == "bearish" and dim_signal == "bearish"
            ):
                agree += 1
            else:
                disagree += 1

        total = agree + disagree
        if total == 0:
            return 0.0

        # Penalty if more dimensions disagree than agree
        if disagree > agree:
            return 0.05
        # Penalty if direction is strong but signals are mixed
        if disagree > 0 and analysis.get("confidence", 0) > 0.8:
            return 0.03

        return 0.0

    def _check_calibration(self, confidence: float, analysis: dict[str, Any]) -> float:
        """Check if confidence level is well-calibrated.

        Penalize overconfidence (>90%) and flag low confidence (<40%).
        """
        issues = []
        penalty = 0.0

        if confidence > self.config.high_confidence_threshold:
            # Very high confidence is suspicious
            risk = analysis.get("risk_level", "").upper()
            if risk in ("HIGH", "MEDIUM"):
                penalty = 0.10
                issues.append(f"高置信度({confidence:.0%})与风险等级({risk})矛盾")
            elif confidence > 0.95:
                penalty = 0.05
                issues.append(f"置信度过高({confidence:.0%}), 可能过拟合")

        return penalty
