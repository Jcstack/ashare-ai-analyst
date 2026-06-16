"""Pipeline planner — resolves user intent to a PipelineSpec.

Two modes:
1. **Config-driven** — matches user intent to predefined pipelines
   loaded from ``config/pipelines.yaml`` (fast path).
2. **LLM-driven** — generates a dynamic PipelineSpec when no
   predefined pipeline matches (slow path, requires LLM call).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.orchestration.primitives import PipelineSpec, RetryPolicy, StepSpec
from src.utils.logger import get_logger

logger = get_logger("orchestration.planner")

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "pipelines.yaml"
)

# Keywords that hint at a pipeline type
_PIPELINE_HINTS: dict[str, list[str]] = {
    "stock_analysis": [
        "分析",
        "怎么样",
        "看看",
        "诊断",
        "评估",
        "技术面",
        "基本面",
        "analyze",
        "analysis",
        "stock",
        "how about",
    ],
    "trade_decision": [
        "买",
        "卖",
        "加仓",
        "减仓",
        "建仓",
        "交易",
        "操作",
        "执行",
        "buy",
        "sell",
        "trade",
        "execute",
        "position",
    ],
    "portfolio_review": [
        "持仓",
        "组合",
        "仓位",
        "账户",
        "总览",
        "portfolio",
        "holdings",
    ],
    "market_overview": [
        "大盘",
        "市场",
        "行情",
        "指数",
        "概况",
        "market",
        "index",
        "overview",
    ],
}

_DYNAMIC_PLANNING_PROMPT = """\
你是投资分析系统的编排器。根据用户意图，生成一个分析流水线。

## 可用 Agent
{agent_list}

## 输出格式（严格 JSON）
```json
{{
  "name": "dynamic_{intent}",
  "steps": {{
    "step_id": {{
      "agent": "agent_name",
      "task": "任务描述",
      "depends_on": [],
      "input_filter": ["field1", "field2"],
      "output_fields": ["output1"],
      "required": true,
      "timeout_ms": 30000
    }}
  }},
  "require_all_outputs": ["confidence_score", "key_assumptions", "failure_modes", "data_lineage", "data_gaps"]
}}
```

## 规则
- data_qa 必须是第一步（无依赖），用于数据质量检查
- 涉及交易建议时必须包含 risk 步骤
- 涉及买卖执行时必须包含 exec_plan 步骤，且 exec_plan 必须在 risk 之后
- 每个步骤的 input_filter 只写真正需要的字段名（上下文隔离）
- require_all_outputs 必须包含：confidence_score, key_assumptions, failure_modes, data_lineage, data_gaps
- 只返回 JSON，不要其他文字
"""


class PipelinePlanner:
    """Resolves user intent into a PipelineSpec."""

    def __init__(
        self,
        llm_router: Any | None = None,
        available_agents: list[str] | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self._llm = llm_router
        self._available_agents = available_agents or []
        self._predefined: dict[str, PipelineSpec] = {}
        self._load_predefined(Path(config_path) if config_path else _CONFIG_PATH)

    @property
    def predefined_pipelines(self) -> dict[str, PipelineSpec]:
        return dict(self._predefined)

    def _load_predefined(self, path: Path) -> None:
        """Load predefined pipelines from YAML config."""
        if not path.exists():
            logger.info("No pipelines config at %s, skipping", path)
            return

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to parse %s", path, exc_info=True)
            return

        pipelines = raw.get("pipelines", {})
        for name, pdef in pipelines.items():
            try:
                self._predefined[name] = self._parse_pipeline(name, pdef)
                logger.debug("Loaded predefined pipeline: %s", name)
            except Exception:
                logger.warning("Failed to parse pipeline '%s'", name, exc_info=True)

        logger.info("Loaded %d predefined pipelines", len(self._predefined))

    @staticmethod
    def _parse_pipeline(name: str, raw: dict[str, Any]) -> PipelineSpec:
        """Parse a raw YAML dict into a PipelineSpec."""
        steps: dict[str, StepSpec] = {}
        for sid, sdef in raw.get("steps", {}).items():
            retry_raw = sdef.get("retry", {})
            retry = (
                RetryPolicy(
                    max_retries=retry_raw.get("max_retries", 1),
                    backoff_ms=retry_raw.get("backoff_ms", 1000),
                    retry_on=retry_raw.get("retry_on", ["timeout", "tool_error"]),
                )
                if retry_raw
                else RetryPolicy()
            )

            steps[sid] = StepSpec(
                agent=sdef.get("agent", ""),
                task=sdef.get("task", ""),
                depends_on=sdef.get("depends_on", []),
                input_filter=sdef.get("input_filter", []),
                output_fields=sdef.get("output_fields", []),
                required=sdef.get("required", True),
                timeout_ms=sdef.get("timeout_ms", 30_000),
                retry=retry,
            )

        return PipelineSpec(
            name=name,
            steps=steps,
            budget_tokens=raw.get("budget_tokens", 50_000),
            require_all_outputs=raw.get("require_all_outputs", []),
        )

    async def plan(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
    ) -> PipelineSpec:
        """Resolve user intent to a PipelineSpec.

        1. Try to match a predefined pipeline via keyword hinting.
        2. If no match and LLM is available, generate a dynamic pipeline.
        3. Fallback to a minimal single-agent pipeline.
        """
        ctx = context or {}

        # 1. Keyword matching
        matched = self._match_predefined(user_message)
        if matched:
            logger.info("Matched predefined pipeline: %s", matched.name)
            return self._substitute_templates(matched, ctx)

        # 2. LLM-driven planning
        if self._llm:
            try:
                dynamic = await self._plan_dynamic(user_message, ctx)
                if dynamic:
                    logger.info("Generated dynamic pipeline: %s", dynamic.name)
                    return dynamic
            except Exception:
                logger.warning("Dynamic planning failed", exc_info=True)

        # 3. Fallback: single analyst step
        logger.info("Using fallback single-agent pipeline")
        return PipelineSpec(
            name="fallback",
            steps={
                "analysis": StepSpec(
                    agent="analyst",
                    task=user_message,
                    input_filter=["*"],
                    output_fields=["*"],
                ),
            },
        )

    def _match_predefined(self, user_message: str) -> PipelineSpec | None:
        """Match user message to predefined pipeline via keyword hints."""
        msg_lower = user_message.lower()
        scores: dict[str, int] = {}

        for pipeline_name, keywords in _PIPELINE_HINTS.items():
            if pipeline_name not in self._predefined:
                continue
            score = sum(1 for kw in keywords if kw in msg_lower)
            if score > 0:
                scores[pipeline_name] = score

        if not scores:
            return None

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        return self._predefined[best]

    async def _plan_dynamic(
        self,
        user_message: str,
        ctx: dict[str, Any],
    ) -> PipelineSpec | None:
        """Use LLM to generate a PipelineSpec for novel queries."""
        from src.llm.base import LLMMessage

        agent_list = "\n".join(f"- {a}" for a in self._available_agents)
        system = _DYNAMIC_PLANNING_PROMPT.format(
            agent_list=agent_list,
            intent="custom",
        )

        if ctx.get("symbol"):
            system += f"\n\n用户关注的股票: {ctx['symbol']}"

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user_message),
        ]

        response = await asyncio.to_thread(
            self._llm.complete_with_tools,
            messages=messages,
            tools=[],
            max_tokens=1024,
            temperature=0.1,
            analysis_type="pipeline_planning",
        )

        text = (response.text or "").strip()

        # Extract JSON
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)

        try:
            plan_data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON for planning")
            return None

        return self._parse_pipeline(
            plan_data.get("name", "dynamic"),
            plan_data,
        )

    @staticmethod
    def _substitute_templates(
        pipeline: PipelineSpec,
        ctx: dict[str, Any],
    ) -> PipelineSpec:
        """Substitute ``{symbol}`` and similar placeholders in step tasks."""
        new_steps: dict[str, StepSpec] = {}
        for sid, step in pipeline.steps.items():
            task = step.task
            for key, val in ctx.items():
                if isinstance(val, str):
                    task = task.replace(f"{{{key}}}", val)
            new_steps[sid] = StepSpec(
                agent=step.agent,
                task=task,
                depends_on=list(step.depends_on),
                input_filter=list(step.input_filter),
                output_fields=list(step.output_fields),
                required=step.required,
                timeout_ms=step.timeout_ms,
                retry=step.retry,
            )
        return PipelineSpec(
            name=pipeline.name,
            steps=new_steps,
            budget_tokens=pipeline.budget_tokens,
            require_all_outputs=list(pipeline.require_all_outputs),
        )
