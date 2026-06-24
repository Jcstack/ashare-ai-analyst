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
You are a professional A-share portfolio analyst. The user will provide their current \
holdings and technical indicator data. Perform a comprehensive portfolio diagnosis \
and return results in strict JSON format.

All text values in the output must be in Chinese.

Return format (no markdown wrappers, return pure JSON):
{
  "health_score": integer 0-100,
  "health_label": one of "优秀/良好/一般/较差/危险",
  "summary": "one paragraph summarizing overall portfolio status (Chinese)",
  "concentration_risk": {
    "level": "low/medium/high",
    "description": "concentration risk description (Chinese)",
    "top_holdings_pct": top 3 holdings percentage as number
  },
  "position_advice": [
    {
      "symbol": "stock code",
      "name": "stock name (Chinese)",
      "action": "hold/reduce/increase/stop_loss/take_profit",
      "reason": "action rationale (Chinese)",
      "target_price": target price or null
    }
  ],
  "rebalancing": ["rebalancing advice 1 (Chinese)", "advice 2 (Chinese)"],
  "risk_warnings": ["risk warning 1 (Chinese)", "warning 2 (Chinese)"],
  "reasoning": ["reasoning step 1 (Chinese)", "step 2", "step 3"]
}

Analysis dimensions:
1. Holding concentration: is any single stock's weight too high
2. Industry diversification: is the portfolio over-concentrated in one sector
3. P&L status: are stop-loss/take-profit levels reasonable
4. Technical signals: assess current position of each holding using indicators
5. Systemic risk: overall risk assessment

Notes:
- health_score: 80-100=优秀, 60-79=良好, 40-59=一般, 20-39=较差, 0-19=危险
- All analysis is based on historical data and technical indicators, not investment advice
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
