"""AI Trading Advisor — dual-layer quantitative + AI operation recommendations.

Per PRD v3.2 FR-TA001 (stock buy/sell advice), FR-TA002 (watchlist position
strategy), FR-TA003 (portfolio add/reduce advice), FR-HS003 (holiday impact
assessment), FR-HS004 (pre-open briefing report).

Layer 1: Quantitative signal aggregation (technical score + strategy consensus
         + Bayesian probability).
Layer 2: AI judgment (incorporating sentiment, cross-market, holiday factors).

Output: action enum (buy/add/hold/reduce/sell/watch), confidence, reasoning,
risk warnings, target price, stop loss.
"""

import json
import time
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError
from src.llm.router import RoutingStrategy
from src.prediction.analysis_frameworks import STANDARD_DISCLAIMER
from src.prediction.realtime_analyzer import RealtimeAnalyzer
from src.utils.logger import get_logger

logger = get_logger("prediction.trading_advisor")

_VALID_ACTIONS = {"buy", "add", "hold", "reduce", "sell", "watch"}

_ACTION_LABELS = {
    "buy": "买入",
    "add": "加仓",
    "hold": "持有",
    "reduce": "减仓",
    "sell": "卖出",
    "watch": "观望",
}


def _build_advisor_system_prompt(board_type: str = "", price_limit: str = "") -> str:
    """Build v7.0-compliant advisor system prompt with framework injection."""
    from src.prediction.analysis_frameworks import (
        CONFIDENCE_GRADING_TABLE,
        DATA_INJECTION_RULES,
        RISK_ACTION_MATRIX,
        ROLE_DEFINITIONS,
        SEVEN_DIMENSION_FRAMEWORK,
        format_board_constraint,
    )

    board_constraint = (
        format_board_constraint(board_type, price_limit) if board_type else ""
    )

    return (
        f"{ROLE_DEFINITIONS['unified']}\n\n"
        f"{SEVEN_DIMENSION_FRAMEWORK}\n\n"
        f"{CONFIDENCE_GRADING_TABLE}\n\n"
        f"{RISK_ACTION_MATRIX}\n\n"
        f"{DATA_INJECTION_RULES}\n\n"
        f"{board_constraint}\n\n"
        "### Action enum\n"
        "- buy: recommend opening a new position\n"
        "- add: recommend adding to an existing position\n"
        "- hold: recommend holding and waiting\n"
        "- reduce: recommend reducing position\n"
        "- sell: recommend closing the entire position\n"
        "- watch: stay on the sidelines, wait for clearer signals\n\n"
        "**Key constraints**:\n"
        "- target_price low/high MUST be derived from injected quote data and "
        "technical levels — do NOT fabricate values\n"
        "- stop_loss MUST be < current price (long-only scenario), based on "
        "key support levels\n"
        "- All numbers (prices, change %, capital flow) MUST be cited directly "
        "from system-injected data — do NOT fabricate\n"
        "- data_references MUST contain >= 3 entries, each citing a specific "
        "value from the injected data\n\n"
        "Write all output text in Chinese.\n"
        "Output STRICTLY in the following JSON format with no extra text.\n\n"
        "```json\n"
        "{\n"
        '  "action": "buy | add | hold | reduce | sell | watch",\n'
        '  "confidence": 0.0 ~ 1.0,\n'
        '  "risk_level": "low | medium | high",\n'
        '  "ai_reasoning": ["推理要点1", "推理要点2", "推理要点3"],\n'
        '  "risk_warnings": ["风险提示1", "风险提示2"],\n'
        '  "target_price": {"low": 0.00, "high": 0.00, "rationale": "基于XX支撑/阻力位"},\n'
        '  "stop_loss": {"price": 0.00, "rationale": "基于XX支撑位或N%回撤"},\n'
        '  "contrarian_check": "当前判断可能失败的情景",\n'
        '  "data_references": [{"field": "指标名", "value": "数值", "source": "来源"}]\n'
        "}\n"
        "```"
    )


class TradingAdvisor:
    """AI Trading Advisor with dual-layer quant + AI recommendations.

    Args:
        router: LLM router/gateway instance for API calls.
    """

    def __init__(self, router: Any | None = None) -> None:
        if router is None:
            from src.web.dependencies import get_llm_gateway

            router = get_llm_gateway()
        self._router = router
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def advise_stock(
        self,
        symbol: str,
        *,
        quote: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        fund_flow: list[dict[str, Any]] | None = None,
        strategy_signals: dict[str, Any] | None = None,
        bayesian_analysis: dict[str, Any] | None = None,
        news_context: list[dict[str, Any]] | None = None,
        global_context: dict[str, Any] | None = None,
        board_type: str = "",
        price_limit: str = "",
        sector_info: dict[str, Any] | None = None,
        intel_signals: list[dict[str, Any]] | None = None,
        macro_signals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate operation advice for a single stock.

        Layer 1: Quantitative signal aggregation.
        Layer 2: AI judgment with full context.

        Args:
            symbol: 6-digit stock code.
            quote: Real-time quote data.
            indicators: Technical indicator values.
            fund_flow: Recent fund flow data.
            strategy_signals: Multi-strategy signal context.
            bayesian_analysis: Bayesian probability analysis.
            news_context: Matched news items for the stock.
            global_context: Global market snapshot.
            board_type: Board classification.
            price_limit: Price limit string.
            sector_info: Concept sector data (concepts, resonance, industry).
            intel_signals: Recent intel-sourced signals for this stock.
            macro_signals: Recent macro radar signals.

        Returns:
            Advice dict with action, confidence, reasoning, etc.
        """
        cache_key = f"advise_{symbol}"
        cached = self._get_cached(cache_key, 1800)  # 30min cache
        if cached is not None:
            return cached

        # Format context sections
        prompt_sections = [f"## 个股操作建议分析\n\n股票代码: {symbol}"]

        if board_type:
            prompt_sections.append(f"板块: {board_type} ({price_limit})")

        prompt_sections.append(f"\n### 实时行情\n{_format_quote(quote)}")
        prompt_sections.append(f"\n### 技术指标\n{_format_indicators(indicators)}")

        from src.prediction.analysis_frameworks import format_fund_flow

        prompt_sections.append(f"\n### 资金流向\n{format_fund_flow(fund_flow)}")

        if strategy_signals:
            from src.prediction.analysis_frameworks import format_strategy_signals

            prompt_sections.append(
                f"\n### 量化策略信号\n{format_strategy_signals(strategy_signals)}"
            )

        if bayesian_analysis:
            from src.prediction.analysis_frameworks import format_bayesian_context

            prompt_sections.append(
                f"\n### 贝叶斯历史概率\n{format_bayesian_context(bayesian_analysis)}"
            )

        if news_context:
            news_lines = []
            for item in news_context[:8]:
                title = item.get("title", "")
                platform = item.get("platform", "")
                heat = item.get("heat_score", 0)
                news_lines.append(f"[{platform}] {title} (热度: {heat:.2f})")
            prompt_sections.append("\n### 相关舆情\n" + "\n".join(news_lines))
        else:
            prompt_sections.append("\n### 相关舆情\n无匹配舆情")

        if global_context:
            indices = global_context.get("indices", [])
            if indices:
                idx_lines = []
                for idx in indices[:6]:
                    name = idx.get("name", "")
                    pct = idx.get("change_pct", 0)
                    idx_lines.append(f"{name}: {pct:+.2f}%")
                prompt_sections.append("\n### 全球市场概况\n" + " | ".join(idx_lines))

        if sector_info:
            prompt_sections.append(_format_sector_info(sector_info))

        # Inject intel and macro signal context from SignalBus
        if intel_signals:
            intel_lines = ["\n### 情报信号 (来自情报分析管线)"]
            for sig in intel_signals[:5]:
                intel_lines.append(
                    f"- {sig.get('summary', '')} "
                    f"(置信度: {sig.get('confidence', 0):.0f}%)"
                )
            prompt_sections.append("\n".join(intel_lines))

        if macro_signals:
            macro_lines = ["\n### 宏观雷达信号"]
            for sig in macro_signals[:5]:
                detail = sig.get("detail", sig.get("summary", ""))
                macro_lines.append(f"- {detail}")
            prompt_sections.append("\n".join(macro_lines))

        # FR-PR008: inject system-precomputed quant signals
        from src.prediction.analysis_frameworks import compute_quant_signals

        precomputed_quant = compute_quant_signals(
            indicators or {}, strategy_signals or {}, bayesian_analysis or {}
        )
        quant_lines = [
            "\n### 量化信号 (system pre-computed — cite these, do NOT recalculate)",
            f"技术评分: {precomputed_quant.get('technical_score', 'N/A')}",
            f"动量评分: {precomputed_quant.get('momentum_score', 'N/A')}",
            f"策略共识: {precomputed_quant.get('strategy_consensus', 'N/A')}",
            f"贝叶斯概率: {precomputed_quant.get('bayesian_probability', 'N/A')}",
        ]
        prompt_sections.append("\n".join(quant_lines))

        prompt_text = "\n".join(prompt_sections)

        system_prompt = _build_advisor_system_prompt(board_type, price_limit)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="trading_advisor.advise_stock",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=16384,
                temperature=0.3,
                symbol=symbol,
                analysis_type="trading_advisor",
            )
            current_price = float(quote.get("price", 0)) if quote else 0.0
            result = self._parse_advice(response.text, symbol, current_price)
            result["model_used"] = response.model
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["disclaimer"] = STANDARD_DISCLAIMER
            # FR-PR008: use system-precomputed quant_signals, not LLM-generated
            result["quant_signals"] = precomputed_quant
            self._set_cached(cache_key, result)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Trading advice failed for %s: %s", symbol, exc)
            return _error_result(symbol, str(exc))

    def advise_watchlist(
        self,
        symbols: list[str],
        *,
        stock_data: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate strategy report for a watchlist.

        Args:
            symbols: List of stock codes.
            stock_data: Per-symbol data dict with quote, indicators, etc.

        Returns:
            Watchlist strategy result with per-stock advice and ranking.
        """
        items = []
        for sym in symbols:
            data = stock_data.get(sym, {})
            advice = self.advise_stock(
                sym,
                quote=data.get("quote"),
                indicators=data.get("indicators"),
                fund_flow=data.get("fund_flow"),
                strategy_signals=data.get("strategy_signals"),
                bayesian_analysis=data.get("bayesian_analysis"),
                news_context=data.get("news_context"),
                global_context=data.get("global_context"),
                board_type=data.get("board_type", ""),
                price_limit=data.get("price_limit", ""),
                sector_info=data.get("sector_info"),
            )
            items.append(advice)

        # Sort by confidence descending, buy/add first
        action_priority = {
            "buy": 0,
            "add": 1,
            "hold": 2,
            "reduce": 3,
            "sell": 4,
            "watch": 5,
        }
        items.sort(
            key=lambda x: (
                action_priority.get(x.get("action", "watch"), 5),
                -(x.get("confidence", 0)),
            )
        )

        return {
            "status": "success",
            "items": items,
            "total": len(items),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "disclaimer": STANDARD_DISCLAIMER,
        }

    def advise_portfolio(
        self,
        positions: list[dict[str, Any]],
        *,
        stock_data: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate add/reduce/stop-loss advice for held positions.

        Args:
            positions: List of position dicts with symbol, cost_price, shares, etc.
            stock_data: Per-symbol data dict.

        Returns:
            Portfolio advice result with per-position recommendations.
        """
        position_advices = []

        for pos in positions:
            sym = pos.get("symbol", "")
            data = stock_data.get(sym, {})
            base_advice = self.advise_stock(
                sym,
                quote=data.get("quote"),
                indicators=data.get("indicators"),
                fund_flow=data.get("fund_flow"),
                strategy_signals=data.get("strategy_signals"),
                bayesian_analysis=data.get("bayesian_analysis"),
                news_context=data.get("news_context"),
                global_context=data.get("global_context"),
                board_type=data.get("board_type", ""),
                price_limit=data.get("price_limit", ""),
                sector_info=data.get("sector_info"),
            )

            # Enrich with position context
            cost_price = pos.get("cost_price", 0)
            current_price = (
                data.get("quote", {}).get("price", 0) if data.get("quote") else 0
            )
            pnl_pct = (
                ((current_price - cost_price) / cost_price * 100)
                if cost_price > 0
                else 0
            )

            base_advice["cost_price"] = cost_price
            base_advice["current_price"] = current_price
            base_advice["pnl_pct"] = round(pnl_pct, 2)
            base_advice["shares"] = pos.get("shares", 0)
            base_advice["holding_days"] = pos.get("holding_days", 0)

            position_advices.append(base_advice)

        return {
            "status": "success",
            "positions": position_advices,
            "total": len(position_advices),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "disclaimer": STANDARD_DISCLAIMER,
        }

    def assess_holiday_impact(
        self,
        symbol: str,
        *,
        position: dict[str, Any] | None = None,
        global_snapshot: dict[str, Any] | None = None,
        news_items: list[dict[str, Any]] | None = None,
        cross_market_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assess holiday impact on a held stock (FR-HS003).

        Args:
            symbol: 6-digit stock code.
            position: Position data (cost, shares, holding days).
            global_snapshot: Global market data during holiday.
            news_items: Matched news items during holiday.
            cross_market_data: Cross-market mapping for this stock.

        Returns:
            Holiday impact assessment with score and factors.
        """
        cache_key = f"holiday_{symbol}"
        cached = self._get_cached(cache_key, 7200)  # 2h cache
        if cached is not None:
            return cached

        prompt_sections = [
            f"## 假期持仓影响评估\n\n股票: {symbol}",
        ]

        if position:
            cost = position.get("cost_price", 0)
            shares = position.get("shares", 0)
            prompt_sections.append(f"持仓成本: {cost}, 持股: {shares}股")

        if global_snapshot:
            indices = global_snapshot.get("indices", [])
            if indices:
                lines = [
                    f"{idx.get('name', '')}: {idx.get('change_pct', 0):+.2f}%"
                    for idx in indices[:8]
                ]
                prompt_sections.append("\n### 假期全球市场表现\n" + " | ".join(lines))

            commodities = global_snapshot.get("commodities", [])
            if commodities:
                lines = [
                    f"{c.get('name', '')}: {c.get('change_pct', 0):+.2f}%"
                    for c in commodities[:5]
                ]
                prompt_sections.append("商品: " + " | ".join(lines))

        if news_items:
            titles = [item.get("title", "") for item in news_items[:10]]
            prompt_sections.append(
                "\n### 假期期间相关新闻\n" + "\n".join(f"- {t}" for t in titles)
            )

        if cross_market_data:
            peers = cross_market_data.get("us_peers", [])
            if peers:
                prompt_sections.append(f"海外同行: {', '.join(peers)}")
            tags = cross_market_data.get("tags", [])
            if tags:
                prompt_sections.append(f"行业标签: {', '.join(tags)}")

        prompt_text = "\n".join(prompt_sections)

        holiday_system = (
            "You are an A-share holiday position risk assessment expert. "
            "Based on global market movements during the holiday, relevant "
            "news sentiment, and cross-market correlations, assess the likely "
            "impact on held stocks when the market reopens after the holiday.\n\n"
            "Write all output text in Chinese.\n"
            "Output STRICTLY in the following JSON format:\n"
            "```json\n"
            "{\n"
            '  "impact_score": 0.0 ~ 1.0,\n'
            '  "impact_direction": "positive | negative | neutral",\n'
            '  "factors": [\n'
            '    {"name": "因子名", "impact": "positive | negative | neutral", '
            '"weight": 0.0~1.0, "description": "说明"}\n'
            "  ],\n"
            '  "ai_assessment": "综合评估文字",\n'
            '  "suggested_action": "hold | reduce | watch",\n'
            '  "confidence": 0.0 ~ 1.0\n'
            "}\n"
            "```"
        )

        messages = [
            LLMMessage(role="system", content=holiday_system),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="trading_advisor.assess_holiday_impact",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=16384,
                temperature=0.3,
                symbol=symbol,
                analysis_type="holiday_impact",
            )
            result = self._parse_holiday_impact(response.text, symbol)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["disclaimer"] = STANDARD_DISCLAIMER
            self._set_cached(cache_key, result)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Holiday impact failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "impact_score": 0.5,
                "impact_direction": "neutral",
                "factors": [],
                "ai_assessment": "假期影响评估暂时不可用",
                "suggested_action": "watch",
                "confidence": 0.0,
                "disclaimer": STANDARD_DISCLAIMER,
                "message": str(exc),
            }

    def generate_reopen_briefing(
        self,
        *,
        positions: list[dict[str, Any]] | None = None,
        watchlist: list[str] | None = None,
        global_snapshot: dict[str, Any] | None = None,
        news_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate pre-open comprehensive briefing (FR-HS004).

        Args:
            positions: User's held positions.
            watchlist: User's watchlist symbols.
            global_snapshot: Global market snapshot.
            news_context: Key news during holiday.

        Returns:
            Briefing report with market outlook, position impacts, recommendations.
        """
        cache_key = "reopen_briefing"
        cached = self._get_cached(cache_key, 3600)  # 1h cache
        if cached is not None:
            return cached

        prompt_sections = ["## 节后开盘研判报告"]

        if global_snapshot:
            indices = global_snapshot.get("indices", [])
            if indices:
                lines = [
                    f"{idx.get('name', '')}: {idx.get('change_pct', 0):+.2f}%"
                    for idx in indices
                ]
                prompt_sections.append("\n### 全球市场\n" + "\n".join(lines))

        if positions:
            pos_lines = [
                f"- {p.get('symbol', '')} ({p.get('name', '')}): "
                f"成本 {p.get('cost_price', 0)}, {p.get('shares', 0)}股"
                for p in positions[:20]
            ]
            prompt_sections.append("\n### 持仓列表\n" + "\n".join(pos_lines))

        if watchlist:
            prompt_sections.append("\n### 自选股\n" + ", ".join(watchlist[:20]))

        if news_context:
            titles = [item.get("title", "") for item in news_context[:15]]
            prompt_sections.append(
                "\n### 假期要闻\n" + "\n".join(f"- {t}" for t in titles)
            )

        prompt_text = "\n".join(prompt_sections)

        briefing_system = (
            "You are an A-share pre-open comprehensive research analyst. "
            "Based on global market performance during the holiday, key news, "
            "and user position data, generate a post-holiday market-open "
            "research briefing.\n\n"
            "Write all output text in Chinese.\n"
            "Output STRICTLY in the following JSON format:\n"
            "```json\n"
            "{\n"
            '  "market_outlook": "bullish | bearish | neutral",\n'
            '  "confidence": 0.0 ~ 1.0,\n'
            '  "summary": "一段话开盘展望",\n'
            '  "key_events": ["重要事件1", "重要事件2"],\n'
            '  "position_impacts": [\n'
            '    {"symbol": "代码", "impact": "positive | negative | neutral", '
            '"brief": "一句话影响说明"}\n'
            "  ],\n"
            '  "recommendations": ["建议1", "建议2"],\n'
            '  "risk_warnings": ["风险1", "风险2"]\n'
            "}\n"
            "```"
        )

        messages = [
            LLMMessage(role="system", content=briefing_system),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="trading_advisor.generate_reopen_briefing",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=16384,
                temperature=0.3,
                analysis_type="reopen_briefing",
            )
            result = self._parse_briefing(response.text)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["disclaimer"] = STANDARD_DISCLAIMER
            self._set_cached(cache_key, result)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Reopen briefing failed: %s", exc)
            return {
                "status": "error",
                "market_outlook": "neutral",
                "confidence": 0.0,
                "summary": "节后研判报告暂时不可用",
                "key_events": [],
                "position_impacts": [],
                "recommendations": [],
                "risk_warnings": [],
                "disclaimer": STANDARD_DISCLAIMER,
                "message": str(exc),
            }

    # --- Parsing helpers ---

    def _parse_advice(
        self, text: str, symbol: str, current_price: float = 0.0
    ) -> dict[str, Any]:
        """Parse stock advice JSON from LLM response."""
        json_str = RealtimeAnalyzer._extract_json(text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse advice for %s", symbol)
            return _error_result(symbol, "JSON parse error")

        # Normalize action
        action = str(data.get("action", "watch")).strip().lower()
        action_map = {
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
        action = action_map.get(action, action)
        if action not in _VALID_ACTIONS:
            action = "watch"

        # Normalize confidence
        try:
            confidence = float(data.get("confidence", 0.5))
            confidence = max(
                0.0, min(1.0, confidence if confidence <= 1.0 else confidence / 100.0)
            )
        except (TypeError, ValueError):
            confidence = 0.5

        # Apply confidence degradation rule
        if confidence < 0.3:
            action = "watch"
        elif confidence < 0.5 and action in ("buy", "sell", "add", "reduce"):
            action = "hold" if action in ("add", "hold") else "watch"

        # Normalize risk_level
        risk_level = str(data.get("risk_level", "medium")).strip().lower()
        if risk_level not in ("low", "medium", "high"):
            risk_level = "medium"

        # V04 (FR-PR007): high risk → no buy/add
        if risk_level == "high" and action in ("buy", "add"):
            action = "watch"

        # Normalize quant_signals
        quant = data.get("quant_signals", {})
        if not isinstance(quant, dict):
            quant = {}

        # Normalize list fields
        reasoning = data.get("ai_reasoning", [])
        if not isinstance(reasoning, list):
            reasoning = [str(reasoning)] if reasoning else []

        warnings = data.get("risk_warnings", [])
        if not isinstance(warnings, list):
            warnings = [str(warnings)] if warnings else []

        # Normalize target_price (supports both flat and nested formats)
        target_price = data.get("target_price")
        if isinstance(target_price, dict):
            try:
                target_price = {
                    "low": float(target_price.get("low", 0)),
                    "high": float(target_price.get("high", 0)),
                    "rationale": str(target_price.get("rationale", "")),
                }
            except (TypeError, ValueError):
                target_price = None
        else:
            target_price = None

        # Bounds validation: target_price must be within reasonable range of current price
        if target_price and current_price > 0:
            tp_low = target_price["low"]
            tp_high = target_price["high"]
            max_deviation = 0.30  # 30% max deviation from current price
            if (
                tp_low > 0
                and abs(tp_low - current_price) / current_price > max_deviation
            ):
                logger.warning(
                    "H03: target_price.low=%.2f deviates >30%% from current=%.2f for %s, nullifying",
                    tp_low,
                    current_price,
                    symbol,
                )
                target_price = None
            if (
                tp_high > 0
                and abs(tp_high - current_price) / current_price > max_deviation
            ):
                logger.warning(
                    "H03: target_price.high=%.2f deviates >30%% from current=%.2f for %s, nullifying",
                    tp_high,
                    current_price,
                    symbol,
                )
                target_price = None

        # Normalize stop_loss (supports both flat and nested formats)
        stop_loss_raw = data.get("stop_loss")
        if isinstance(stop_loss_raw, dict):
            try:
                stop_loss = float(stop_loss_raw.get("price", 0)) or None
            except (TypeError, ValueError):
                stop_loss = None
        else:
            try:
                stop_loss = float(stop_loss_raw) if stop_loss_raw else None
            except (TypeError, ValueError):
                stop_loss = None

        # Bounds validation: stop_loss must be < current_price (long-only)
        if stop_loss and current_price > 0 and stop_loss >= current_price:
            logger.warning(
                "H04: stop_loss=%.2f >= current_price=%.2f for %s — logically invalid, nullifying",
                stop_loss,
                current_price,
                symbol,
            )
            stop_loss = None

        # V07 (FR-PR005): data_references empty → warning + degrade confidence
        data_refs = data.get("data_references")
        if not data_refs or (isinstance(data_refs, list) and len(data_refs) < 2):
            logger.warning(
                "V07: data_references has < 2 entries for advisor %s — possible hallucination",
                symbol,
            )
            confidence = min(
                confidence, 0.4
            )  # Degrade confidence when data refs are insufficient

        # Normalize contrarian_check
        contrarian_check = str(data.get("contrarian_check", ""))

        # FR-PR010: force standard disclaimer
        return {
            "status": "success",
            "symbol": symbol,
            "action": action,
            "action_label": _ACTION_LABELS.get(action, "观望"),
            "confidence": round(confidence, 3),
            "risk_level": risk_level,
            "quant_signals": quant,
            "ai_reasoning": reasoning,
            "risk_warnings": warnings,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "contrarian_check": contrarian_check,
            "data_references": data_refs if isinstance(data_refs, list) else [],
            "disclaimer": STANDARD_DISCLAIMER,
        }

    def _parse_holiday_impact(self, text: str, symbol: str) -> dict[str, Any]:
        """Parse holiday impact JSON from LLM response."""
        json_str = RealtimeAnalyzer._extract_json(text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "status": "parse_error",
                "symbol": symbol,
                "impact_score": 0.5,
                "impact_direction": "neutral",
                "factors": [],
                "ai_assessment": "解析失败",
                "suggested_action": "watch",
                "confidence": 0.0,
            }

        # Normalize
        try:
            score = float(data.get("impact_score", 0.5))
            score = max(0.0, min(1.0, score))
        except (TypeError, ValueError):
            score = 0.5

        direction = str(data.get("impact_direction", "neutral")).strip().lower()
        if direction not in ("positive", "negative", "neutral"):
            direction = "neutral"

        factors = data.get("factors", [])
        if not isinstance(factors, list):
            factors = []

        suggested = str(data.get("suggested_action", "watch")).strip().lower()
        if suggested not in ("hold", "reduce", "watch"):
            suggested = "watch"

        try:
            conf = float(data.get("confidence", 0.5))
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.5

        return {
            "status": "success",
            "symbol": symbol,
            "impact_score": round(score, 3),
            "impact_direction": direction,
            "factors": factors,
            "ai_assessment": str(data.get("ai_assessment", "")),
            "suggested_action": suggested,
            "confidence": round(conf, 3),
        }

    def _parse_briefing(self, text: str) -> dict[str, Any]:
        """Parse reopen briefing JSON from LLM response."""
        json_str = RealtimeAnalyzer._extract_json(text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "status": "parse_error",
                "market_outlook": "neutral",
                "confidence": 0.0,
                "summary": "解析失败",
                "key_events": [],
                "position_impacts": [],
                "recommendations": [],
                "risk_warnings": [],
            }

        outlook = str(data.get("market_outlook", "neutral")).strip().lower()
        if outlook not in ("bullish", "bearish", "neutral"):
            outlook = "neutral"

        try:
            conf = float(data.get("confidence", 0.5))
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.5

        return {
            "status": "success",
            "market_outlook": outlook,
            "confidence": round(conf, 3),
            "summary": str(data.get("summary", "")),
            "key_events": data.get("key_events", [])
            if isinstance(data.get("key_events"), list)
            else [],
            "position_impacts": data.get("position_impacts", [])
            if isinstance(data.get("position_impacts"), list)
            else [],
            "recommendations": data.get("recommendations", [])
            if isinstance(data.get("recommendations"), list)
            else [],
            "risk_warnings": data.get("risk_warnings", [])
            if isinstance(data.get("risk_warnings"), list)
            else [],
        }

    def _get_cached(self, key: str, ttl: float) -> dict[str, Any] | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < ttl:
                return data
        return None

    def _set_cached(self, key: str, data: dict[str, Any]) -> None:
        self._cache[key] = (time.time(), data)


def _format_quote(quote: dict[str, Any] | None) -> str:
    if not quote:
        return "无行情数据（实时源和收盘价均不可用）"
    source_tag = "（收盘价）" if quote.get("_source") == "eod_fallback" else ""
    parts = []
    if quote.get("price") is not None:
        parts.append(f"最新价{source_tag}: {quote['price']}")
    if quote.get("pct_change") is not None:
        parts.append(f"涨跌幅: {quote['pct_change']}%")
    if quote.get("volume") is not None:
        parts.append(f"成交量: {quote['volume']}")
    if quote.get("high") is not None:
        parts.append(f"最高: {quote['high']}")
    if quote.get("low") is not None:
        parts.append(f"最低: {quote['low']}")
    return " | ".join(parts) if parts else "无行情数据"


def _format_indicators(indicators: dict[str, Any] | None) -> str:
    if not indicators:
        return "无技术指标数据"
    lines = []
    for name, value in indicators.items():
        if isinstance(value, dict):
            for sub, sub_val in value.items():
                lines.append(f"{name}.{sub}: {sub_val}")
        elif value is not None:
            lines.append(f"{name}: {value}")
    return "\n".join(lines)


def _format_sector_info(sector_info: dict[str, Any]) -> str:
    """Format concept sector info for prompt injection."""
    lines = ["\n### 概念板块"]
    industry = sector_info.get("industry", "")
    if industry:
        lines.append(f"行业: {industry}")

    concepts = sector_info.get("concepts", [])
    if concepts:
        lines.append(f"所属概念 (共 {len(concepts)} 个):")
        for c in concepts[:10]:
            name = c.get("name", "")
            pct = c.get("pct_change", 0)
            rank = c.get("stock_rank_pct")
            rank_str = f" (前{rank * 100:.0f}%)" if rank is not None else ""
            lines.append(f"  - {name}: {pct:+.2f}%{rank_str}")

    resonance = sector_info.get("resonance", {})
    level = resonance.get("level", "none")
    if level != "none":
        res_concepts = resonance.get("concepts", [])
        driver = resonance.get("top_driver", "")
        rank_in = resonance.get("rank_in_driver", "")
        lines.append(f"概念共振: {level}")
        if res_concepts:
            lines.append(f"  共振概念: {', '.join(res_concepts)}")
        if driver:
            lines.append(f"  主驱动板块: {driver}")
        if rank_in:
            lines.append(f"  个股在主驱动板块中: {rank_in}")

    return "\n".join(lines)


def _error_result(symbol: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "symbol": symbol,
        "action": "watch",
        "action_label": "观望",
        "confidence": 0.0,
        "risk_level": "high",
        "quant_signals": {},
        "ai_reasoning": [],
        "risk_warnings": ["分析暂时不可用"],
        "target_price": None,
        "stop_loss": None,
        "disclaimer": STANDARD_DISCLAIMER,
        "message": message,
    }
