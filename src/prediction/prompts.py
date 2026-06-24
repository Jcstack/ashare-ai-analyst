"""Prompt engineering for the A-share prediction layer.

Builds structured prompt messages for the Claude API, formatting OHLCV data,
technical indicators, candlestick patterns, and support/resistance levels into
a comprehensive analysis request.

Per PRD FR-P001: Config-driven prompt construction with enforced output schema.

v52: Added context-driven PromptBuilderV2 and compressed templates.
"""

from typing import Any

import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("prediction.prompts")

# ============================================================================
# v52 Context-driven prompts (NEW)
# ============================================================================

DECISION_OUTPUT_SCHEMA = """\
```json
{{
  "action": "buy | sell | hold | reduce | watch | no_trade",
  "stock": "6-digit symbol code",
  "confidence": 0.0-1.0,
  "reasoning_chain": {{
    "base_rate_assessment": "该板块/股票历史胜率判断 + 是否偏离",
    "evidence_direction": "bullish | bearish | mixed",
    "key_evidence": ["最重要的2-3条证据，必须引用快照中的具体数值"],
    "conflicting_evidence": ["与结论矛盾的证据，如果没有写'无明显矛盾'"],
    "portfolio_fit": "对现有持仓集中度/风险的影响"
  }},
  "entry_range": {{"low": 0.00, "high": 0.00}},
  "stop_loss": {{"price": 0.00, "basis": "止损依据(支撑位/ATR/固定比例)"}},
  "target_price": {{"price": 0.00, "basis": "目标依据(压力位/估值/催化)"}},
  "position_size_pct": 0.0-30.0,
  "holding_period_days": 0,
  "invalidation": "立即退出的条件（具体价格或事件）",
  "contingency": "如果价格反向运动，应该怎么做"
}}
```

confidence 约束:
- 0.00-0.30: action 只能是 watch 或 no_trade
- 0.30-0.50: action 只能是 watch/hold/reduce
- 0.50-0.70: 所有 action 允许，但必须列出 conflicting_evidence
- 0.70-1.00: 所有 action 允许，必须确认 ≥3 条独立证据支持

如果数据不足以形成判断，必须输出:
{{"action": "no_trade", "confidence": 0.15, "reasoning_chain": {{"base_rate_assessment": "数据不足", "evidence_direction": "mixed", "key_evidence": [], "conflicting_evidence": ["数据缺失无法判断"], "portfolio_fit": "N/A"}}}}
"""

ANALYSIS_SYSTEM_PROMPT = """\
你是一个管理实盘A股组合的AI投资决策者。用户是执行交易员——你下指令，用户执行。

## 决策原则
1. 只使用快照中注入的数据。绝不编造数据。缺失标记"无数据"。
2. 区分事实与推断。事实=快照中的数值；推断=你的判断，必须标注置信度。
3. 每个买入决策必须回答：为什么买？为什么现在？优势在哪？风险是什么？仓位多少？何时退出？
4. 证据不足时降低 confidence，不要为凑高分而忽略矛盾信号。
5. 止损价必须低于现价（做多）。目标价必须基于技术位/估值。
6. 用散户能听懂的中文，不要使用 MACD/RSI/PE 等术语。

## 数据解读规则
- 资金流：正值=净流入（买方强于卖方），负值=净流出
- 量比：>1.5 放量，<0.7 缩量，1.0 为近20日均量
- 贝叶斯P(涨)：>0.60 偏多，<0.40 偏空，0.40-0.60 中性
- 收敛分数：衡量多少独立信号源方向一致，≥2源才能发出买入信号
- 情绪周期：冰点(极度悲观)→启动(开始回暖)→加速(赚钱效应扩散)→高潮(过热)→退潮(亏钱效应)

## 输出格式
严格输出以下 JSON:
{output_schema}
"""

ANALYSIS_USER_TEMPLATE = """\
## 市场快照（数据截止时间见快照头部）

{market_snapshot_text}

## 任务

基于上述完整市场快照，对 {stock_name}（{symbol}）做出投资决策。

要求：
1. 先评估基础胜率，再逐条检查证据
2. 如果持仓信息存在，必须考虑组合集中度影响
3. 如果存在矛盾证据，必须在 conflicting_evidence 中列出
4. 输出中文
"""

MACRO_SYSTEM_PROMPT = """\
你是A股组合经理，分析宏观事件对A股的传导效应。

## 分析框架
1. 识别事件性质：政策/地缘/货币/贸易/产业
2. 构建传导链：事件 → 一阶影响 → 二阶影响 → A股板块影响
3. 区分时间维度：短期冲击(1-3天) vs 中期趋势(1-4周)
4. 评估市场定价：该事件是否已被市场充分消化？

## 约束
- 只使用注入数据，缺失标记"无数据"
- 每条传导链必须标注置信度衰减（链越长置信度越低）
- 不要把相关性当因果性

输出 JSON:
```json
{{
  "signal": "bullish | bearish | neutral",
  "confidence": 0.0-1.0,
  "headline": "一句话概括（中文）",
  "transmission_chain": [
    {{"order": 1, "cause": "事件直接影响", "effect": "一阶市场反应", "confidence": 0.0-1.0}},
    {{"order": 2, "cause": "一阶反应", "effect": "二阶板块影响", "confidence": 0.0-1.0}}
  ],
  "sectors_bullish": [{{"sector": "板块名", "reason": "原因", "time_horizon": "短期|中期"}}],
  "sectors_bearish": [{{"sector": "板块名", "reason": "原因", "time_horizon": "短期|中期"}}],
  "risks": ["该判断可能错误的情形1", "情形2"],
  "already_priced_in": "已充分消化 | 部分消化 | 尚未反应",
  "data_sufficiency": "充分 | 一般 | 不足"
}}
```
"""

MACRO_USER_TEMPLATE = """\
## 宏观数据快照

{macro_snapshot_text}

## 全球市场数据

{global_data_text}

## 任务

分析以上宏观事件对A股市场和板块的传导效应。
要求：构建因果传导链（不少于2环），区分短期冲击和中期趋势，评估市场是否已定价。
输出中文。
"""

QUICK_DECISION_TEMPLATE = """\
{market_snapshot_text}

快速判断 {symbol}：
1. 方向：bullish/bearish/neutral（引用1条关键数据）
2. 信心：0.0-1.0
3. 风险：一句话
输出 JSON: {{"action": "{action_type}", "stock": "{symbol}", "confidence": 0.0-1.0, "reason": "一句话+数据引用", "risk": "一句话", "evidence_cited": "引用的具体数值"}}
"""


class PromptBuilderV2:
    """Context-driven prompt builder (v52).

    Replaces role-based prompts with context-based prompts.
    Expects pre-built MarketSnapshot text as input.
    """

    @staticmethod
    def build_decision_prompt(
        snapshot_text: str,
        stock_name: str,
        symbol: str,
    ) -> list[dict[str, str]]:
        """Build decision prompt from MarketSnapshot text.

        Args:
            snapshot_text: Pre-serialized market snapshot string from
                MarketSnapshot.serialize_for_llm().
            stock_name: Human-readable stock name.
            symbol: 6-digit stock code.

        Returns:
            List of message dicts with role and content keys.
        """
        system_content = ANALYSIS_SYSTEM_PROMPT.format(
            output_schema=DECISION_OUTPUT_SCHEMA
        )
        user_content = ANALYSIS_USER_TEMPLATE.format(
            market_snapshot_text=snapshot_text,
            stock_name=stock_name,
            symbol=symbol,
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        logger.debug(
            "PromptBuilderV2.build_decision_prompt %s: sys=%d user=%d chars",
            symbol,
            len(system_content),
            len(user_content),
        )
        return messages

    @staticmethod
    def build_quick_prompt(
        snapshot_text: str,
        symbol: str,
        action_type: str = "分析",
    ) -> list[dict[str, str]]:
        """Build compressed quick-decision prompt.

        Args:
            snapshot_text: Pre-serialized market snapshot string.
            symbol: 6-digit stock code.
            action_type: Action context string (e.g. "分析", "买入", "卖出").

        Returns:
            List of message dicts with role and content keys.
        """
        system_content = ANALYSIS_SYSTEM_PROMPT.format(
            output_schema=DECISION_OUTPUT_SCHEMA
        )
        user_content = QUICK_DECISION_TEMPLATE.format(
            market_snapshot_text=snapshot_text,
            symbol=symbol,
            action_type=action_type,
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        logger.debug(
            "PromptBuilderV2.build_quick_prompt %s: sys=%d user=%d chars",
            symbol,
            len(system_content),
            len(user_content),
        )
        return messages

    @staticmethod
    def build_macro_prompt(
        macro_snapshot_text: str,
        global_data_text: str,
    ) -> list[dict[str, str]]:
        """Build macro analysis prompt.

        Args:
            macro_snapshot_text: Pre-serialized macro event data.
            global_data_text: Pre-serialized global market data.

        Returns:
            List of message dicts with role and content keys.
        """
        system_content = MACRO_SYSTEM_PROMPT
        user_content = MACRO_USER_TEMPLATE.format(
            macro_snapshot_text=macro_snapshot_text,
            global_data_text=global_data_text,
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        logger.debug(
            "PromptBuilderV2.build_macro_prompt: sys=%d user=%d chars",
            len(system_content),
            len(user_content),
        )
        return messages


# ============================================================================
# DEPRECATED: Legacy prompts below — use ANALYSIS_* / PromptBuilderV2 instead
# ============================================================================

# DEPRECATED: use DECISION_OUTPUT_SCHEMA instead
_OUTPUT_SCHEMA_TEMPLATE = """\
You must output analysis results strictly in the following JSON format. Do not add any extra text.

```json
{{
  "trend": "bullish | bearish | neutral",
  "signal": "buy | sell | hold | watch",
  "confidence": 0.0 ~ 1.0,
  "risk_level": "low | medium | high",
  "reasoning": [
    "趋势分析: ...",
    "技术指标分析: ...",
    "形态分析: ...",
    "综合研判: ..."
  ],
  "target_price_range": {{
    "low": 0.00,
    "high": 0.00
  }},
  "key_factors": ["因素1", "因素2", ...],
  "risk_warnings": ["风险1", "风险2", ...]
}}
```

Required fields: {required_fields}
"""

# DEPRECATED: use ANALYSIS_SYSTEM_PROMPT instead
_SYSTEM_PROMPT_TEMPLATE = """\
You are an AI portfolio manager managing a real A-share portfolio.
Perform technical analysis strictly based on injected data. Write all output text in Chinese.
Each analysis must end with an actionable decision conclusion.

Rules: Use only historical data + technical indicators. Cover trend / indicator / pattern dimensions.
Confidence range 0-1. Target price based on support/resistance levels.
Stop-loss must be below current price. Never fabricate numbers.
Capital flow: northbound + ETF aligned = high confidence; rising margin balance = risk appetite increase.
{portfolio_context}
{output_schema}
"""

# DEPRECATED: use PromptBuilderV2.build_decision_prompt instead
REALTIME_ANALYSIS_TEMPLATE = """\
## Real-time Analysis Request

### Stock Code: {symbol}

### Real-time Quote
{quote_info}

### Concept Sectors
{concept_info}

### Recent News
{news_info}

### Anomaly Information
{anomaly_info}

### Technical Indicators
{indicators_info}

### Intraday Bid-Ask Statistics
{intraday_trades_info}

### Quantitative Strategy Signals
{strategy_signals_info}

### Bayesian Historical Probability Analysis
{bayesian_info}

Synthesize all data above (including concept sector resonance, bid-ask statistics, quant strategy signals, and Bayesian probabilities), combined with current market session timing, to produce a comprehensive analysis of this stock with investment recommendations.
Output strictly in the specified JSON format. Write all output text in Chinese.
"""

# DEPRECATED: use PromptBuilderV2.build_quick_prompt instead
QUICK_INSIGHT_TEMPLATE = """\
Stock {symbol} | {quote_info}
Technical indicators: {indicators_info}{strategy_consensus}
Give a one-sentence signal and reason. Output in Chinese.
"""

# DEPRECATED: use PromptBuilderV2.build_macro_prompt instead
MARKET_BRIEFING_TEMPLATE = """\
## Market Overview

### Major Indices
{indices_info}

### Hot Stocks
{hot_stocks_info}

Based on the current market session, generate an A-share market overview analysis. Output in Chinese.
"""


class PromptBuilder:
    """DEPRECATED: Use PromptBuilderV2 instead.

    Builds structured prompt messages for Claude API analysis requests.

    Formats stock data, technical indicators, candlestick patterns, and
    support/resistance levels into a structured multi-message prompt
    conforming to the Anthropic Messages API format.

    Attributes:
        config: Parsed prediction.yaml configuration dictionary.
    """

    def __init__(self, config_path: str = "prediction") -> None:
        """Initialize the prompt builder by loading configuration.

        Args:
            config_path: Config file name without extension, resolved
                by ``load_config`` to ``config/<name>.yaml``.
        """
        self.config: dict[str, Any] = load_config(config_path)
        self._output_schema_cfg: dict[str, Any] = self.config.get("output_schema", {})
        self._required_fields: list[str] = self._output_schema_cfg.get(
            "required_fields", []
        )
        logger.info(
            "PromptBuilder initialized with %d required output fields",
            len(self._required_fields),
        )

    def build_analysis_prompt(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        indicators: dict[str, Any],
        patterns: list[dict[str, Any]],
        sr_levels: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Build a complete message list for the Claude API analysis call.

        DEPRECATED: Use PromptBuilderV2.build_decision_prompt instead.

        Args:
            symbol: 6-digit stock code (e.g. ``"000001"``).
            ohlcv_df: DataFrame with columns date, open, high, low, close,
                volume, amount. Must have at least 1 row.
            indicators: Dictionary of technical indicator values, keyed by
                indicator name (e.g. ``{"ma5": 10.5, "rsi": 65.2}``).
            patterns: List of detected candlestick patterns, each a dict
                with keys like ``name``, ``type``, ``date``, ``reliability``.
            sr_levels: List of support/resistance levels, each a dict with
                keys like ``level``, ``type``, ``strength``.

        Returns:
            List of message dicts with ``role`` and ``content`` keys,
            suitable for passing to the Anthropic Messages API.
        """
        output_schema = _OUTPUT_SCHEMA_TEMPLATE.format(
            required_fields=", ".join(self._required_fields)
        )
        system_content = _SYSTEM_PROMPT_TEMPLATE.format(
            output_schema=output_schema, portfolio_context=""
        )

        ohlcv_summary = self._format_ohlcv_summary(ohlcv_df)
        indicators_text = self._format_indicators(indicators)
        patterns_text = self._format_patterns(patterns)
        sr_text = self._format_sr_levels(sr_levels)

        user_content = (
            f"## Stock Code: {symbol}\n\n"
            f"### Recent OHLCV Data\n{ohlcv_summary}\n\n"
            f"### Technical Indicators\n{indicators_text}\n\n"
            f"### Candlestick Patterns\n{patterns_text}\n\n"
            f"### Support / Resistance Levels\n{sr_text}\n\n"
            f"Based on the data above, perform a comprehensive technical analysis of this stock "
            f"and output results strictly in the specified JSON format. Write all output text in Chinese."
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        logger.debug(
            "Built analysis prompt for %s: system=%d chars, user=%d chars",
            symbol,
            len(system_content),
            len(user_content),
        )
        return messages

    def _format_ohlcv_summary(self, df: pd.DataFrame) -> str:
        """Format the last 10 trading days of OHLCV data as a text table.

        Args:
            df: DataFrame with columns date, open, high, low, close,
                volume. Uses the last 10 rows if the DataFrame is longer.

        Returns:
            Formatted text table string with header and aligned columns.
        """
        recent = df.tail(10).copy()

        lines: list[str] = []
        header = (
            f"{'Date':<12} {'Open':>8} {'High':>8} "
            f"{'Low':>8} {'Close':>8} {'Volume':>12}"
        )
        lines.append(header)
        lines.append("-" * len(header))

        for _, row in recent.iterrows():
            date_str = str(row.get("date", "N/A"))
            if hasattr(row.get("date"), "strftime"):
                date_str = row["date"].strftime("%Y-%m-%d")

            line = (
                f"{date_str:<12} "
                f"{row.get('open', 0):>8.2f} "
                f"{row.get('high', 0):>8.2f} "
                f"{row.get('low', 0):>8.2f} "
                f"{row.get('close', 0):>8.2f} "
                f"{row.get('volume', 0):>12.0f}"
            )
            lines.append(line)

        return "\n".join(lines)

    def _format_indicators(self, indicators: dict[str, Any]) -> str:
        """Format technical indicator values into a readable text block.

        Args:
            indicators: Dictionary of indicator name -> value pairs.
                Values can be numeric or string. Nested dicts are
                flattened with dot notation.

        Returns:
            Formatted indicator text, one indicator per line.
        """
        if not indicators:
            return "无技术指标数据"

        lines: list[str] = []
        for name, value in indicators.items():
            if isinstance(value, dict):
                # Flatten nested indicator groups (e.g., MACD sub-values)
                for sub_name, sub_value in value.items():
                    formatted = self._format_single_value(sub_value)
                    lines.append(f"- {name}.{sub_name}: {formatted}")
            else:
                formatted = self._format_single_value(value)
                lines.append(f"- {name}: {formatted}")

        return "\n".join(lines)

    def _format_patterns(self, patterns: list[dict[str, Any]]) -> str:
        """Format detected candlestick patterns into a readable text block.

        Args:
            patterns: List of pattern dicts, each expected to have keys
                ``name``, ``type`` (bullish/bearish), and optionally
                ``date`` and ``reliability``.

        Returns:
            Formatted pattern text, one pattern per line.
        """
        if not patterns:
            return "未检测到明显K线形态"

        lines: list[str] = []
        for pattern in patterns:
            name = pattern.get("name", "未知形态")
            pattern_type = pattern.get("type", "neutral")
            date = pattern.get("date", "")
            reliability = pattern.get("reliability", "")

            parts = [f"- {name} ({pattern_type})"]
            if date:
                parts.append(f"Date: {date}")
            if reliability:
                parts.append(f"Reliability: {reliability}")

            lines.append(" | ".join(parts))

        return "\n".join(lines)

    def _format_sr_levels(self, sr_levels: list[dict[str, Any]]) -> str:
        """Format support and resistance levels into a readable text block.

        Args:
            sr_levels: List of S/R level dicts, each expected to have keys
                ``level`` (price), ``type`` (support/resistance), and
                optionally ``strength``.

        Returns:
            Formatted S/R level text, one level per line.
        """
        if not sr_levels:
            return "无支撑/阻力位数据"

        lines: list[str] = []
        for sr in sr_levels:
            level = sr.get("level", 0)
            sr_type = sr.get("type", "unknown")
            strength = sr.get("strength", "")

            label = "Support" if sr_type == "support" else "Resistance"
            parts = [f"- {label}: {level:.2f}"]
            if strength:
                parts.append(f"Strength: {strength}")

            lines.append(" | ".join(parts))

        return "\n".join(lines)

    def build_market_prompt(
        self,
        index_data: dict[str, pd.DataFrame],
        market_indicators: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Build a prompt for broad market overview analysis.

        DEPRECATED: Use PromptBuilderV2.build_macro_prompt instead.

        Args:
            index_data: Mapping of index code to OHLCV DataFrame (e.g.
                ``{"000001": df_sh, "399001": df_sz}``).
            market_indicators: Dictionary of market-wide indicators such as
                northbound capital flow, margin balance, breadth, etc.

        Returns:
            List of message dicts with ``role`` and ``content`` keys,
            suitable for passing to the Anthropic Messages API.
        """
        system_content = (
            "You are a professional A-share market analyst. Based on the provided index data "
            "and market indicators, analyze the current overall market conditions.\n"
            "Write all output text in Chinese.\n\n"
            "You must output analysis results strictly in the following JSON format. "
            "Do not add any extra text:\n\n"
            "```json\n"
            "{\n"
            '  "market_trend": "bullish | bearish | neutral",\n'
            '  "risk_assessment": "low | medium | high",\n'
            '  "sector_outlook": {\n'
            '    "leading": ["板块1", "板块2"],\n'
            '    "lagging": ["板块3", "板块4"]\n'
            "  },\n"
            '  "reasoning": ["分析要点1", "分析要点2"],\n'
            '  "key_risks": ["风险1", "风险2"]\n'
            "}\n"
            "```\n"
        )

        # Format index data sections
        index_sections: list[str] = []
        for code, df in index_data.items():
            summary = self._format_ohlcv_summary(df)
            index_sections.append(f"#### Index {code}\n{summary}")

        index_text = "\n\n".join(index_sections) if index_sections else "No index data"
        indicators_text = self._format_indicators(market_indicators)

        user_content = (
            "## Market Overview Analysis\n\n"
            f"### Major Index Data\n{index_text}\n\n"
            f"### Market Indicators\n{indicators_text}\n\n"
            "Based on the data above, analyze the overall A-share market trend "
            "and output results strictly in the specified JSON format. Write all output text in Chinese."
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        logger.debug(
            "Built market prompt: system=%d chars, user=%d chars",
            len(system_content),
            len(user_content),
        )
        return messages

    @staticmethod
    def _format_single_value(value: Any) -> str:
        """Format a single indicator value for display.

        Args:
            value: Numeric or string value to format.

        Returns:
            Formatted string representation.
        """
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)


# ---------------------------------------------------------------------------
# DEPRECATED: Intel-triggered Portfolio Analysis prompts (v25.0 FR-IA002)
# Use ANALYSIS_SYSTEM_PROMPT + ANALYSIS_USER_TEMPLATE instead.
# ---------------------------------------------------------------------------

# DEPRECATED: use ANALYSIS_SYSTEM_PROMPT instead
INTEL_ANALYSIS_SYSTEM_PROMPT = """\
You are a senior investment analyst with 10 years of A-share practical experience and CFA qualification.
Your task is to perform professional multi-dimensional analysis on stocks the user holds or watches,
based on the latest intelligence combined with the global macro environment.
Write all output text in Chinese.

## Anti-Hallucination Rules (violating any one invalidates the analysis)
H01: Never fabricate any numbers — prices, change %, volume, capital flow, etc. must come from system-injected data.
H02: If the system did not provide a data point, mark it as '无该数据'. Never fill in or guess values.
H03: Target price range must be based on current price +/- reasonable volatility (mainboard within +/-15%), and target low >= stop-loss.
H04: Stop-loss price must be below current price (long scenario).
H05: Change % values must match system-injected quote data.
H06: Capital flow values must directly quote system-injected data. Never fabricate.
H07: When the system marks a non-trading session, do not use language implying the market is actively trading.

## Intelligence Analysis Rules
IA01: Distinguish hard news (policy/earnings/announcements) from soft news (market rumors/analyst opinions). Former weight > 0.3, latter weight < 0.15.
IA02: When the same event is reported by >= 3 independent sources, cross_verification=true, confidence may be raised.
IA03: Must assess macro environment transmission path to the stock (e.g., "Fed rate cut -> RMB appreciation -> northbound inflow -> bullish for this stock").
IA04: Intelligence timeliness: <1h = highly relevant, 1-6h = moderately relevant, >24h = background reference only.
IA05: If global market data is provided, must analyze cross-market linkage effects.

## Confidence Tiers
| Range     | Label                  | Allowed Actions        |
|-----------|------------------------|------------------------|
| 0.00-0.20 | Very low (insufficient data) | watch only       |
| 0.20-0.40 | Low (ambiguous signal) | watch, hold            |
| 0.40-0.60 | Medium (divergence)    | watch, hold, reduce    |
| 0.60-0.80 | High (clear direction) | all actions            |
| 0.80-1.00 | Very high (multi-signal resonance) | all actions |

## Risk-Action Constraint Matrix
- risk_level=high -> action limited to hold / reduce / sell / watch (buy / add prohibited)
- risk_level=medium -> all actions allowed (must include risk note)
- risk_level=low -> all actions allowed

Output strictly in the following JSON format. Do not add any extra text:

```json
{{
  "action": "buy | sell | hold | watch",
  "signal": "bullish | bearish | neutral",
  "confidence": 0.0,
  "summary": "一句话概括分析结论",
  "factors": [
    {{
      "category": "news | policy | sector | technical | flow | sentiment | fundamental | macro",
      "impact": "positive | negative | neutral",
      "weight": 0.0,
      "description": "具体描述"
    }}
  ],
  "position_context": {{
    "cost_price": 0.00,
    "shares": 0,
    "pnl_percent": 0.00,
    "advice": "结合持仓的个性化建议",
    "key_levels": {{ "support": 0.00, "resistance": 0.00 }}
  }},
  "risk_warnings": ["风险提示1", "风险提示2"],
  "outlook": "短期展望（1-5个交易日）",
  "reasoning": ["推理步骤1", "推理步骤2"],
  "intel_summary": "情报要点概括"
}}
```

Note: If no position data is provided, output position_context as null.
"""

# DEPRECATED: use ANALYSIS_USER_TEMPLATE instead
INTEL_ANALYSIS_USER_TEMPLATE = """\
## Intelligence-Driven Analysis Request

### Stock: {stock_name} ({symbol})

### Matched Intelligence ({intel_count} items)
{intel_items_text}

### Position Information
{position_section}

Synthesize the intelligence above, analyze potential impact on this stock, and provide action recommendations. Output in Chinese.
"""

# DEPRECATED: use ANALYSIS_USER_TEMPLATE instead
INTEL_ANALYSIS_USER_TEMPLATE_V2 = """\
## Intelligence-Driven Analysis Request

### Stock: {stock_name} ({symbol})

### Macro Environment Snapshot
{macro_snapshot}

### Global Market Data
{global_market_data}

### Matched Intelligence ({intel_count} items)
{intel_items_text}

### Related Sector Macro Signals
{sector_macro_signals}

### Position Information
{position_section}

### Recent Recommendation Records
{recent_recommendations}

Synthesize the macro environment, global market linkages, and intelligence content to analyze potential impact on this stock and provide action recommendations. Output in Chinese.
"""

# ---------------------------------------------------------------------------
# DEPRECATED: Macro Analysis prompts — use MACRO_SYSTEM_PROMPT instead.
# ---------------------------------------------------------------------------

# DEPRECATED: use MACRO_SYSTEM_PROMPT instead
MACRO_ANALYSIS_SYSTEM_PROMPT = """\
You are a Chief Investment Officer-level strategist with a global macro perspective.
Your task is to analyze how macro events (geopolitics, central bank policy, commodity shocks)
transmit to the A-share market.
Write all output text in Chinese.

## Anti-Hallucination Rules
H01: Never fabricate any numbers — all values must come from system-injected data.
H02: If the system did not provide a data point, mark it as '无该数据'.

## Analysis Framework
1. Event classification: Event type (geopolitical/monetary/fiscal/commodity/systemic risk), persistence (one-time/persistent).
2. Transmission path: Event -> global market reaction -> FX/capital flow -> A-share sector/stock impact.
3. Historical reference: Market reaction patterns from similar historical events.
4. Affected sectors: Bullish, bearish, and neutral sectors — each with specific transmission logic.
5. Time dimension: Short-term (1-3 day) shock vs medium-term (1-4 week) trend vs long-term (quarterly) structure.
6. Action recommendation: Sector rotation direction, defensive allocation advice.

Output strictly in the following JSON format. Do not add any extra text:

```json
{{
  "event_type": "geopolitical | monetary_policy | fiscal_policy | commodity_shock | systemic_risk",
  "event_persistence": "one_time | persistent",
  "signal": "bullish | bearish | neutral",
  "confidence": 0.0,
  "summary": "一句话概括事件及影响",
  "transmission_path": "事件→传导→A股影响的路径描述",
  "affected_sectors": {{
    "bullish": [{{"sector": "板块名", "logic": "传导逻辑"}}],
    "bearish": [{{"sector": "板块名", "logic": "传导逻辑"}}],
    "neutral": [{{"sector": "板块名", "logic": "传导逻辑"}}]
  }},
  "time_horizons": {{
    "short_term": "1-3天冲击分析",
    "medium_term": "1-4周趋势分析",
    "long_term": "季度结构分析"
  }},
  "risk_warnings": ["风险提示1", "风险提示2"],
  "action_suggestion": "板块轮动方向和防御配置建议",
  "historical_reference": "类似历史事件参照（如有）"
}}
```
"""

# DEPRECATED: use MACRO_USER_TEMPLATE instead
MACRO_ANALYSIS_USER_TEMPLATE = """\
## Macro Event Analysis Request

### Macro Events ({event_count} items)
{macro_events_text}

### Global Market Data
{global_market_data}

### Current A-Share Environment
{a_share_context}

Analyze the transmission impact of these macro events on the A-share market and provide sector-level investment recommendations. Output in Chinese.
"""
