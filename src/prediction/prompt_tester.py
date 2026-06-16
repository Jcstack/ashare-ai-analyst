"""Prompt testing and AI-assisted optimization.

Executes prompt templates with test variables against the LLM,
and provides AI-assisted optimization suggestions.

Per PRD v2.5 FR-PM003, FR-PM004.
"""

import json
import time
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError
from src.llm.router import RoutingStrategy
from src.prediction.prompt_manager import PromptManager
from src.utils.logger import get_logger

logger = get_logger("prediction.prompt_tester")


class PromptTester:
    """Executes prompt tests and provides AI optimization suggestions."""

    def __init__(
        self,
        prompt_manager: PromptManager | None = None,
        router: Any | None = None,
    ) -> None:
        self._pm = prompt_manager or PromptManager()
        if router is None:
            from src.web.dependencies import get_llm_gateway

            router = get_llm_gateway()
        self._router = router

    def test_prompt(
        self,
        prompt_id: str,
        test_variables: dict[str, str],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Execute a prompt template with test variables.

        Args:
            prompt_id: The prompt template ID.
            test_variables: Variable name -> value mapping for template substitution.
            max_tokens: Max tokens for LLM response.
            temperature: LLM temperature.

        Returns:
            Test result dict with response, token counts, latency, cost.
        """
        prompt = self._pm.get_prompt(prompt_id)
        if prompt is None:
            return {"status": "error", "message": f"Prompt '{prompt_id}' not found"}

        system_template = prompt.get("system_template", "")
        user_template = prompt.get("user_template", "")

        # Substitute variables
        try:
            system_text = system_template.format(**test_variables)
            user_text = user_template.format(**test_variables)
        except KeyError as exc:
            return {
                "status": "error",
                "message": f"Missing variable: {exc}",
            }

        messages = [
            LLMMessage(role="system", content=system_text),
            LLMMessage(role="user", content=user_text),
        ]

        start = time.time()
        try:
            response = self._router.complete(
                messages=messages,
                caller="prompt_tester.test_prompt",
                strategy=RoutingStrategy.COST,
                max_tokens=max_tokens,
                temperature=temperature,
                analysis_type="prompt_test",
            )
            latency_ms = int((time.time() - start) * 1000)
            return {
                "status": "success",
                "response": response.text,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": latency_ms,
                "cost_usd": response.cost_usd,
                "rendered_system": system_text,
                "rendered_user": user_text,
            }
        except (LLMProviderError, Exception) as exc:
            latency_ms = int((time.time() - start) * 1000)
            logger.error("Prompt test failed for %s: %s", prompt_id, exc)
            return {
                "status": "error",
                "message": str(exc),
                "latency_ms": latency_ms,
                "rendered_system": system_text,
                "rendered_user": user_text,
            }

    def optimize_prompt(
        self,
        prompt_id: str,
        test_output: str | None = None,
    ) -> dict[str, Any]:
        """Use AI to suggest improvements for a prompt template.

        Args:
            prompt_id: The prompt template ID.
            test_output: Optional previous test output for context.

        Returns:
            Optimization suggestions dict.
        """
        prompt = self._pm.get_prompt(prompt_id)
        if prompt is None:
            return {"status": "error", "message": f"Prompt '{prompt_id}' not found"}

        meta_prompt = (
            "你是一名 Prompt Engineering 专家。分析以下 prompt 模板并提出优化建议。\n\n"
            f"## Prompt 名称\n{prompt.get('name', '')}\n\n"
            f"## System Template\n```\n{prompt.get('system_template', '')}\n```\n\n"
            f"## User Template\n```\n{prompt.get('user_template', '')}\n```\n\n"
        )

        if test_output:
            meta_prompt += f"## 最近一次测试输出\n```\n{test_output[:2000]}\n```\n\n"

        meta_prompt += (
            "请从以下维度给出优化建议，严格按照JSON格式输出：\n"
            "```json\n"
            "{\n"
            '  "overall_score": 0~100,\n'
            '  "suggestions": [\n'
            '    {"aspect": "方面", "issue": "问题", "recommendation": "建议", "priority": "high|medium|low"}\n'
            "  ],\n"
            '  "improved_system_template": "优化后的system模板",\n'
            '  "improved_user_template": "优化后的user模板"\n'
            "}\n"
            "```"
        )

        messages = [
            LLMMessage(
                role="system",
                content="你是Prompt Engineering专家，帮助优化A股分析prompt模板。",
            ),
            LLMMessage(role="user", content=meta_prompt),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="prompt_tester.optimize_prompt",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=16384,
                temperature=0.4,
                analysis_type="prompt_optimize",
            )
            # Try to parse JSON from response
            import re

            text = response.text
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            json_str = match.group(1).strip() if match else text
            try:
                result = json.loads(json_str)
            except json.JSONDecodeError:
                result = {"raw_suggestions": text[:3000]}

            result["status"] = "success"
            result["model"] = response.model
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Prompt optimization failed for %s: %s", prompt_id, exc)
            return {"status": "error", "message": str(exc)}
