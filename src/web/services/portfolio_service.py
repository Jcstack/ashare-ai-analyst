"""Service layer for AI portfolio diagnosis.

Accepts user portfolio positions, enriches them with technical indicators,
and calls the LLM for a comprehensive portfolio health assessment.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError
from src.utils.logger import get_logger
from src.web.services.stock_service import StockService

logger = get_logger("web.portfolio_service")

_SYSTEM_PROMPT = """\
你是一位专业的A股投资组合分析师。用户将提供其当前持仓信息和技术指标数据。
请对整个投资组合进行全面诊断，并严格以 JSON 格式返回分析结果。

返回格式（不要包含任何 markdown 标记，直接返回纯 JSON）：
{
  "health_score": 0-100 整数,
  "health_label": "优秀/良好/一般/较差/危险" 之一,
  "summary": "一段话总结持仓整体状况",
  "concentration_risk": {
    "level": "low/medium/high",
    "description": "集中度风险说明",
    "top_holdings_pct": 前3大持仓占比百分比数值
  },
  "position_advice": [
    {
      "symbol": "股票代码",
      "name": "股票名称",
      "action": "hold/reduce/increase/stop_loss/take_profit",
      "reason": "操作理由",
      "target_price": 目标价或null
    }
  ],
  "rebalancing": ["调仓建议1", "调仓建议2"],
  "risk_warnings": ["风险提示1", "风险提示2"],
  "reasoning": ["推理步骤1", "推理步骤2", "推理步骤3"]
}

分析维度：
1. 持仓集中度：单只股票占比是否过高
2. 行业分散度：是否过度集中在某一板块
3. 盈亏状态：止损/止盈位是否合理
4. 技术面信号：结合指标判断各持仓当前位置
5. 整体风险：系统性风险评估

注意：
- health_score: 80-100=优秀, 60-79=良好, 40-59=一般, 20-39=较差, 0-19=危险
- 所有分析基于历史数据和技术指标，不构成投资建议
"""


class PortfolioService:
    """Orchestrates AI-powered portfolio diagnosis.

    Enriches user positions with technical indicators and sends
    a structured prompt to the LLM for comprehensive analysis.
    """

    def __init__(self, stock_service: StockService | None = None) -> None:
        self._stock_service = stock_service or StockService()
        self._llm_router = None

    def _get_llm_router(self):
        """Lazily initialize the LLM gateway."""
        if self._llm_router is None:
            from src.web.dependencies import get_llm_gateway

            self._llm_router = get_llm_gateway()
        return self._llm_router

    def diagnose_portfolio(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """Run AI diagnosis on a user's portfolio.

        Args:
            positions: List of position dicts from the frontend.

        Returns:
            Diagnosis result dict matching PortfolioDiagnosisResult schema.
        """
        if not positions:
            return {
                "status": "error",
                "message": "持仓列表为空，无法进行诊断",
            }

        # Build enriched portfolio data
        total_market_value = 0.0
        portfolio_lines: list[str] = []

        for pos in positions:
            symbol = pos["symbol"]
            name = pos.get("name", symbol)
            shares = pos.get("shares", 0)
            cost_price = pos.get("cost_price", 0)
            current_price = pos.get("current_price")
            pnl = pos.get("pnl")
            pnl_percent = pos.get("pnl_percent")

            market_value = (current_price or cost_price) * shares
            total_market_value += market_value

            # Try to get technical indicators
            indicators = {}
            try:
                indicators = self._stock_service.get_indicators_summary(symbol)
            except Exception as exc:
                logger.debug("Could not fetch indicators for %s: %s", symbol, exc)

            line = (
                f"- {name}({symbol}): "
                f"持仓{shares}股, 成本价{cost_price:.2f}, "
                f"现价{current_price or '未知'}, "
                f"市值{market_value:.0f}元"
            )
            if pnl is not None:
                line += f", 盈亏{pnl:+.0f}元({pnl_percent or 0:+.1f}%)"
            if indicators:
                ind_parts = []
                for key in ["RSI", "MACD", "MACD_hist", "KDJ_K", "KDJ_D"]:
                    if key in indicators and indicators[key] is not None:
                        ind_parts.append(f"{key}={indicators[key]}")
                for key in indicators:
                    if key.startswith("MA_") and indicators[key] is not None:
                        ind_parts.append(f"{key}={indicators[key]}")
                if ind_parts:
                    line += f"\n  技术指标: {', '.join(ind_parts)}"

            portfolio_lines.append(line)

        # Build user prompt
        user_prompt = (
            f"当前持仓 ({len(positions)} 只股票, "
            f"总市值约 {total_market_value:,.0f} 元):\n\n" + "\n".join(portfolio_lines)
        )

        # Call LLM
        try:
            router = self._get_llm_router()
            messages = [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ]
            response = router.complete(
                messages=messages,
                caller="portfolio_service.diagnose_portfolio",
                max_tokens=2048,
                temperature=0.3,
                analysis_type="portfolio_diagnosis",
            )
        except LLMProviderError as exc:
            logger.error("LLM call failed for portfolio diagnosis: %s", exc)
            return {"status": "error", "message": f"AI 分析失败: {exc}"}
        except Exception as exc:
            logger.error("Unexpected error in portfolio diagnosis: %s", exc)
            return {"status": "error", "message": f"系统错误: {exc}"}

        # Parse response
        result = self._parse_diagnosis(response.text)
        result["status"] = "success"
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        result["model_used"] = response.model
        return result

    def _parse_diagnosis(self, text: str) -> dict[str, Any]:
        """Parse LLM JSON response, handling markdown wrappers.

        Args:
            text: Raw LLM output text.

        Returns:
            Parsed diagnosis dict with safe defaults.
        """
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        json_str = json_match.group(1).strip() if json_match else text.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse diagnosis JSON, using defaults")
            return {
                "health_score": 50,
                "health_label": "一般",
                "summary": text[:500],
                "concentration_risk": None,
                "position_advice": [],
                "rebalancing": [],
                "risk_warnings": ["AI 返回格式异常，请重试"],
                "reasoning": [],
            }

        # Normalize concentration_risk
        cr = data.get("concentration_risk")
        if isinstance(cr, dict):
            data["concentration_risk"] = {
                "level": cr.get("level", "low"),
                "description": cr.get("description", ""),
                "top_holdings_pct": cr.get("top_holdings_pct"),
            }

        # Ensure list fields
        for key in ("position_advice", "rebalancing", "risk_warnings", "reasoning"):
            if not isinstance(data.get(key), list):
                data[key] = []

        # Clamp health_score
        score = data.get("health_score", 50)
        if isinstance(score, (int, float)):
            data["health_score"] = max(0, min(100, int(score)))
        else:
            data["health_score"] = 50

        return data
