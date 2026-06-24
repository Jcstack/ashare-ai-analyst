"""Real-time AI stock analyzer combining live data, news, and anomalies.

Provides comprehensive and quick AI analysis by combining real-time quotes,
recent news, anomaly data, and technical indicators into structured prompts.

Per PRD v2.0 FR-AI001/AI002/AI003.
"""

import json
import re
import time
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError, LLMResponse
from src.llm.router import LLMRouter, RoutingStrategy
from src.utils.config import load_config
from src.utils.logger import get_logger
from src.utils.market_hours import format_session_for_prompt, get_market_session

# Type alias: accepts either LLMRouter or LLMGateway (duck-typed)
_LLMBackend = Any

logger = get_logger("prediction.realtime_analyzer")


class RealtimeAnalyzer:
    """AI-powered real-time stock analyzer.

    Combines live quote data, news, anomalies, and technical indicators
    to produce comprehensive or quick AI analysis.

    Args:
        router: LLM router instance for API calls.
        config_name: Config file name for agent settings.
    """

    def __init__(
        self,
        router: _LLMBackend | None = None,
        config_name: str = "agent",
        cache: Any | None = None,
    ) -> None:
        config = load_config(config_name)
        ai_cfg = config.get("ai_analysis", {})
        self._quick_cache_ttl: float = float(ai_cfg.get("quick_cache_ttl_seconds", 300))
        self._deep_cache_ttl: float = float(ai_cfg.get("deep_cache_ttl_seconds", 1800))
        self._max_tokens_quick: int = ai_cfg.get("max_tokens_quick", 512)
        self._max_tokens_deep: int = ai_cfg.get("max_tokens_deep", 4096)
        self._temperature: float = ai_cfg.get("temperature", 0.3)
        self._router = router or LLMRouter()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._llm_cache = cache  # LLMResultCache (L1+L2) or None
        # Detect if router is an LLMGateway (supports caller= kwarg)
        self._has_caller = hasattr(self._router, "_audit_log")

    def _complete(self, caller: str, **kwargs: Any) -> LLMResponse:
        """Call the router/gateway's complete(), adding caller if gateway."""
        if self._has_caller:
            return self._router.complete(caller=caller, **kwargs)
        return self._router.complete(**kwargs)

    def analyze_stock_realtime(
        self,
        symbol: str,
        quote: dict[str, Any] | None = None,
        news_items: list[dict[str, Any]] | None = None,
        anomalies: list[dict[str, Any]] | None = None,
        indicators: dict[str, Any] | None = None,
        force_refresh: bool = False,
        strategy_signals: dict[str, Any] | None = None,
        bayesian_analysis: dict[str, Any] | None = None,
        board_type: str = "",
        price_limit: str = "",
        data_quality_score: int = 100,
        data_warnings: list[str] | None = None,
        intraday_trades: dict[str, Any] | None = None,
        sector_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform comprehensive AI analysis combining all available data.

        Args:
            symbol: 6-digit stock code.
            quote: Real-time quote dict (price, change, volume, etc.).
            news_items: Recent news items for the stock.
            anomalies: Recent anomaly/unusual activity data.
            indicators: Technical indicator values.
            force_refresh: If True, bypass cache.
            strategy_signals: Multi-strategy signal context.
            bayesian_analysis: Bayesian probability analysis.
            board_type: Board classification (e.g. "沪市主板").
            price_limit: Price limit string (e.g. "±10%").
            data_quality_score: Data quality score 0-100.
            data_warnings: Data quality warnings.
            intraday_trades: Intraday tick stats and recent ticks.

        Returns:
            Analysis result dict with trend, signal, confidence, reasoning, etc.
        """
        from src.prediction.analysis_frameworks import (
            CONFIDENCE_GRADING_TABLE,
            DATA_INJECTION_RULES,
            RISK_ACTION_MATRIX,
            ROLE_DEFINITIONS,
            SEVEN_DIMENSION_FRAMEWORK,
            format_bayesian_context,
            format_board_constraint,
            format_data_quality_section,
            format_strategy_signals,
        )

        cache_key = f"deep_{symbol}"
        if not force_refresh:
            cached = self._get_cached(cache_key, self._deep_cache_ttl)
            if cached is not None:
                return cached

        from src.prediction.prompts import REALTIME_ANALYSIS_TEMPLATE

        prompt_text = REALTIME_ANALYSIS_TEMPLATE.format(
            symbol=symbol,
            quote_info=self._format_quote(quote),
            concept_info=self._format_concept_info(sector_info),
            news_info=self._format_news(news_items),
            anomaly_info=self._format_anomalies(anomalies),
            indicators_info=self._format_indicators(indicators),
            intraday_trades_info=self._format_intraday_trades(intraday_trades),
            strategy_signals_info=format_strategy_signals(strategy_signals or {}),
            bayesian_info=format_bayesian_context(bayesian_analysis or {}),
        )

        session = get_market_session()
        session_context = format_session_for_prompt(session)

        board_constraint = (
            format_board_constraint(board_type, price_limit) if board_type else ""
        )
        data_quality_section = format_data_quality_section(
            data_quality_score, data_warnings or []
        )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"{ROLE_DEFINITIONS['unified']}\n\n"
                    f"{SEVEN_DIMENSION_FRAMEWORK}\n\n"
                    f"{CONFIDENCE_GRADING_TABLE}\n\n"
                    f"{RISK_ACTION_MATRIX}\n\n"
                    f"{DATA_INJECTION_RULES}\n\n"
                    f"{board_constraint}\n\n"
                    "Adjust analysis emphasis based on the current market session and "
                    "the prediction target time window. The 'prediction target' in the "
                    "user message specifies the exact session you should predict.\n\n"
                    f"{data_quality_section}\n\n"
                    "**Key constraints**:\n"
                    "- All numbers (prices, change %, capital flow) MUST be cited from "
                    "injected system data — do NOT fabricate any figures\n"
                    "- target_price_range MUST be derived from current price and "
                    "technical levels — do NOT invent values\n"
                    "- data_references MUST contain >= 3 entries, each citing a specific "
                    "value from the injected data\n\n"
                    "Write all output text in Chinese.\n"
                    "Output STRICTLY in the following JSON format with no extra text.\n\n"
                    "```json\n"
                    "{\n"
                    '  "trend": "bullish | bearish | neutral",\n'
                    '  "signal": "buy | sell | hold | watch",\n'
                    '  "confidence": 0.0 ~ 1.0,\n'
                    '  "risk_level": "low | medium | high",\n'
                    '  "reasoning": ["分析要点1", "分析要点2", ...],\n'
                    '  "target_price_range": {"low": 0.00, "high": 0.00, "rationale": "基于XX技术位"},\n'
                    '  "key_factors": ["因素1", "因素2"],\n'
                    '  "risk_warnings": ["风险1", "风险2"],\n'
                    '  "news_sentiment": "positive | negative | neutral | mixed",\n'
                    '  "data_references": [{"field": "指标名", "value": "数值", "source": "来源"}]\n'
                    "}\n"
                    "```"
                ),
            ),
            LLMMessage(
                role="user",
                content=f"### 当前市场时段\n{session_context}\n\n{prompt_text}",
            ),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.deep",
                messages=messages,
                strategy=RoutingStrategy.QUALITY,
                max_tokens=self._max_tokens_deep,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="realtime_deep",
            )
            result = self._parse_response(response.text, symbol)
            result["model_used"] = response.model
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._set_cached(cache_key, result, ttl=int(self._deep_cache_ttl))
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Deep analysis failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "message": str(exc),
            }

    def get_quick_insight(
        self,
        symbol: str,
        quote: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        strategy_signals: dict[str, Any] | None = None,
        board_type: str = "",
        price_limit: str = "",
        sector_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get a quick one-liner AI insight (cheap model, cached 5min).

        Args:
            symbol: 6-digit stock code.
            quote: Real-time quote dict.
            indicators: Technical indicator values.
            strategy_signals: Multi-strategy signal context.
            board_type: Board classification.
            price_limit: Price limit string.
            sector_info: Concept sector data (concepts, resonance, industry).

        Returns:
            Quick insight dict with signal, confidence, summary.
        """
        from src.prediction.analysis_frameworks import (
            QUICK_DIMENSION_FRAMEWORK,
            ROLE_DEFINITIONS,
        )

        cache_key = f"quick_{symbol}"
        cached = self._get_cached(cache_key, self._quick_cache_ttl)
        if cached is not None:
            return cached

        from src.prediction.prompts import QUICK_INSIGHT_TEMPLATE

        # Append strategy consensus to quick insight
        strategy_summary = ""
        if strategy_signals:
            consensus = strategy_signals.get("consensus", {})
            if consensus:
                strategy_summary = f"\n策略共识: {consensus.get('note', '无')}"

        # Append sector info summary
        sector_summary = ""
        if sector_info:
            concepts = sector_info.get("concepts", [])
            resonance = sector_info.get("resonance", {})
            if concepts:
                top3 = sorted(
                    concepts, key=lambda c: abs(c.get("pct_change", 0)), reverse=True
                )[:3]
                names = ", ".join(
                    f"{c.get('name', '')}({c.get('pct_change', 0):+.1f}%)" for c in top3
                )
                sector_summary = f"\n概念板块: {names}"
            level = resonance.get("level", "none")
            if level != "none":
                sector_summary += f" [共振:{level}]"

        prompt_text = QUICK_INSIGHT_TEMPLATE.format(
            symbol=symbol,
            quote_info=self._format_quote(quote),
            indicators_info=self._format_indicators(indicators),
            strategy_consensus=strategy_summary + sector_summary,
        )

        session = get_market_session()
        session_label = session["label"]

        board_note = (
            f"This stock belongs to {board_type} ({price_limit})." if board_type else ""
        )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"{ROLE_DEFINITIONS['quick_insight']}\n\n"
                    f"{QUICK_DIMENSION_FRAMEWORK}\n"
                    f"Current session: {session_label}. {board_note}\n"
                    "Provide a one-sentence investment signal with reasoning. "
                    "You MUST cite at least one specific data value.\n"
                    "Write all output text in Chinese.\n"
                    "Output STRICTLY in the following JSON format:\n"
                    '{"signal": "bullish|bearish|neutral", "confidence": 0.0~1.0, '
                    '"summary": "一句话总结(含具体数值)", "risk_badge": "low|medium|high", '
                    '"confidence_label": "置信度标签", "key_data": "引用的关键数据点"}'
                ),
            ),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.quick",
                messages=messages,
                strategy=RoutingStrategy.COST,
                max_tokens=self._max_tokens_quick,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="quick_insight",
            )
            result = self._parse_quick_response(response.text, symbol)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._set_cached(cache_key, result, ttl=int(self._quick_cache_ttl))
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Quick insight failed for %s: %s", symbol, exc)
            return {
                "symbol": symbol,
                "signal": "neutral",
                "confidence": 0.0,
                "summary": "分析暂时不可用",
                "risk_badge": "medium",
            }

    def get_market_overview(
        self,
        indices_data: dict[str, Any] | None = None,
        hot_stocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate market-level AI morning briefing.

        Args:
            indices_data: Market index data.
            hot_stocks: Hot stock ranking data.

        Returns:
            Market overview dict.
        """
        cache_key = "market_overview"
        cached = self._get_cached(cache_key, 3600)  # 1 hour cache
        if cached is not None:
            return cached

        from src.prediction.prompts import MARKET_BRIEFING_TEMPLATE

        prompt_text = MARKET_BRIEFING_TEMPLATE.format(
            indices_info=json.dumps(
                indices_data or {}, ensure_ascii=False, default=str
            ),
            hot_stocks_info=json.dumps(
                hot_stocks[:10] if hot_stocks else [], ensure_ascii=False, default=str
            ),
        )

        session = get_market_session()
        session_context = format_session_for_prompt(session)

        from src.prediction.analysis_frameworks import QUICK_DIMENSION_FRAMEWORK

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are an A-share market analyst. Generate a daily market overview.\n\n"
                    f"{QUICK_DIMENSION_FRAMEWORK}\n\n"
                    "Adjust analysis content and wording based on the current market session.\n"
                    "Write all output text in Chinese.\n"
                    "Output STRICTLY in the following JSON format:\n"
                    "```json\n"
                    "{\n"
                    '  "market_trend": "bullish | bearish | neutral",\n'
                    '  "risk_assessment": "low | medium | high",\n'
                    '  "summary": "一段话概览",\n'
                    '  "key_points": ["要点1", "要点2"],\n'
                    '  "sector_outlook": {"leading": ["板块1"], "lagging": ["板块2"]}\n'
                    "}\n"
                    "```"
                ),
            ),
            LLMMessage(
                role="user",
                content=f"### 当前市场时段\n{session_context}\n\n{prompt_text}",
            ),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.market_overview",
                messages=messages,
                strategy=RoutingStrategy.COST,
                max_tokens=2048,
                temperature=self._temperature,
                analysis_type="market_overview",
            )
            result = self._parse_market_response(response.text)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._set_cached(cache_key, result, ttl=3600)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Market overview failed: %s", exc)
            return {
                "status": "error",
                "market_trend": "neutral",
                "risk_assessment": "medium",
                "summary": "市场概览暂时不可用",
                "key_points": [],
                "sector_outlook": None,
            }

    def analyze_dragon_tiger(
        self,
        symbol: str,
        name: str = "",
        quote: dict[str, Any] | None = None,
        seats: list[dict[str, Any]] | None = None,
        stats: list[dict[str, Any]] | None = None,
        indicators: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """AI analysis of dragon-tiger data for a specific stock.

        Per PRD v2.3 FR-DT002.

        Args:
            symbol: 6-digit stock code.
            name: Stock name.
            quote: Real-time quote dict.
            seats: Dragon-tiger seat details.
            stats: Dragon-tiger historical statistics.
            indicators: Technical indicator values.

        Returns:
            Structured dragon-tiger AI analysis result.
        """
        cache_key = f"dt_ai_{symbol}"
        cached = self._get_cached(cache_key, 1800)  # 30min cache
        if cached is not None:
            return cached

        # Format data for prompt
        seats_info = "无席位数据"
        if seats:
            lines = []
            for s in seats[:10]:
                seat_name = s.get("seat_name", "")
                seat_type = s.get("seat_type", "普通营业部")
                buy = s.get("buy_amount", 0)
                sell = s.get("sell_amount", 0)
                net = s.get("net_amount", 0)
                lines.append(f"[{seat_type}] {seat_name}: 买{buy}, 卖{sell}, 净{net}")
            seats_info = "\n".join(lines)

        stats_info = "无历史统计"
        if stats:
            row = stats[0] if stats else {}
            stats_info = json.dumps(row, ensure_ascii=False, default=str)

        prompt_text = (
            f"## 个股龙虎榜深度分析\n\n"
            f"股票: {name} ({symbol})\n"
            f"行情: {self._format_quote(quote)}\n"
            f"技术指标: {self._format_indicators(indicators)}\n\n"
            f"### 龙虎榜席位明细\n{seats_info}\n\n"
            f"### 历史统计\n{stats_info}\n"
        )

        session = get_market_session()
        session_label = session["label"]

        from src.prediction.analysis_frameworks import QUICK_DIMENSION_FRAMEWORK

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are an A-share 龙虎榜 (dragon-tiger list) analysis expert. "
                    "Analyze the stock's dragon-tiger seat composition, "
                    "institutional vs. hot-money (游资) activity, and historical statistics. "
                    f"Provide trading signals and risk warnings. Current session: {session_label}.\n\n"
                    f"{QUICK_DIMENSION_FRAMEWORK}\n\n"
                    "Write all output text in Chinese.\n"
                    "Output STRICTLY in the following JSON format:\n"
                    "```json\n"
                    "{\n"
                    '  "summary": "一句话总结",\n'
                    '  "signal": "bullish | bearish | neutral",\n'
                    '  "confidence": 0.0 ~ 1.0,\n'
                    '  "key_findings": ["发现1", "发现2"],\n'
                    '  "risk_factors": ["风险1"],\n'
                    '  "reasoning": ["推理1", "推理2"]\n'
                    "}\n"
                    "```"
                ),
            ),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.dragon_tiger",
                messages=messages,
                strategy=RoutingStrategy.QUALITY,
                max_tokens=2048,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="dragon_tiger_ai",
            )
            result = self._parse_response(response.text, symbol)
            result["status"] = "success"
            result["symbol"] = symbol
            result["model_used"] = response.model
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            # Add historical performance from stats
            if stats:
                row = stats[0]
                result["historical_performance"] = {
                    "appearances_3m": row.get("appearances", 0),
                    "institution_net_buy": row.get("net_amount", 0),
                    "avg_return_5d": 0.0,
                    "win_rate_5d": 0.0,
                }

            self._set_cached(cache_key, result, ttl=1800)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Dragon-tiger AI failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "summary": "龙虎榜AI分析暂时不可用",
                "signal": "neutral",
                "confidence": 0.0,
                "key_findings": [],
                "risk_factors": [],
                "reasoning": [],
                "message": str(exc),
            }

    def analyze_comprehensive_realtime(
        self,
        symbol: str,
        quote: dict[str, Any] | None = None,
        fund_flow: list[dict[str, Any]] | None = None,
        dragon_tiger: list[dict[str, Any]] | None = None,
        indicators: dict[str, Any] | None = None,
        strategy_signals: dict[str, Any] | None = None,
        bayesian_analysis: dict[str, Any] | None = None,
        board_type: str = "",
        price_limit: str = "",
        valuation: dict[str, Any] | None = None,
        fund_flow_detail: dict[str, Any] | None = None,
        fund_flow_timeline: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Comprehensive realtime analysis combining fund-flow, dragon-tiger,
        quotes, indicators, strategy signals, Bayesian probabilities, and
        valuation metrics.

        Uses COST routing strategy with 5-minute cache.

        Args:
            symbol: 6-digit stock code.
            quote: Real-time quote dict.
            fund_flow: Intraday fund flow records.
            dragon_tiger: Recent dragon-tiger records.
            indicators: Technical indicator values.
            strategy_signals: Multi-strategy signal context.
            bayesian_analysis: Bayesian probability analysis.
            board_type: Board classification.
            price_limit: Price limit string.
            valuation: Valuation indicator dict (PE/PB/PS/dividend/market cap).
            fund_flow_detail: Per-order-size inflow/outflow detail dict.
            fund_flow_timeline: Sampled intraday fund-flow time series.

        Returns:
            Comprehensive analysis dict with signal, summary, points, risks.
        """
        from src.prediction.analysis_frameworks import (
            QUICK_DIMENSION_FRAMEWORK,
            format_bayesian_context,
            format_board_constraint,
            format_fund_flow,
            format_fund_flow_detail,
            format_fund_flow_timeline,
            format_strategy_signals,
            format_valuation,
        )

        cache_key = f"comprehensive_{symbol}"
        cached = self._get_cached(cache_key, 300)  # 5min cache
        if cached is not None:
            return cached

        flow_info = format_fund_flow(fund_flow)

        detail_section = ""
        if fund_flow_detail:
            detail_section = f"\n\n### 资金流明细（分档）\n{format_fund_flow_detail(fund_flow_detail)}"

        timeline_section = ""
        timeline_text = format_fund_flow_timeline(fund_flow_timeline)
        if timeline_text:
            timeline_section = f"\n\n### 盘中资金流向时间线（实际采样数据，禁止编造未提供的时间点）\n{timeline_text}"

        dt_info = "无龙虎榜数据"
        if dragon_tiger:
            lines = []
            for row in dragon_tiger[:3]:
                date = row.get("日期", row.get("date", ""))
                reason = row.get("上榜原因", row.get("reason", ""))
                net = row.get("净买额", row.get("net_amount", 0))
                lines.append(f"[{date}] {reason}, 净买入: {net}")
            dt_info = "\n".join(lines)

        strategy_info = format_strategy_signals(strategy_signals or {})
        bayesian_info = format_bayesian_context(bayesian_analysis or {})
        valuation_info = format_valuation(valuation)

        prompt_text = (
            f"## 综合实时分析\n\n"
            f"股票: {symbol}\n"
            f"行情: {self._format_quote(quote)}\n"
            f"技术指标: {self._format_indicators(indicators)}\n\n"
            f"### 估值指标\n{valuation_info}\n\n"
            f"### 盘中资金流向\n{flow_info}\n\n"
            f"{detail_section}"
            f"{timeline_section}"
            f"### 近期龙虎榜\n{dt_info}\n\n"
            f"### 量化策略信号\n{strategy_info}\n\n"
            f"### 贝叶斯历史概率\n{bayesian_info}\n"
        )

        session = get_market_session()
        session_context = format_session_for_prompt(session)

        board_note = (
            format_board_constraint(board_type, price_limit) if board_type else ""
        )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are an A-share real-time comprehensive analyst. Synthesize "
                    "quotes, valuation metrics, capital flow, capital flow breakdown, "
                    "龙虎榜 (dragon-tiger list), technical indicators, quantitative "
                    "strategy signals, and Bayesian probabilities into a concise "
                    "comprehensive analysis.\n\n"
                    f"{QUICK_DIMENSION_FRAMEWORK}\n\n"
                    f"{board_note}\n"
                    "Adjust analysis emphasis based on the current market session.\n"
                    "Write all output text in Chinese.\n"
                    "Output STRICTLY in the following JSON format:\n"
                    "```json\n"
                    "{\n"
                    '  "signal": "bullish | bearish | neutral",\n'
                    '  "confidence": 0.0 ~ 1.0,\n'
                    '  "summary": "一句话综合判断",\n'
                    '  "points": ["分析要点1", "分析要点2", "分析要点3"],\n'
                    '  "risks": ["风险提示1", "风险提示2"]\n'
                    "}\n"
                    "```"
                ),
            ),
            LLMMessage(
                role="user",
                content=f"### 当前市场时段\n{session_context}\n\n{prompt_text}",
            ),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.comprehensive",
                messages=messages,
                strategy=RoutingStrategy.COST,
                max_tokens=1024,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="comprehensive_realtime",
            )
            result = self._parse_response(response.text, symbol)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._set_cached(cache_key, result, ttl=300)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Comprehensive analysis failed for %s: %s", symbol, exc)
            return {
                "symbol": symbol,
                "signal": "neutral",
                "confidence": 0.0,
                "summary": "综合分析暂时不可用",
                "points": [],
                "risks": [],
            }

    def analyze_support_resistance(
        self,
        symbol: str,
        levels: list[dict[str, Any]],
        current_price: float,
        fund_flow: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """AI analysis of support/resistance levels with fund flow context.

        Per PRD v2.4 FR-SR002.

        Args:
            symbol: 6-digit stock code.
            levels: Support/resistance levels from technical analysis.
            current_price: Current stock price.
            fund_flow: Recent fund flow data (optional).

        Returns:
            Structured analysis dict with summary, advice, risk_warnings.
        """
        cache_key = f"sr_ai_{symbol}"
        cached = self._get_cached(cache_key, 1800)  # 30min cache
        if cached is not None:
            return cached

        # Format levels with distance
        level_lines = []
        for lv in levels:
            price = lv.get("level", 0)
            ltype = lv.get("type", "")
            touches = lv.get("touches", 0)
            distance_pct = ((current_price - price) / price * 100) if price else 0
            level_lines.append(
                f"[{ltype}] {price:.2f} (触及{touches}次, 距当前价{distance_pct:+.1f}%)"
            )
        levels_info = "\n".join(level_lines) if level_lines else "无支撑阻力数据"

        from src.prediction.analysis_frameworks import format_fund_flow as _fmt_ff

        flow_info = _fmt_ff(fund_flow)

        prompt_text = (
            f"## 支撑阻力分析\n\n"
            f"股票: {symbol}\n当前价: {current_price:.2f}\n\n"
            f"### 支撑/阻力位\n{levels_info}\n\n"
            f"### 资金流向\n{flow_info}\n"
        )

        session = get_market_session()
        session_label = session["label"]

        from src.prediction.analysis_frameworks import QUICK_DIMENSION_FRAMEWORK

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are an A-share technical analysis expert. Analyze the strength "
                    "of support/resistance levels and combine with capital flow data "
                    f"to provide actionable trading advice. Current session: {session_label}.\n\n"
                    f"{QUICK_DIMENSION_FRAMEWORK}\n\n"
                    "Write all output text in Chinese.\n"
                    "Output STRICTLY in the following JSON format:\n"
                    "```json\n"
                    "{\n"
                    '  "summary": "一段话概括",\n'
                    '  "key_levels": [{"price": 0.00, "type": "support|resistance", "strength": "strong|moderate|weak", "comment": "说明"}],\n'
                    '  "advice": "操作建议",\n'
                    '  "risk_warnings": ["风险1"]\n'
                    "}\n"
                    "```"
                ),
            ),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.support_resistance",
                messages=messages,
                strategy=RoutingStrategy.COST,
                max_tokens=1024,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="sr_analysis",
            )
            result = self._parse_response(response.text, symbol)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._set_cached(cache_key, result, ttl=1800)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("S/R analysis failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "summary": "支撑阻力分析暂时不可用",
                "key_levels": [],
                "advice": "",
                "risk_warnings": [],
                "message": str(exc),
            }

    def _format_quote(self, quote: dict[str, Any] | None) -> str:
        if not quote:
            return "无实时行情数据"
        parts = []
        if quote.get("price") is not None:
            parts.append(f"最新价: {quote['price']}")
        if quote.get("change") is not None:
            parts.append(f"涨跌额: {quote['change']}")
        if quote.get("pct_change") is not None:
            parts.append(f"涨跌幅: {quote['pct_change']}%")
        if quote.get("volume") is not None:
            parts.append(f"成交量: {quote['volume']}")
        if quote.get("open") is not None:
            parts.append(f"今开: {quote['open']}")
        if quote.get("high") is not None:
            parts.append(f"最高: {quote['high']}")
        if quote.get("low") is not None:
            parts.append(f"最低: {quote['low']}")
        return " | ".join(parts) if parts else "无实时行情数据"

    def _format_news(self, news_items: list[dict[str, Any]] | None) -> str:
        if not news_items:
            return "无近期新闻"
        lines = []
        for i, item in enumerate(news_items[:5], 1):
            title = item.get("title", "未知标题")
            dt = item.get("datetime", "")
            lines.append(f"{i}. [{dt}] {title}")
        return "\n".join(lines)

    def _format_anomalies(self, anomalies: list[dict[str, Any]] | None) -> str:
        if not anomalies:
            return "无异动信息"
        lines = []
        for item in anomalies[:5]:
            dt = item.get("datetime", "")
            desc = item.get("description", item.get("change_type", ""))
            lines.append(f"[{dt}] {desc}")
        return "\n".join(lines)

    def _format_indicators(self, indicators: dict[str, Any] | None) -> str:
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

    @staticmethod
    def _format_concept_info(sector_info: dict[str, Any] | None) -> str:
        """Format concept board info for the AI prompt."""
        if not sector_info:
            return "无概念板块数据"

        lines: list[str] = []
        industry = sector_info.get("industry", "")
        if industry:
            lines.append(f"行业: {industry}")

        concepts = sector_info.get("concepts", [])
        if not concepts:
            concept_names = sector_info.get("concept_names", [])
            if concept_names:
                lines.append(f"关联概念: {', '.join(concept_names)}")
            elif not lines:
                return "无概念板块数据"
            return "\n".join(lines)

        rising = []
        for c in concepts:
            name = c.get("name", "") if isinstance(c, dict) else str(c)
            pct = c.get("pct_change") if isinstance(c, dict) else None
            if pct is not None:
                prefix = "+" if pct > 0 else ""
                rising.append(f"{name}({prefix}{pct:.2f}%)")
            else:
                rising.append(name)
        lines.append(f"关联概念({len(concepts)}个): {', '.join(rising)}")

        # Count rising concepts for resonance hint
        hot = [
            c
            for c in concepts
            if isinstance(c, dict) and (c.get("pct_change") or 0) > 1.0
        ]
        if len(hot) >= 3:
            lines.append(f"概念共振: {len(hot)}个概念涨幅>1%，板块联动效应较强")

        return "\n".join(lines)

    @staticmethod
    def _format_intraday_trades(trades: dict[str, Any] | None) -> str:
        """Format intraday tick stats and recent ticks for AI prompt."""
        if not trades:
            return "无盘中买卖盘数据"

        stats = trades.get("stats", {})
        if not stats:
            return "无盘中买卖盘数据"

        is_historical = trades.get("is_historical", False)

        buy_ratio = stats.get("buy_ratio", 0)
        sell_ratio = stats.get("sell_ratio", 0)
        neutral_ratio = stats.get("neutral_ratio", 0)
        buy_vol = stats.get("buy_volume", 0)
        sell_vol = stats.get("sell_volume", 0)

        lines: list[str] = []
        if is_historical:
            lines.append("（以下为最近交易日数据，非实时）")
        lines.extend(
            [
                f"买盘占比: {buy_ratio * 100:.1f}% | "
                f"卖盘占比: {sell_ratio * 100:.1f}% | "
                f"中性: {neutral_ratio * 100:.1f}%",
                f"买盘成交量: {buy_vol} 手 | 卖盘成交量: {sell_vol} 手",
            ]
        )

        recent_ticks = trades.get("recent_ticks", [])
        if recent_ticks:
            tick_parts = []
            for tick in recent_ticks[:5]:
                t = tick.get("time", "")
                direction = tick.get("direction", "")
                price = tick.get("price", 0)
                vol = tick.get("volume", 0)
                tick_parts.append(f"[{t}] {direction} {price}×{vol}手")
            lines.append(f"近{len(tick_parts)}笔: {' | '.join(tick_parts)}")

        return "\n".join(lines)

    @staticmethod
    def _format_capital_flow(ctx: dict[str, Any] | None) -> str:
        """Format macro capital flow context for AI prompt."""
        if not ctx:
            return "无宏观资金面数据"

        lines: list[str] = []

        # Inject data limitation warnings first
        warnings = ctx.get("warnings", [])
        for w in warnings:
            lines.append(f"[数据说明] {w}")

        score = ctx.get("environment_score")
        signal = ctx.get("signal", "neutral")
        if score is not None:
            signal_label = {
                "bullish": "偏多",
                "bearish": "偏空",
                "neutral": "中性",
            }.get(signal, signal)
            lines.append(f"资金环境评分: {score} ({signal_label})")

        nb = ctx.get("northbound_net")
        if nb is not None:
            lines.append(f"北向资金今日净流入: {nb:.2f} 亿元")

        sb = ctx.get("southbound_net")
        if sb is not None:
            lines.append(f"南向资金今日净流入: {sb:.2f} 亿元")

        mg = ctx.get("margin_balance_change")
        if mg is not None:
            lines.append(f"融资余额变动: {mg:.2f} 亿元")

        etf = ctx.get("etf_net_flow")
        if etf is not None:
            lines.append(f"ETF净流入(机构): {etf:.2f} 亿元")

        return "\n".join(lines) if lines else "无宏观资金面数据"

    def _parse_response(self, text: str, symbol: str) -> dict[str, Any]:
        """Parse full analysis JSON response from LLM.

        Normalizes common LLM field-name deviations (e.g. ``market_trend``
        instead of ``signal``) to the canonical schema expected by the
        frontend: ``signal``, ``confidence``, ``summary``, ``points``,
        ``risks``.

        Post-parse enforcement (v7.0):
        - V04 (FR-PR007): high risk → action cannot be buy/add
        - V07 (FR-PR005): data_references empty → warning log
        - FR-PR010: disclaimer forced to STANDARD_DISCLAIMER
        """
        from src.prediction.analysis_frameworks import STANDARD_DISCLAIMER

        json_str = self._extract_json(text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse analysis response for %s", symbol)
            return {
                "status": "parse_error",
                "symbol": symbol,
                "raw_response": text[:500],
            }

        # --- Normalize field names ------------------------------------------
        # signal: LLM sometimes uses "market_trend", "trend", "direction"
        if "signal" not in data:
            for alt in ("market_trend", "trend", "direction", "outlook"):
                if alt in data:
                    data["signal"] = data.pop(alt)
                    break
            else:
                data["signal"] = "neutral"

        # Map Chinese / verbose signal values to canonical enum
        signal_map = {
            "看多": "bullish",
            "看涨": "bullish",
            "偏多": "bullish",
            "看空": "bearish",
            "看跌": "bearish",
            "偏空": "bearish",
            "中性": "neutral",
            "震荡": "neutral",
            "观望": "neutral",
        }
        raw_signal = str(data["signal"]).strip().lower()
        data["signal"] = signal_map.get(raw_signal, raw_signal)
        if data["signal"] not in ("bullish", "bearish", "neutral"):
            data["signal"] = "neutral"

        # confidence: may be missing or use alternative keys
        if "confidence" not in data:
            for alt in ("confidence_score", "score", "probability"):
                if alt in data:
                    data["confidence"] = data.pop(alt)
                    break
            else:
                data["confidence"] = 0.5
        # Ensure float in [0, 1]
        try:
            conf = float(data["confidence"])
            data["confidence"] = max(
                0.0, min(1.0, conf if conf <= 1.0 else conf / 100.0)
            )
        except (TypeError, ValueError):
            data["confidence"] = 0.5

        # summary: may use alternative keys
        if "summary" not in data:
            for alt in ("overview", "conclusion", "analysis"):
                if alt in data:
                    data["summary"] = data.pop(alt)
                    break
            else:
                data["summary"] = ""

        # points: may use "key_points", "analysis_points", "highlights"
        if "points" not in data:
            for alt in ("key_points", "analysis_points", "highlights", "key_factors"):
                if alt in data:
                    data["points"] = data.pop(alt)
                    break
            else:
                data["points"] = []
        if not isinstance(data["points"], list):
            data["points"] = [str(data["points"])] if data["points"] else []

        # risks: may use "risk_warnings", "risk_factors", "risk_assessment"
        if "risks" not in data:
            for alt in ("risk_warnings", "risk_factors", "risk_assessment", "warnings"):
                if alt in data:
                    val = data.pop(alt)
                    if isinstance(val, list):
                        data["risks"] = val
                    elif isinstance(val, str) and val:
                        data["risks"] = [val]
                    else:
                        data["risks"] = []
                    break
            else:
                data["risks"] = []
        if not isinstance(data["risks"], list):
            data["risks"] = [str(data["risks"])] if data["risks"] else []

        # --- V04 (FR-PR007): high risk → no buy/add ---
        risk_level = str(data.get("risk_level", "medium")).strip().lower()
        signal = str(data.get("signal", "neutral")).strip().lower()
        if risk_level == "high" and signal in ("buy", "add"):
            data["signal"] = "hold"
            logger.info("V04: high risk override signal buy/add → hold for %s", symbol)

        # --- V07 (FR-PR005): data_references insufficient → degrade confidence ---
        data_refs = data.get("data_references")
        if not data_refs or (isinstance(data_refs, list) and len(data_refs) < 2):
            logger.warning(
                "V07: data_references has < 2 entries for %s — possible hallucination",
                symbol,
            )
            data["confidence"] = min(data.get("confidence", 0.5), 0.4)

        # --- FR-PR010: force standard disclaimer ---
        data["disclaimer"] = STANDARD_DISCLAIMER

        data["status"] = "success"
        data["symbol"] = symbol
        return data

    def _parse_quick_response(self, text: str, symbol: str) -> dict[str, Any]:
        """Parse quick insight JSON response from LLM."""
        from src.prediction.analysis_frameworks import get_confidence_label

        json_str = self._extract_json(text)
        try:
            data = json.loads(json_str)
            data["symbol"] = symbol
            # Ensure confidence_label is present (FR-PR003)
            if "confidence_label" not in data:
                try:
                    conf = float(data.get("confidence", 0.5))
                    data["confidence_label"] = get_confidence_label(conf)
                except (TypeError, ValueError):
                    data["confidence_label"] = get_confidence_label(0.5)
            # Ensure key_data is present (FR-PR003)
            if "key_data" not in data:
                data["key_data"] = ""
            return data
        except json.JSONDecodeError:
            return {
                "symbol": symbol,
                "signal": "neutral",
                "confidence": 0.0,
                "summary": text[:100] if text else "解析失败",
                "risk_badge": "medium",
                "confidence_label": "极低(数据不足)",
                "key_data": "",
            }

    def _parse_market_response(self, text: str) -> dict[str, Any]:
        """Parse market overview JSON response from LLM.

        Normalizes field names and ensures all required fields are present
        for the ``MarketAIOverview`` schema.
        """
        json_str = self._extract_json(text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse market overview JSON")
            return {
                "status": "parse_error",
                "market_trend": "neutral",
                "risk_assessment": "medium",
                "summary": "市场概览解析失败，请稍后重试",
                "key_points": [],
                "sector_outlook": None,
            }

        # Normalize market_trend — LLM may use "trend", "signal", "outlook"
        if "market_trend" not in data:
            for alt in ("trend", "signal", "market_signal", "direction", "outlook"):
                if alt in data:
                    data["market_trend"] = data.pop(alt)
                    break
            else:
                data["market_trend"] = "neutral"

        # Map Chinese signal values to canonical enum
        trend_map = {
            "看多": "bullish",
            "看涨": "bullish",
            "偏多": "bullish",
            "看空": "bearish",
            "看跌": "bearish",
            "偏空": "bearish",
            "中性": "neutral",
            "震荡": "neutral",
            "观望": "neutral",
        }
        raw_trend = str(data["market_trend"]).strip().lower()
        data["market_trend"] = trend_map.get(raw_trend, raw_trend)
        if data["market_trend"] not in ("bullish", "bearish", "neutral"):
            data["market_trend"] = "neutral"

        # Normalize risk_assessment
        if "risk_assessment" not in data:
            for alt in ("risk_level", "risk", "risk_badge"):
                if alt in data:
                    data["risk_assessment"] = data.pop(alt)
                    break
            else:
                data["risk_assessment"] = "medium"
        if data["risk_assessment"] not in ("low", "medium", "high"):
            data["risk_assessment"] = "medium"

        # Ensure summary exists
        if "summary" not in data:
            for alt in ("overview", "conclusion", "analysis", "market_summary"):
                if alt in data:
                    data["summary"] = data.pop(alt)
                    break
            else:
                data["summary"] = ""

        # Ensure key_points is a list
        if "key_points" not in data:
            for alt in ("points", "highlights", "key_factors", "analysis_points"):
                if alt in data:
                    data["key_points"] = data.pop(alt)
                    break
            else:
                data["key_points"] = []
        if not isinstance(data["key_points"], list):
            data["key_points"] = [str(data["key_points"])] if data["key_points"] else []

        # Ensure sector_outlook structure
        if "sector_outlook" not in data:
            data["sector_outlook"] = None
        elif isinstance(data["sector_outlook"], dict):
            if "leading" not in data["sector_outlook"]:
                data["sector_outlook"]["leading"] = []
            if "lagging" not in data["sector_outlook"]:
                data["sector_outlook"]["lagging"] = []

        data["status"] = "success"
        return data

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from markdown code blocks or raw text.

        Handles common LLM output patterns:
        - JSON wrapped in ```json ... ``` code blocks
        - Raw JSON objects in the text
        - Truncated JSON from hitting max_tokens (attempts brace repair)
        """
        # Try to find JSON in code blocks first
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate

        # Try to find a JSON object directly — use brace-counting to find
        # the correct closing brace instead of greedy match.
        start = text.find("{")
        if start == -1:
            return text.strip()

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        # If we reach here, JSON is likely truncated (unclosed braces from
        # hitting max_tokens).  Attempt repair by closing open braces/brackets.
        truncated = text[start:]
        # Close any open strings
        if truncated.count('"') % 2 == 1:
            truncated += '"'
        # Close open brackets / braces
        for ch in reversed(truncated):
            if ch in "{}[]":
                break
        open_brackets = truncated.count("[") - truncated.count("]")
        open_braces = truncated.count("{") - truncated.count("}")
        truncated += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        return truncated

    def _get_cached(self, key: str, ttl: float) -> dict[str, Any] | None:
        # L1 in-process check
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < ttl:
                return data
        # L2 Redis check (backfills L1 on hit)
        if self._llm_cache is not None:
            l2 = self._llm_cache.get(key, ttl)
            if l2 is not None:
                self._cache[key] = (time.time(), l2)
                return l2
        return None

    def _set_cached(self, key: str, data: dict[str, Any], ttl: int = 0) -> None:
        self._cache[key] = (time.time(), data)
        if self._llm_cache is not None and ttl > 0:
            self._llm_cache.set(key, data, ttl)

    # ═══════════════════════════════════════════════════════════════════════
    # v7.0 / v8.0 Unified Analysis  (FR-PR001~010, FR-AS001)
    # ═══════════════════════════════════════════════════════════════════════

    def analyze_stock_unified(
        self,
        symbol: str,
        quote: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        news_items: list[dict[str, Any]] | None = None,
        anomalies: list[dict[str, Any]] | None = None,
        fund_flow: dict[str, Any] | list[dict[str, Any]] | None = None,
        strategy_signals: dict[str, Any] | None = None,
        bayesian_analysis: dict[str, Any] | None = None,
        board_type: str = "",
        price_limit: str = "",
        data_quality_score: int = 100,
        data_warnings: list[str] | None = None,
        sector_info: dict[str, Any] | None = None,
        news_context: list[dict[str, Any]] | None = None,
        global_context: dict[str, Any] | None = None,
        intraday_trades: dict[str, Any] | None = None,
        policy_context: str = "",
        intel_context: str | None = None,
        capital_flow_context: dict[str, Any] | None = None,
        support_resistance: list[dict[str, Any]] | None = None,
        dragon_tiger: list[dict[str, Any]] | None = None,
        fund_flow_detail: dict[str, Any] | None = None,
        fund_flow_timeline: list[dict[str, Any]] | None = None,
        divergence_signals: list[dict[str, Any]] | None = None,
        valuation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Unified seven-dimension AI analysis merging P01+P03.

        Combines comprehensive analysis and trading advice into a single
        LLM call with the v7.0 seven-dimension framework.

        Args:
            symbol: 6-digit stock code.
            quote: Real-time quote dict.
            indicators: Technical indicator values.
            news_items: Recent news items for the stock.
            anomalies: Recent anomaly/unusual activity data.
            fund_flow: Fund flow data (dict or list).
            strategy_signals: Multi-strategy signal context.
            bayesian_analysis: Bayesian probability analysis.
            board_type: Board classification.
            price_limit: Price limit string.
            data_quality_score: Data quality score 0-100.
            data_warnings: Data quality warnings.
            sector_info: Concept sector data.
            news_context: Matched news items from TrendNewsAggregator.
            global_context: Global market snapshot.
            intraday_trades: Intraday tick stats.
            intel_context: Pre-formatted intelligence hub context string.
            capital_flow_context: Macro capital flow data dict with keys:
                environment_score, signal, northbound_net, margin_balance_change,
                etf_net_flow. Fetched from MacroFlowFetcher.

        Returns:
            Unified analysis result dict with 7 dimensions, action, confidence, etc.
        """
        from src.prediction.analysis_frameworks import (
            ACTION_LABELS,
            CONFIDENCE_GRADING_TABLE,
            DATA_INJECTION_RULES,
            RISK_ACTION_MATRIX,
            ROLE_DEFINITIONS,
            SEVEN_DIMENSION_FRAMEWORK,
            STANDARD_DISCLAIMER,
            UNIFIED_OUTPUT_SCHEMA,
            compute_quant_signals,
            format_bayesian_context,
            format_board_constraint,
            format_data_quality_section,
            format_fund_flow,
            format_global_context,
            format_limit_constraint,
            format_news_context,
            format_quant_signals,
            format_sector_analysis_hint,
            format_sector_info,
            format_strategy_signals,
            format_support_resistance,
            format_dragon_tiger,
            format_fund_flow_detail,
            format_fund_flow_timeline,
            format_divergence_signals,
            format_valuation,
        )

        cache_key = f"unified_{symbol}"
        cached = self._get_cached(cache_key, self._deep_cache_ttl)
        if cached is not None:
            return cached

        # Pre-compute quant signals (FR-PR008)
        price = (quote or {}).get("price")
        precomputed_quant = compute_quant_signals(
            indicators,
            strategy_signals,
            bayesian_analysis,
            current_price=float(price) if price else None,
        )

        # Build system prompt
        board_constraint = (
            format_board_constraint(board_type, price_limit) if board_type else ""
        )
        data_quality_section = format_data_quality_section(
            data_quality_score, data_warnings or []
        )

        # P1-1: Sector-specific analysis hint
        industry = (sector_info or {}).get("industry", "")
        sector_hint = format_sector_analysis_hint(industry)

        # P1-5: Limit price (涨跌停) constraint
        limit_constraint = format_limit_constraint(quote, price_limit)

        system_content = (
            f"{ROLE_DEFINITIONS['unified']}\n\n"
            f"{SEVEN_DIMENSION_FRAMEWORK}\n\n"
            f"{CONFIDENCE_GRADING_TABLE}\n\n"
            f"{RISK_ACTION_MATRIX}\n\n"
            f"{DATA_INJECTION_RULES}\n\n"
            f"{board_constraint}\n\n"
            + (f"{limit_constraint}\n\n" if limit_constraint else "")
            + (f"{sector_hint}\n\n" if sector_hint else "")
            + f"{data_quality_section}\n\n"
            f"{UNIFIED_OUTPUT_SCHEMA}"
        )

        # Build user prompt with all data sections
        session = get_market_session()
        session_context = format_session_for_prompt(session)

        # Merge news: news_items (from AKShare) + news_context (from TrendNews)
        merged_news = news_context or []
        if not merged_news and news_items:
            merged_news = news_items

        user_sections = [
            f"### 当前市场时段\n{session_context}",
            f"\n### 股票代码\n{symbol}",
            f"\n### 实时行情\n{self._format_quote(quote)}",
            f"\n### 技术指标\n{self._format_indicators(indicators)}",
            f"\n### 资金流向\n{format_fund_flow(fund_flow)}",
            f"\n### 量化信号 (system pre-computed — cite these, do NOT recalculate)\n{format_quant_signals(precomputed_quant)}",
            f"\n### 贝叶斯分析\n{format_bayesian_context(bayesian_analysis or {})}",
            f"\n### 量化策略信号\n{format_strategy_signals(strategy_signals or {})}",
            f"\n### 估值指标\n{format_valuation(valuation)}",
            f"\n### 概念板块\n{format_sector_info(sector_info)}",
            f"\n### 新闻舆情\n{format_news_context(merged_news)}",
            f"\n### 全球市场\n{format_global_context(global_context)}",
            f"\n### 支撑与阻力位\n{format_support_resistance(support_resistance)}",
        ]

        if dragon_tiger:
            user_sections.append(
                f"\n### 龙虎榜数据\n{format_dragon_tiger(dragon_tiger)}"
            )

        timeline_text = format_fund_flow_timeline(fund_flow_timeline)
        if timeline_text:
            user_sections.append(
                f"\n### 盘中资金流向时间线（实际采样数据，禁止编造未提供的时间点）\n{timeline_text}"
            )

        if fund_flow_detail:
            user_sections.append(
                f"\n### 资金流明细（分档）\n{format_fund_flow_detail(fund_flow_detail)}"
            )

        divergence_text = format_divergence_signals(divergence_signals)
        if divergence_text:
            user_sections.append(f"\n### 量价背离信号\n{divergence_text}")

        if policy_context:
            user_sections.append(f"\n### 政策与监管动态\n{policy_context}")

        if intraday_trades:
            user_sections.append(
                f"\n### 盘口数据\n{self._format_intraday_trades(intraday_trades)}"
            )

        if anomalies:
            user_sections.append(f"\n### 异动信息\n{self._format_anomalies(anomalies)}")

        if capital_flow_context:
            user_sections.append(
                f"\n### 宏观资金面\n{self._format_capital_flow(capital_flow_context)}"
            )

        if intel_context:
            user_sections.append(f"\n{intel_context}")

        user_content = "\n".join(user_sections)

        messages = [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=user_content),
        ]

        try:
            response = self._complete(
                "realtime_analyzer.unified",
                messages=messages,
                strategy=RoutingStrategy.QUALITY,
                max_tokens=self._max_tokens_deep,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="unified_analysis",
            )
            logger.info(
                "Unified LLM response for %s: model=%s tokens=%d/%d "
                "finish=%s text_len=%d text_preview=%.200s",
                symbol,
                response.model,
                response.input_tokens,
                response.output_tokens,
                getattr(response, "finish_reason", "?"),
                len(response.text) if response.text else 0,
                (response.text or "")[:200],
            )
            result = self._parse_unified_result(
                response.text,
                symbol,
                data_quality_score=data_quality_score,
                precomputed_quant=precomputed_quant,
                indicators=indicators,
            )
            result["model_used"] = response.model
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["disclaimer"] = STANDARD_DISCLAIMER
            result["status"] = "ok"
            result["symbol"] = symbol

            # P2-2: Non-trading hours confidence decay
            if not session.get("is_trading", False):
                action = str(result.get("action", "watch")).lower()
                if action in ("buy", "add", "sell", "reduce"):
                    conf = result.get("confidence")
                    if isinstance(conf, dict):
                        conf_val = float(conf.get("score", 0.5))
                    else:
                        conf_val = float(conf) if conf else 0.5
                    if conf_val > 0.65:
                        capped = 0.65
                        if isinstance(result.get("confidence"), dict):
                            result["confidence"]["score"] = capped
                        else:
                            result["confidence"] = capped
                        logger.info(
                            "Off-hours confidence cap: %.2f -> %.2f for %s (%s)",
                            conf_val,
                            capped,
                            symbol,
                            action,
                        )

            # Backward compat: action_label
            action = result.get("action", "watch")
            if "action_label" not in result or not result["action_label"]:
                result["action_label"] = ACTION_LABELS.get(action, "建议观望")

            self._set_cached(cache_key, result, ttl=int(self._deep_cache_ttl))
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Unified analysis failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "action": "watch",
                "action_label": "建议观望",
                "confidence": {"score": 0.0, "label": "极低(数据不足)", "basis": []},
                "risk_level": "high",
                "summary": "分析暂时不可用",
                "dimensions": [],
                "risk_warnings": [],
                "target_price": None,
                "stop_loss": None,
                "contrarian_check": "",
                "data_references": [],
                "disclaimer": STANDARD_DISCLAIMER,
                "message": str(exc),
                # backward compat
                "trend": "neutral",
                "signal": "neutral",
                "confidence_number": 0.0,
                "reasoning": [],
                "quant_signals": precomputed_quant,
                "ai_reasoning": [],
            }

    def _parse_unified_result(
        self,
        text: str,
        symbol: str,
        *,
        data_quality_score: int = 100,
        precomputed_quant: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Parse unified analysis JSON with V01-V10 validations.

        Uses the ValidationFramework for rule-based validation and auto-fix,
        then builds the full result dict with backward-compat fields.

        Args:
            text: Raw LLM response text.
            symbol: Stock symbol.
            data_quality_score: Data quality score for confidence clamping.
            precomputed_quant: System-computed quant signals.
            indicators: Technical indicator values for V10 consistency check.

        Returns:
            Validated and normalized result dict.
        """
        from src.prediction.analysis_frameworks import (
            ACTION_LABELS,
            STANDARD_DISCLAIMER,
            VALID_ACTIONS,
            get_confidence_label,
        )
        from src.web.services.validation_framework import ValidationFramework

        json_str = self._extract_json(text)

        # V06: 3-level JSON repair
        data: dict[str, Any] = {}
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Level 1: try extracting just the first { ... }
            try:
                start = text.find("{")
                if start >= 0:
                    data = json.loads(text[start:])
            except json.JSONDecodeError:
                # Level 2: return minimal valid result
                logger.warning("Failed to parse unified result for %s", symbol)
                data = {}

        # Attach precomputed_quant so V10 can inspect/fix tech_score
        if precomputed_quant:
            data["precomputed_quant"] = precomputed_quant

        # --- Run ValidationFramework (V01-V10) ---
        framework = ValidationFramework()
        validation_context = {
            "symbol": symbol,
            "data_quality_score": data_quality_score,
            "indicators": indicators or {},
        }
        validation_report = framework.validate(data, validation_context)

        # Extract validated action (framework may have mutated it)
        action = str(data.get("action", "watch")).strip().lower()
        if action not in VALID_ACTIONS:
            action = "watch"

        # Extract validated confidence
        raw_conf = data.get("confidence", 0.5)
        if isinstance(raw_conf, dict):
            conf_score = raw_conf.get("score", 0.5)
        else:
            conf_score = raw_conf
        try:
            conf_score = float(conf_score)
            conf_score = max(0.0, min(1.0, conf_score))
        except (TypeError, ValueError):
            conf_score = 0.5

        # --- risk_level normalization ---
        risk_level = str(data.get("risk_level", "medium")).strip().lower()
        if risk_level not in ("low", "medium", "high"):
            risk_level = "medium"
        # Data quality < 40 forces at least medium risk
        if data_quality_score < 40 and risk_level == "low":
            risk_level = "medium"

        # --- Confidence label ---
        conf_label = get_confidence_label(conf_score)
        conf_basis = []
        if isinstance(raw_conf, dict):
            conf_basis = raw_conf.get("basis", [])
        if not isinstance(conf_basis, list):
            conf_basis = [str(conf_basis)] if conf_basis else []

        # --- Dimensions normalization ---
        dimensions = data.get("dimensions", [])
        if not isinstance(dimensions, list):
            dimensions = []
        valid_signals = {"bullish", "neutral", "bearish"}
        for dim in dimensions:
            if not isinstance(dim, dict):
                continue
            sig = str(dim.get("signal", "neutral")).strip().lower()
            if sig not in valid_signals:
                dim["signal"] = "neutral"
            else:
                dim["signal"] = sig
            try:
                dim["score"] = max(0.0, min(1.0, float(dim.get("score", 0.5))))
            except (TypeError, ValueError):
                dim["score"] = 0.5

        # --- summary ---
        summary = str(data.get("summary", "")) or ""

        # --- risk_warnings normalization ---
        risk_warnings = data.get("risk_warnings", [])
        if not isinstance(risk_warnings, list):
            risk_warnings = (
                [{"type": "general", "description": str(risk_warnings)}]
                if risk_warnings
                else []
            )
        # Normalize string items to dict format
        normalized_warnings = []
        for w in risk_warnings:
            if isinstance(w, str):
                normalized_warnings.append({"type": "general", "description": w})
            elif isinstance(w, dict):
                normalized_warnings.append(w)
        risk_warnings = normalized_warnings

        # --- target_price ---
        target_price = data.get("target_price")
        if isinstance(target_price, dict):
            try:
                target_price = {
                    "low": float(target_price.get("low", 0)),
                    "high": float(target_price.get("high", 0)),
                }
            except (TypeError, ValueError):
                target_price = None
        else:
            target_price = None

        # --- stop_loss ---
        stop_loss = data.get("stop_loss")
        try:
            stop_loss = float(stop_loss) if stop_loss else None
        except (TypeError, ValueError):
            stop_loss = None

        # --- contrarian_check ---
        contrarian_check = str(data.get("contrarian_check", ""))

        # --- V07: data_references ---
        data_references = data.get("data_references", [])
        if not isinstance(data_references, list):
            data_references = []
        if not data_references:
            logger.warning(
                "Unified analysis for %s returned no data_references", symbol
            )

        # --- FR-PR010: force disclaimer ---
        disclaimer = STANDARD_DISCLAIMER

        # ===== Build result =====
        result: dict[str, Any] = {
            "action": action,
            "action_label": ACTION_LABELS.get(action, "建议观望"),
            "confidence": {
                "score": round(conf_score, 3),
                "label": conf_label,
                "basis": conf_basis,
            },
            "risk_level": risk_level,
            "summary": summary,
            "dimensions": dimensions,
            "risk_warnings": risk_warnings,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "contrarian_check": contrarian_check,
            "data_references": data_references,
            "disclaimer": disclaimer,
        }

        # ===== Backward compat fields =====
        # trend: derive from dimensions or action
        if dimensions:
            tech_dims = [d for d in dimensions if d.get("key") == "technical"]
            if tech_dims:
                result["trend"] = tech_dims[0].get("signal", "neutral")
            else:
                result["trend"] = (
                    "bullish"
                    if action in ("buy", "add")
                    else "bearish"
                    if action in ("sell", "reduce")
                    else "neutral"
                )
        else:
            result["trend"] = "neutral"

        result["signal"] = result["trend"]
        result["confidence_number"] = round(conf_score, 3)
        result["reasoning"] = [
            d.get("reasoning", "") for d in dimensions if d.get("reasoning")
        ]

        # FR-PR008: inject system-computed quant signals, not LLM output
        result["quant_signals"] = precomputed_quant or {}

        # ai_reasoning: extract from dimensions
        result["ai_reasoning"] = [
            f"{d.get('label', '')}: {d.get('reasoning', '')}"
            for d in dimensions
            if d.get("reasoning")
        ]

        # v14.0: Attach validation metadata
        result["validation"] = {
            "rules_passed": validation_report.rules_passed,
            "rules_failed": validation_report.rules_failed,
            "pass_rate": round(validation_report.pass_rate, 3),
        }

        return result
