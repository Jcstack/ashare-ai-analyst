"""Prediction Monitoring agent — drift detection (rule engine, no LLM).

Tracks prediction accuracy, detects drift, and flags symbols
that need recalibration.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.utils.logger import get_logger

logger = get_logger("agents.prediction_monitor")


class PredictionMonitorAgent(BaseAgent):
    """Prediction monitoring specialist — rule engine, no LLM.

    Capabilities:
    - Accuracy summary retrieval
    - Drift detection
    - Backfill status checking

    Forbidden: All trade tools.
    """

    def __init__(
        self,
        capability: AgentCapability,
        tool_registry: Any,
        llm_router: Any = None,
        system_role: str = "",
    ) -> None:
        super().__init__(capability)
        self._tools = tool_registry

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Check prediction accuracy and drift status."""
        start = time.perf_counter()
        tool_calls_count = 0
        data_gaps: list[str] = []

        window_days = message.context.get("window_days", 30)
        accuracy_summary: dict[str, Any] = {}
        drift_report: dict[str, Any] = {}
        flagged_symbols: list[str] = []

        # Try to get accuracy summary from model monitor
        try:
            from src.intelligence.model_monitor import ModelMonitor

            monitor = ModelMonitor()
            summary = monitor.get_accuracy_summary(window_days=window_days)
            accuracy_summary = summary if isinstance(summary, dict) else {}
        except Exception:
            data_gaps.append("模型监控模块不可用")

        # Try drift detection
        try:
            from src.intelligence.model_monitor import ModelMonitor

            monitor = ModelMonitor()
            drift = monitor.detect_drift()
            if hasattr(drift, "__dict__"):
                drift_report = {
                    "has_significant_drift": getattr(
                        drift, "has_significant_drift", False
                    ),
                    "overall_accuracy": getattr(drift, "overall_accuracy", None),
                    "accuracy_by_window": getattr(drift, "accuracy_by_window", {}),
                }
                if drift_report.get("has_significant_drift"):
                    flagged_symbols = getattr(drift, "flagged_symbols", [])
        except Exception:
            data_gaps.append("漂移检测不可用")

        confidence = 0.8 if accuracy_summary else 0.3

        result = json.dumps(
            {
                "accuracy_summary": accuracy_summary,
                "drift_report": drift_report,
                "flagged_symbols": flagged_symbols,
                "window_days": window_days,
                "confidence_score": confidence,
                "data_gaps": data_gaps,
                "key_assumptions": [
                    "预测结果有足够的回填数据",
                    "检测窗口覆盖有代表性的市场周期",
                ],
                "failure_modes": [
                    "回填数据不足导致统计意义不够",
                    "市场 regime 根本性变化导致所有模型漂移",
                ],
            },
            ensure_ascii=False,
        )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "PredictionMonitorAgent: flagged=%d, %.0fms",
            len(flagged_symbols),
            elapsed,
        )

        return AgentMessage(
            from_agent=self.name,
            to_agent=message.from_agent,
            task=message.task,
            context=message.context,
            budget_remaining=message.budget_remaining,
            result=result,
            tool_calls_made=tool_calls_count,
            tokens_used=0,
            delegation_chain=[*message.delegation_chain, self.name],
        )
