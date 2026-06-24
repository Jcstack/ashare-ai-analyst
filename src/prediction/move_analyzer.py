"""Per-stock move (rise/fall) attribution analyzer.

Combines market indices, sector data, news, technical indicators, and optional
portfolio context to explain *why* a stock moved today.

Per PRD v2.2 FR-PI001/PI002.
"""

import json
import time
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError
from src.llm.router import RoutingStrategy
from src.utils.config import load_config
from src.utils.logger import get_logger
from src.utils.market_hours import format_session_for_prompt, get_market_session

logger = get_logger("prediction.move_analyzer")

MOVE_ANALYSIS_SYSTEM_PROMPT = """\
You are a professional A-share intelligent investment analyst. Your task is to \
explain **why a stock rose or fell** (based on the most recent trading day data), \
NOT to predict future price movements.

{analysis_framework}

{board_constraint}

Analysis rules:
1. Attribute the move across multiple dimensions: broad market, sector, \
news/events, technicals, capital flow, quantitative strategy signals, etc.
2. For each factor, provide impact (positive/negative/neutral) and weight \
(0~1, all factor weights should sum to approximately 1.0).
3. If quantitative strategy signals and Bayesian analysis are provided, \
you MUST incorporate them in the attribution.
4. If user position data is provided, give personalized advice and key price \
levels based on cost basis.
5. All analysis must be based on data that has already occurred — do NOT use \
future data.
6. **Do NOT fabricate numbers**: all values (change %, price, volume, capital \
flow) MUST be cited from the system-injected data — never invent figures.
7. **key_levels (support/resistance)** MUST be derived from injected technical \
indicators (MA, Bollinger Bands, prior highs/lows) — do NOT invent them.
8. **Pay attention to market session**:
   - Pre-market / call auction (集合竞价): quotes are from yesterday or auction \
data; focus on news and pre-market expectations
   - Intraday (morning/afternoon): quotes are real-time but incomplete; change % \
and volume are as-of-now values that may change
   - Midday break (午间休市): quotes reflect only morning trading; afternoon \
trend may differ
   - After close (收盘后): quotes are final full-day data; perform comprehensive \
attribution based on complete intraday data

{data_quality_section}

Write all output text in Chinese.
Output STRICTLY in the following JSON format with no extra text:

```json
{{
  "move_summary": "一句话概括涨跌原因",
  "factors": [
    {{
      "category": "market | sector | news | technical | flow | sentiment | strategy",
      "impact": "positive | negative | neutral",
      "weight": 0.0,
      "description": "具体描述"
    }}
  ],
  "position_context": {{
    "advice": "结合持仓成本的个性化建议",
    "key_levels": {{ "support": 0.00, "resistance": 0.00 }}
  }},
  "outlook": "短期展望（1-3个交易日）",
  "reasoning": ["推理步骤1", "推理步骤2"]
}}
```

Note: if no position data is provided, output position_context as null.
"""

MOVE_ANALYSIS_USER_TEMPLATE = """\
## 涨跌归因分析请求

### 股票: {name} ({symbol})
### 分析日期: {analysis_date}
### 板块: {board_type}（涨跌停限制: {price_limit}）

### 当前市场时段
{market_session}

### 所属板块
{sector_info}

### 个股实时行情
{quote_info}

### 大盘指数
{indices_info}

### 近期新闻
{news_info}

### 技术指标
{indicators_info}

### 异动信息
{anomaly_info}

### 资金流向
{fund_flow_info}

### 板块资金流对比
{sector_flow_info}

### 量化策略信号
{strategy_signals_info}

### 贝叶斯历史概率分析
{bayesian_info}

{position_section}

Based on the current market session, analyze the reasons for this stock's price \
movement (during non-trading hours, use the most recent trading day data). Pay \
special attention to sector/concept linkage effects and sector capital flow \
direction. Rank factors by weight from high to low.
"""


class MoveAnalyzer:
    """Analyzes the reasons behind a stock's price movement.

    Args:
        router: LLM router/gateway instance for API calls.
        config_name: Config file name for agent settings.
    """

    def __init__(
        self,
        router: Any | None = None,
        config_name: str = "agent",
    ) -> None:
        config = load_config(config_name)
        ai_cfg = config.get("ai_analysis", {})
        self._cache_ttl: float = float(ai_cfg.get("move_cache_ttl_seconds", 600))
        self._max_tokens: int = ai_cfg.get("max_tokens_deep", 4096)
        self._temperature: float = ai_cfg.get("temperature", 0.3)
        if router is None:
            from src.web.dependencies import get_llm_gateway

            router = get_llm_gateway()
        self._router = router
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def analyze_move(
        self,
        symbol: str,
        name: str = "",
        quote: dict[str, Any] | None = None,
        indices: list[dict[str, Any]] | None = None,
        news_items: list[dict[str, Any]] | None = None,
        anomalies: list[dict[str, Any]] | None = None,
        indicators: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
        sector_info: dict[str, Any] | None = None,
        fund_flow: list[dict[str, Any]] | None = None,
        strategy_signals: dict[str, Any] | None = None,
        bayesian_analysis: dict[str, Any] | None = None,
        board_type: str = "",
        price_limit: str = "",
        data_quality_score: int = 100,
        data_warnings: list[str] | None = None,
        sector_flow_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Analyze why a stock moved (up/down) today.

        Args:
            symbol: 6-digit stock code.
            name: Stock display name.
            quote: Real-time quote dict.
            indices: Market index data list.
            news_items: Recent news items.
            anomalies: Recent anomaly data.
            indicators: Technical indicator values.
            position: Optional portfolio position context
                      (cost_price, shares, holding_days).
            sector_info: Optional dict with 'industry' and 'concepts' keys.
            fund_flow: Intraday or historical fund flow data.
            strategy_signals: Multi-strategy signal context.
            bayesian_analysis: Bayesian probability analysis.
            board_type: Board classification (e.g. "沪市主板").
            price_limit: Price limit string (e.g. "±10%").
            data_quality_score: Data quality score 0-100.
            data_warnings: Data quality warnings.
            sector_flow_context: Sector-level capital flow data for the
                stock's industry, fetched from SectorFlowFetcher. Dict with
                keys: sector_name, net_inflow, change_pct.

        Returns:
            Move analysis dict with factors, reasoning, and optional position advice.
        """
        from src.prediction.analysis_frameworks import (
            SEVEN_DIMENSION_FRAMEWORK,
            format_bayesian_context,
            format_board_constraint,
            format_data_quality_section,
            format_strategy_signals,
        )

        has_position = position is not None and bool(position)
        cache_key = f"move_{symbol}_{has_position}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        position_section = ""
        if position:
            position_section = (
                "### 用户持仓信息\n"
                f"- 成本价: {position.get('cost_price', '未知')}\n"
                f"- 持仓数量: {position.get('shares', '未知')}股\n"
                f"- 持仓天数: {position.get('holding_days', '未知')}天\n"
                "\nProvide personalized advice and key price levels based on the position cost basis."
            )
        else:
            position_section = "（无持仓数据，position_context 输出 null）"

        import datetime

        session = get_market_session()

        # Format system prompt with framework and constraints
        board_constraint = (
            format_board_constraint(board_type, price_limit) if board_type else ""
        )
        data_quality_section = format_data_quality_section(
            data_quality_score, data_warnings or []
        )

        system_prompt = MOVE_ANALYSIS_SYSTEM_PROMPT.format(
            analysis_framework=SEVEN_DIMENSION_FRAMEWORK,
            board_constraint=board_constraint,
            data_quality_section=data_quality_section,
        )

        # Build sector flow context — fetch from SectorFlowFetcher if not provided
        sector_flow_text = self._format_sector_flow(sector_flow_context, sector_info)

        prompt_text = MOVE_ANALYSIS_USER_TEMPLATE.format(
            symbol=symbol,
            name=name or symbol,
            analysis_date=datetime.date.today().isoformat(),
            board_type=board_type or "未知",
            price_limit=price_limit or "未知",
            market_session=format_session_for_prompt(session),
            sector_info=self._format_sector(sector_info),
            quote_info=self._format_quote(quote),
            indices_info=self._format_indices(indices),
            news_info=self._format_news(news_items),
            indicators_info=self._format_indicators(indicators),
            anomaly_info=self._format_anomalies(anomalies),
            fund_flow_info=self._format_fund_flow(fund_flow),
            sector_flow_info=sector_flow_text,
            strategy_signals_info=format_strategy_signals(strategy_signals or {}),
            bayesian_info=format_bayesian_context(bayesian_analysis or {}),
            position_section=position_section,
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="move_analyzer.analyze_move",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                symbol=symbol,
                analysis_type="move_analysis",
            )
            result = self._parse_response(response.text, symbol, name, quote, position)
            result["model_used"] = response.model
            result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            result["market_session"] = session["label"]
            self._set_cached(cache_key, result)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Move analysis failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "name": name,
                "message": str(exc),
            }

    def _parse_response(
        self,
        text: str,
        symbol: str,
        name: str,
        quote: dict[str, Any] | None,
        position: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Parse LLM response into structured move analysis."""
        import re

        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        json_str = match.group(1).strip() if match else text.strip()
        if not json_str.startswith("{"):
            match2 = re.search(r"\{[\s\S]*\}", json_str)
            if match2:
                json_str = match2.group(0)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse move analysis for %s", symbol)
            data = {
                "move_summary": text[:200] if text else "解析失败",
                "factors": [],
                "reasoning": [],
            }

        pct_change = None
        if quote and quote.get("pct_change") is not None:
            pct_change = quote["pct_change"]

        import datetime

        result: dict[str, Any] = {
            "status": "success",
            "symbol": symbol,
            "name": name,
            "analysis_date": datetime.date.today().isoformat(),
            "price_change": pct_change,
            "move_summary": data.get("move_summary", ""),
            "factors": data.get("factors", []),
            "position_context": data.get("position_context"),
            "outlook": data.get("outlook", ""),
            "reasoning": data.get("reasoning", []),
        }

        # Inject position metadata if provided
        if position and result.get("position_context"):
            ctx = result["position_context"]
            ctx["cost_price"] = position.get("cost_price")
            ctx["current_price"] = quote.get("price") if quote else None
            ctx["pnl_percent"] = pct_change
            ctx["holding_days"] = position.get("holding_days")

        return result

    # ---- formatting helpers (reuse patterns from RealtimeAnalyzer) ----

    @staticmethod
    def _format_sector(sector_info: dict[str, Any] | None) -> str:
        if not sector_info:
            return "无板块数据"
        parts = []
        industry = sector_info.get("industry", "")
        if industry:
            parts.append(f"行业: {industry}")
        concepts = sector_info.get("concepts", [])
        if concepts:
            # concepts is a list of dicts with name/pct_change/code keys
            concept_strs = []
            for c in concepts[:8]:
                if isinstance(c, dict):
                    name = c.get("name", "")
                    pct = c.get("pct_change", 0)
                    concept_strs.append(f"{name}({pct:+.2f}%)")
                else:
                    concept_strs.append(str(c))
            parts.append(f"概念板块: {', '.join(concept_strs)}")
        elif sector_info.get("concept_names"):
            parts.append(f"概念板块: {', '.join(sector_info['concept_names'][:8])}")
        return "\n".join(parts) if parts else "无板块数据"

    @staticmethod
    def _format_quote(quote: dict[str, Any] | None) -> str:
        if not quote:
            return "无实时行情数据"
        parts = []
        for key, label in [
            ("price", "最新价"),
            ("change", "涨跌额"),
            ("pct_change", "涨跌幅"),
            ("volume", "成交量"),
            ("open", "今开"),
            ("high", "最高"),
            ("low", "最低"),
        ]:
            val = quote.get(key)
            if val is not None:
                suffix = "%" if key == "pct_change" else ""
                parts.append(f"{label}: {val}{suffix}")
        return " | ".join(parts) if parts else "无实时行情数据"

    @staticmethod
    def _format_indices(indices: list[dict[str, Any]] | None) -> str:
        if not indices:
            return "无大盘数据"
        lines = []
        for idx in indices:
            name = idx.get("name", "")
            pct = idx.get("pct_change", 0)
            price = idx.get("price", 0)
            lines.append(f"- {name}: {price} ({pct:+.2f}%)")
        return "\n".join(lines)

    @staticmethod
    def _format_news(news_items: list[dict[str, Any]] | None) -> str:
        if not news_items:
            return "无近期新闻"
        lines = []
        for i, item in enumerate(news_items[:5], 1):
            title = item.get("title", "未知标题")
            dt = item.get("datetime", "")
            lines.append(f"{i}. [{dt}] {title}")
        return "\n".join(lines)

    @staticmethod
    def _format_anomalies(anomalies: list[dict[str, Any]] | None) -> str:
        if not anomalies:
            return "无异动信息"
        lines = []
        for item in anomalies[:5]:
            dt = item.get("datetime", "")
            desc = item.get("description", item.get("change_type", ""))
            lines.append(f"[{dt}] {desc}")
        return "\n".join(lines)

    @staticmethod
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

    @staticmethod
    def _format_fund_flow(fund_flow: list[dict[str, Any]] | None) -> str:
        from src.prediction.analysis_frameworks import format_fund_flow

        return format_fund_flow(fund_flow)

    @staticmethod
    def _format_sector_flow(
        sector_flow_context: dict[str, Any] | None,
        sector_info: dict[str, Any] | None,
    ) -> str:
        """Format sector-level capital flow for the move analysis prompt.

        If explicit ``sector_flow_context`` is provided, use it directly.
        Otherwise, attempt to fetch the stock's industry sector flow from
        ``SectorFlowFetcher`` using ``sector_info.industry`` as lookup key.
        Gracefully returns a placeholder string when data is unavailable.
        """
        # Use pre-provided context if available
        if sector_flow_context:
            lines: list[str] = []
            name = sector_flow_context.get("sector_name", "")
            net = sector_flow_context.get("net_inflow")
            pct = sector_flow_context.get("change_pct")
            if name:
                lines.append(f"所属行业板块: {name}")
            if net is not None:
                direction = "净流入" if net >= 0 else "净流出"
                lines.append(f"板块主力资金: {direction} {abs(net):.2f} 亿元")
            if pct is not None:
                lines.append(f"板块涨跌幅: {pct:+.2f}%")
            return "\n".join(lines) if lines else "无板块资金流数据"

        # Attempt auto-fetch from SectorFlowFetcher
        industry = ""
        if sector_info:
            industry = sector_info.get("industry", "")
        if not industry:
            return "无板块资金流数据"

        try:
            from src.data.sector_flow_fetcher import SectorFlowFetcher

            fetcher = SectorFlowFetcher()
            df = fetcher.fetch_industry_flow(period="today")
            if df.empty or "sector_name" not in df.columns:
                return "无板块资金流数据"

            # Find matching industry row
            match = df[df["sector_name"].str.contains(industry, na=False)]
            if match.empty:
                return f"板块({industry})未找到资金流数据"

            row = match.iloc[0]
            net = float(row.get("net_inflow", 0) or 0)
            pct = float(row.get("change_pct", 0) or 0)
            direction = "净流入" if net >= 0 else "净流出"
            lines = [
                f"所属行业板块: {industry}",
                f"板块主力资金: {direction} {abs(net):.2f} 亿元",
                f"板块涨跌幅: {pct:+.2f}%",
            ]
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("Sector flow fetch failed for %s: %s", industry, exc)
            return "无板块资金流数据（获取异常）"

    def _get_cached(self, key: str) -> dict[str, Any] | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: dict[str, Any]) -> None:
        self._cache[key] = (time.time(), data)
