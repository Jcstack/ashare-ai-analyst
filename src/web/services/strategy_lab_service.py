"""Service for AI-driven strategy lab features.

Provides natural-language strategy creation, AI parameter optimization,
and attribution analysis via LLM.

Implements FR-AI001~AI003 from PRD v3.0.
"""

from __future__ import annotations

import json
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("web.strategy_lab_service")

# Strategy key mapping for NL creation
NL_STRATEGY_MAP: dict[str, str] = {
    "趋势": "trend_following",
    "趋势跟踪": "trend_following",
    "均线": "trend_following",
    "均值回归": "mean_reversion",
    "布林": "mean_reversion",
    "超卖": "mean_reversion",
    "动量": "momentum",
    "突破": "momentum",
    "放量": "momentum",
}


class StrategyLabService:
    """AI-driven strategy lab service.

    Methods:
    - create_from_nl: Parse Chinese NL description into strategy config
    - optimize_params: AI suggests parameter optimizations
    - analyze_attribution: Deep AI attribution analysis
    """

    def create_from_nl(
        self,
        description: str,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Parse a natural-language strategy description into config.

        Args:
            description: Chinese NL strategy description.
            symbol: Optional stock symbol for context.

        Returns:
            Dict with strategy_key, params, explanation.
        """
        from src.web.dependencies import get_llm_gateway

        prompt = f"""You are an A-share quantitative strategy expert. The user described a \
trading strategy in natural language. Parse it into an executable strategy configuration.

All text values in the JSON output must be in Chinese.

User description: "{description}"
{f"Target stock: {symbol}" if symbol else ""}

Available strategy types:
1. trend_following (趋势跟踪): params fast_ma(2-30), slow_ma(10-120), volume_threshold(1.0-5.0)
2. mean_reversion (均值回归): params bb_period(10-50), bb_std(1.0-4.0), rsi_period(5-30), rsi_oversold(10-40), rsi_overbought(60-90)
3. momentum (动量策略): params roc_period(5-30), rsi_period(5-30), rsi_threshold(30-70), volume_surge_threshold(1.0-5.0)

Return JSON only, no other content:
{{
  "strategy_key": "策略类型key",
  "params": {{"参数名": 值}},
  "explanation": "策略解读(中文，2-3句话)",
  "confidence": 0.0-1.0
}}"""

        try:
            router = get_llm_gateway()
            response = router.complete(
                messages=[{"role": "user", "content": prompt}],
                caller="strategy_lab.create_from_nl",
                max_tokens=1024,
                temperature=0.3,
                analysis_type="nl_strategy_create",
            )

            content = response.content.strip()
            # Extract JSON from response
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            parsed = json.loads(content)
            return {
                "status": "success",
                "strategy_key": parsed.get("strategy_key", "trend_following"),
                "params": parsed.get("params", {}),
                "explanation": parsed.get("explanation", ""),
                "confidence": parsed.get("confidence", 0.5),
            }
        except json.JSONDecodeError:
            # Fallback: keyword matching
            matched_key = "trend_following"
            for keyword, key in NL_STRATEGY_MAP.items():
                if keyword in description:
                    matched_key = key
                    break
            return {
                "status": "success",
                "strategy_key": matched_key,
                "params": {},
                "explanation": f"已根据关键词匹配为 {matched_key} 策略",
                "confidence": 0.3,
            }
        except Exception as exc:
            logger.error("NL strategy creation failed: %s", exc)
            return {"status": "error", "message": f"策略创建失败: {exc}"}

    def optimize_params(
        self,
        symbol: str,
        strategy_key: str,
        current_params: dict[str, Any],
        current_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """AI suggests parameter optimizations.

        Args:
            symbol: Stock symbol.
            strategy_key: Current strategy key.
            current_params: Current parameter values.
            current_metrics: Current backtest metrics.

        Returns:
            Dict with suggested_params, reasoning, comparison.
        """
        from src.web.dependencies import get_llm_gateway

        prompt = f"""You are an A-share quantitative strategy tuning expert. Based on the \
current backtest results, suggest parameter optimizations.

All text values in the JSON output must be in Chinese.

Stock: {symbol}
Strategy: {strategy_key}
Current params: {json.dumps(current_params, ensure_ascii=False)}
Current performance:
- Total return: {current_metrics.get("total_return", 0):.2%}
- Annualized return: {current_metrics.get("annual_return", 0):.2%}
- Sharpe ratio: {current_metrics.get("sharpe_ratio", 0):.4f}
- Max drawdown: {current_metrics.get("max_drawdown", 0):.2%}
- Win rate: {current_metrics.get("win_rate", 0):.2%}
- Total trades: {current_metrics.get("total_trades", 0)}

Analyze the current strategy's weaknesses and suggest parameter adjustments. \
Return JSON only, no other content:
{{
  "suggested_params": {{"参数名": 建议值}},
  "reasoning": ["原因1", "原因2", ...],
  "param_explanations": {{"参数名": "调整理由"}}
}}"""

        try:
            router = get_llm_gateway()
            response = router.complete(
                messages=[{"role": "user", "content": prompt}],
                caller="strategy_lab.optimize_params",
                max_tokens=1024,
                temperature=0.3,
                symbol=symbol,
                analysis_type="param_optimize",
            )

            content = response.content.strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            parsed = json.loads(content)
            return {
                "status": "success",
                "suggested_params": parsed.get("suggested_params", {}),
                "reasoning": parsed.get("reasoning", []),
                "param_explanations": parsed.get("param_explanations", {}),
            }
        except Exception as exc:
            logger.error("Parameter optimization failed: %s", exc)
            return {"status": "error", "message": f"参数优化失败: {exc}"}

    def analyze_attribution(
        self,
        symbol: str,
        strategy_name: str,
        round_trips: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Deep AI attribution analysis for backtest results.

        Args:
            symbol: Stock symbol.
            strategy_name: Strategy display name.
            round_trips: List of round-trip trade records.
            metrics: Backtest performance metrics.

        Returns:
            Dict with analysis summary, key findings, suggestions.
        """
        from src.web.dependencies import get_llm_gateway

        # Summarize round trips
        if round_trips:
            wins = [rt for rt in round_trips if rt.get("pnl", 0) > 0]
            losses = [rt for rt in round_trips if rt.get("pnl", 0) <= 0]
            rt_summary = (
                f"共 {len(round_trips)} 笔交易，"
                f"盈利 {len(wins)} 笔，亏损 {len(losses)} 笔。"
            )
            if wins:
                avg_win = sum(rt["pnl"] for rt in wins) / len(wins)
                rt_summary += f" 平均盈利 ¥{avg_win:.0f}。"
            if losses:
                avg_loss = sum(abs(rt["pnl"]) for rt in losses) / len(losses)
                rt_summary += f" 平均亏损 ¥{avg_loss:.0f}。"
        else:
            rt_summary = "无交易记录。"

        prompt = f"""You are an A-share backtest attribution analysis expert. Perform a deep \
attribution analysis on the following backtest results.

All text values in the JSON output must be in Chinese.

Stock: {symbol}
Strategy: {strategy_name}

Performance overview:
- Total return: {metrics.get("total_return", 0):.2%}
- Sharpe ratio: {metrics.get("sharpe_ratio", 0):.4f}
- Max drawdown: {metrics.get("max_drawdown", 0):.2%}
- Win rate: {metrics.get("win_rate", 0):.2%}

Trade overview: {rt_summary}

Recent trades (last 5):
{json.dumps(round_trips[-5:], ensure_ascii=False, default=str) if round_trips else "None"}

Return JSON only, no other content:
{{
  "summary": "归因分析总结(2-3句话)",
  "key_findings": ["关键发现1", "关键发现2", ...],
  "win_factors": ["盈利因素1", ...],
  "loss_factors": ["亏损因素1", ...],
  "improvement_suggestions": ["优化建议1", ...],
  "risk_assessment": "风险评估(1-2句话)"
}}"""

        try:
            router = get_llm_gateway()
            response = router.complete(
                messages=[{"role": "user", "content": prompt}],
                caller="strategy_lab.analyze_attribution",
                max_tokens=1536,
                temperature=0.3,
                symbol=symbol,
                analysis_type="backtest_attribution",
            )

            content = response.content.strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            parsed = json.loads(content)
            return {
                "status": "success",
                "summary": parsed.get("summary", ""),
                "key_findings": parsed.get("key_findings", []),
                "win_factors": parsed.get("win_factors", []),
                "loss_factors": parsed.get("loss_factors", []),
                "improvement_suggestions": parsed.get("improvement_suggestions", []),
                "risk_assessment": parsed.get("risk_assessment", ""),
            }
        except Exception as exc:
            logger.error("Attribution analysis failed: %s", exc)
            return {"status": "error", "message": f"归因分析失败: {exc}"}
