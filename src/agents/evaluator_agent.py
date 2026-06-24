"""Independent Evaluator Agent — quality assessment of analysis output.

Performs rule-based checks (no LLM, ~5ms) and optional LLM meta-review
to evaluate the quality and consistency of unified analysis results.

Part of WS5: Independent Evaluation Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.utils.logger import get_logger

logger = get_logger("agents.evaluator")


@dataclass
class EvaluationFlag:
    """A single evaluation finding."""

    rule: str
    severity: str  # "error", "warning", "info"
    message: str


@dataclass
class EvaluationReport:
    """Complete evaluation result."""

    quality_score: float = 0.0
    checks_passed: int = 0
    checks_total: int = 0
    flags: list[EvaluationFlag] = field(default_factory=list)
    meta_review: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": round(self.quality_score, 2),
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "flags": [
                {"rule": f.rule, "severity": f.severity, "message": f.message}
                for f in self.flags
            ],
            "meta_review": self.meta_review,
        }


class EvaluatorAgent(BaseAgent):
    """Evaluates the quality and consistency of analysis output.

    Rule-based checks (no LLM, ~5ms):
    1. Dimension consistency — majority signal should align with action
    2. Confidence calibration — low data quality caps confidence
    3. Risk warning completeness — buy/add must have risk warnings
    4. Data reference adequacy — at least 3 data references required
    5. Stop loss presence — buy/add must have stop_loss
    6. Five-element compliance — all mandatory fields present

    Optional LLM meta-review (~3s):
    - Feed analysis + input data to LLM
    - Identify logical gaps and unsupported claims
    """

    def __init__(
        self,
        capability: AgentCapability | None = None,
        tool_registry: Any = None,
        llm_router: Any = None,
        system_role: str = "",
    ) -> None:
        cap = capability or AgentCapability(
            name="evaluator",
            description="Independent quality evaluator",
            use_llm=False,
            temperature=0.0,
        )
        super().__init__(cap)
        self._tools = tool_registry
        self._llm_router = llm_router
        self._system_role = system_role

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Execute evaluation on the analysis in message.context."""
        import json

        analysis = message.context
        report = self.evaluate(analysis)

        return AgentMessage(
            from_agent=self.name,
            to_agent=message.from_agent,
            task=message.task,
            result=json.dumps(report.to_dict(), ensure_ascii=False),
            tokens_used=0,
            tool_calls_made=0,
        )

    def evaluate(
        self,
        analysis: dict[str, Any],
        data_quality_score: int | None = None,
    ) -> EvaluationReport:
        """Run all rule-based evaluation checks.

        Args:
            analysis: Unified analysis result dict.
            data_quality_score: Optional override for data quality score.

        Returns:
            EvaluationReport with quality score and flags.
        """
        report = EvaluationReport()
        flags: list[EvaluationFlag] = []

        # Extract if nested
        if "data_quality_score" in analysis and data_quality_score is None:
            data_quality_score = analysis.get("data_quality_score", 100)

        # ── Rule 1: Dimension consistency ────────────────────
        report.checks_total += 1
        dimensions = analysis.get("dimensions", [])
        action = str(analysis.get("action", "watch")).lower()

        if dimensions:
            bullish_count = sum(
                1
                for d in dimensions
                if isinstance(d, dict) and d.get("signal") == "bullish"
            )
            bearish_count = sum(
                1
                for d in dimensions
                if isinstance(d, dict) and d.get("signal") == "bearish"
            )
            total_dims = len(dimensions)

            is_consistent = True
            if total_dims > 0:
                bullish_ratio = bullish_count / total_dims
                bearish_ratio = bearish_count / total_dims

                if bullish_ratio > 0.6 and action in ("sell", "reduce"):
                    is_consistent = False
                    flags.append(
                        EvaluationFlag(
                            rule="dimension_consistency",
                            severity="warning",
                            message=f"多数维度看多({bullish_count}/{total_dims})但操作建议为{action}",
                        )
                    )
                elif bearish_ratio > 0.6 and action in ("buy", "add"):
                    is_consistent = False
                    flags.append(
                        EvaluationFlag(
                            rule="dimension_consistency",
                            severity="warning",
                            message=f"多数维度看空({bearish_count}/{total_dims})但操作建议为{action}",
                        )
                    )

            if is_consistent:
                report.checks_passed += 1

        else:
            report.checks_passed += 1  # No dimensions to check

        # ── Rule 2: Confidence calibration ───────────────────
        report.checks_total += 1
        confidence = analysis.get("confidence", {})
        conf_score = (
            confidence.get("score", 0.5) if isinstance(confidence, dict) else confidence
        )

        try:
            conf_score = float(conf_score)
        except (TypeError, ValueError):
            conf_score = 0.5

        dq_score = data_quality_score if data_quality_score is not None else 100

        if dq_score < 40 and conf_score > 0.6:
            flags.append(
                EvaluationFlag(
                    rule="confidence_calibration",
                    severity="warning",
                    message=f"数据质量低({dq_score})但置信度偏高({conf_score:.2f})，建议不超过0.6",
                )
            )
        else:
            report.checks_passed += 1

        # ── Rule 3: Risk warning completeness ────────────────
        report.checks_total += 1
        risk_warnings = analysis.get("risk_warnings", [])

        if action in ("buy", "add") and len(risk_warnings) < 1:
            flags.append(
                EvaluationFlag(
                    rule="risk_warning_completeness",
                    severity="error",
                    message=f"操作建议为{action}但缺少风险提示",
                )
            )
        else:
            report.checks_passed += 1

        # ── Rule 4: Data reference adequacy ──────────────────
        report.checks_total += 1
        data_refs = analysis.get("data_references", [])

        if len(data_refs) < 3:
            flags.append(
                EvaluationFlag(
                    rule="data_reference_adequacy",
                    severity="warning",
                    message=f"数据引用不足: {len(data_refs)}/3",
                )
            )
        else:
            report.checks_passed += 1

        # ── Rule 5: Stop loss presence ───────────────────────
        report.checks_total += 1
        stop_loss = analysis.get("stop_loss")

        if action in ("buy", "add") and stop_loss is None:
            flags.append(
                EvaluationFlag(
                    rule="stop_loss_presence",
                    severity="warning",
                    message="买入/加仓建议缺少止损位",
                )
            )
        else:
            report.checks_passed += 1

        # ── Rule 6: Five-element compliance ──────────────────
        report.checks_total += 1
        mandatory_fields = [
            "action",
            "confidence",
            "risk_level",
            "summary",
            "dimensions",
        ]
        missing = [f for f in mandatory_fields if not analysis.get(f)]

        if missing:
            flags.append(
                EvaluationFlag(
                    rule="five_element_compliance",
                    severity="error",
                    message=f"缺少必填字段: {', '.join(missing)}",
                )
            )
        else:
            report.checks_passed += 1

        # ── Calculate quality score ──────────────────────────
        report.flags = flags
        if report.checks_total > 0:
            base_score = report.checks_passed / report.checks_total
            # Penalize errors more than warnings
            error_count = sum(1 for f in flags if f.severity == "error")
            warning_count = sum(1 for f in flags if f.severity == "warning")
            penalty = error_count * 0.15 + warning_count * 0.05
            report.quality_score = max(0.0, min(1.0, base_score - penalty))
        else:
            report.quality_score = 1.0

        return report

    async def evaluate_with_llm(
        self,
        analysis: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> EvaluationReport:
        """Run rule-based evaluation + optional LLM meta-review.

        Args:
            analysis: Unified analysis result dict.
            input_data: Original input data for cross-reference.

        Returns:
            EvaluationReport with meta_review populated.
        """
        import json

        from src.llm.base import LLMMessage

        report = self.evaluate(analysis)

        if self._llm_router is None:
            return report

        # Build LLM prompt for meta-review
        analysis_summary = json.dumps(
            {k: v for k, v in analysis.items() if k != "disclaimer"},
            ensure_ascii=False,
            default=str,
        )[:3000]

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are an independent analysis quality auditor. Review the following "
                    "AI analysis output — identify logical gaps, conclusions lacking data "
                    "support, and overlooked risk factors. "
                    "Output a concise 2-3 sentence review. "
                    "Write all output text in Chinese."
                ),
            ),
            LLMMessage(
                role="user",
                content=f"## Analysis Result\n{analysis_summary}",
            ),
        ]

        try:
            has_caller = hasattr(self._llm_router, "_audit_log")
            kwargs: dict[str, Any] = {
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.2,
                "analysis_type": "evaluation_meta_review",
            }
            if has_caller:
                kwargs["caller"] = "evaluator_agent.meta_review"

            response = self._llm_router.complete(**kwargs)
            report.meta_review = response.text.strip()
        except Exception as exc:
            logger.warning("LLM meta-review failed: %s", exc)
            report.meta_review = ""

        return report
