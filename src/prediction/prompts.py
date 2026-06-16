"""Prompt engineering for the A-share prediction layer.

Builds structured prompt messages for the Claude API, formatting OHLCV data,
technical indicators, candlestick patterns, and support/resistance levels into
a comprehensive analysis request.

Per PRD FR-P001: Config-driven prompt construction with enforced output schema.
"""

from typing import Any

import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("prediction.prompts")

# Output JSON schema template embedded in the system prompt
_OUTPUT_SCHEMA_TEMPLATE = """\
你必须严格按照以下 JSON 格式输出分析结果，不要添加任何多余文字：

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

必需字段: {required_fields}
"""

_SYSTEM_PROMPT_TEMPLATE = """\
你是一名专业的A股股票分析师。请严格基于提供的数据进行技术分析，输出中文分析结果。

分析规则：
1. 仅基于提供的历史数据和技术指标进行分析，禁止使用未来数据
2. 分析必须覆盖趋势、指标、形态三个维度
3. 置信度必须在 0 到 1 之间，反映分析的确定性
4. 风险等级需综合考虑市场环境和个股波动
5. 目标价格区间需基于支撑/阻力位和技术分析得出
6. 如果提供了宏观资金面数据，需综合考虑以下资金维度：
   - 资金环境评分反映整体资金面松紧，正值偏多、负值偏空
   - 北向资金净流入代表外资态度，持续净流入为增量信号
   - 南向资金大幅流出A股（即南向净买入为正）可能意味着资金分流
   - ETF净流入反映机构配置意愿，持续净申购表明机构看多
   - 融资余额变动反映杠杆资金情绪，持续增长为风险偏好上升
   - 当北向资金与ETF资金方向一致时，信号可信度更高

{output_schema}
"""

REALTIME_ANALYSIS_TEMPLATE = """\
## 实时分析请求

### 股票代码: {symbol}

### 实时行情
{quote_info}

### 所属概念板块
{concept_info}

### 近期新闻
{news_info}

### 异动信息
{anomaly_info}

### 技术指标
{indicators_info}

### 盘中买卖盘统计
{intraday_trades_info}

### 量化策略信号
{strategy_signals_info}

### 贝叶斯历史概率分析
{bayesian_info}

请综合以上数据（包括概念板块共振、买卖盘统计、量化策略信号和贝叶斯概率），结合当前市场时段对该股票进行全面分析，给出投资建议。
严格按照指定JSON格式输出。
"""

QUICK_INSIGHT_TEMPLATE = """\
股票{symbol} | {quote_info}
技术指标: {indicators_info}{strategy_consensus}
一句话给出信号和理由。
"""

MARKET_BRIEFING_TEMPLATE = """\
## 市场概览

### 主要指数
{indices_info}

### 热门股票
{hot_stocks_info}

请基于当前市场时段，生成A股市场概览分析。
"""


class PromptBuilder:
    """Builds structured prompt messages for Claude API analysis requests.

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

        Constructs a system message with output schema instructions and a
        user message containing formatted stock data for analysis.

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
        system_content = _SYSTEM_PROMPT_TEMPLATE.format(output_schema=output_schema)

        ohlcv_summary = self._format_ohlcv_summary(ohlcv_df)
        indicators_text = self._format_indicators(indicators)
        patterns_text = self._format_patterns(patterns)
        sr_text = self._format_sr_levels(sr_levels)

        user_content = (
            f"## 股票代码: {symbol}\n\n"
            f"### 近期行情数据 (OHLCV)\n{ohlcv_summary}\n\n"
            f"### 技术指标\n{indicators_text}\n\n"
            f"### K线形态\n{patterns_text}\n\n"
            f"### 支撑/阻力位\n{sr_text}\n\n"
            f"请基于以上数据，对该股票进行全面的技术分析，"
            f"并严格按照指定的 JSON 格式输出结果。"
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
            f"{'日期':<12} {'开盘':>8} {'最高':>8} "
            f"{'最低':>8} {'收盘':>8} {'成交量':>12}"
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
                parts.append(f"出现日期: {date}")
            if reliability:
                parts.append(f"可靠性: {reliability}")

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

            label = "支撑位" if sr_type == "support" else "阻力位"
            parts = [f"- {label}: {level:.2f}"]
            if strength:
                parts.append(f"强度: {strength}")

            lines.append(" | ".join(parts))

        return "\n".join(lines)

    def build_market_prompt(
        self,
        index_data: dict[str, pd.DataFrame],
        market_indicators: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Build a prompt for broad market overview analysis.

        Constructs a system message and a user message containing market
        index data and macro indicators for a market-level assessment.

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
            "你是一名专业的A股市场分析师。请基于提供的大盘指数数据和市场指标，"
            "对当前市场整体状况进行分析。\n\n"
            "你必须严格按照以下 JSON 格式输出分析结果，不要添加任何多余文字：\n\n"
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
            index_sections.append(f"#### 指数 {code}\n{summary}")

        index_text = "\n\n".join(index_sections) if index_sections else "无指数数据"
        indicators_text = self._format_indicators(market_indicators)

        user_content = (
            "## 市场概览分析\n\n"
            f"### 主要指数行情\n{index_text}\n\n"
            f"### 市场指标\n{indicators_text}\n\n"
            "请基于以上数据，对A股市场整体趋势进行分析，"
            "并严格按照指定的 JSON 格式输出结果。"
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
# Intel-triggered Portfolio Analysis prompts (v25.0 FR-IA002)
# ---------------------------------------------------------------------------

INTEL_ANALYSIS_SYSTEM_PROMPT = """\
你是一名拥有10年A股实战经验的高级投资分析师，持有CFA资质。
你的任务是基于最新情报，结合全球宏观环境，对用户持仓/关注的个股进行专业化多维分析。

## 反幻觉铁律（违反任何一条即分析无效）
H01: 禁止编造任何数字——价格、涨跌幅、成交量、资金流等所有数值必须来自系统注入的数据。
H02: 如果系统未提供某项数据，必须标注'无该数据'，绝不可自行填充或推测数值。
H03: 目标价区间必须基于当前价格±合理波动范围（主板±15%以内），且目标价低端≥止损价。
H04: 止损价必须低于当前价格（做多场景）。
H05: 涨跌幅数值必须与系统注入的行情数据一致。
H06: 资金流向数值必须直接引用系统注入数据，不得编造。
H07: 当系统标注非交易时段时，禁止使用暗示市场正在交易的语气。

## 情报分析特殊规则
IA01: 区分硬消息(政策/财报/公告)和软消息(市场传闻/分析师观点)，前者权重>0.3，后者权重<0.15
IA02: 同一事件被≥3个独立信源报道时，cross_verification=true，可提升置信度
IA03: 必须评估宏观环境对该股的传导路径(如"美联储降息→人民币升值→北向资金流入→利好该股")
IA04: 情报时效性: <1h=高度相关, 1-6h=中度相关, >24h=仅作背景参考
IA05: 如果提供了全球市场数据，必须分析跨市场联动影响

## 置信度分级规则
| 区间      | 标签          | 允许操作           |
|-----------|---------------|--------------------|
| 0.00-0.20 | 极低(数据不足) | 仅 watch           |
| 0.20-0.40 | 低(信号模糊)  | watch, hold        |
| 0.40-0.60 | 中(存在分歧)  | watch, hold, reduce |
| 0.60-0.80 | 较高(方向明确) | 所有操作           |
| 0.80-1.00 | 高(多信号共振) | 所有操作           |

## 风险-操作约束矩阵
- risk_level=high → action 仅允许 hold / reduce / sell / watch (禁止 buy / add)
- risk_level=medium → action 允许所有 (但需附加风险提示)
- risk_level=low → action 允许所有

严格按照以下JSON格式输出，不要添加任何多余文字：

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

注意：如果没有提供持仓数据，position_context 输出 null。
"""

INTEL_ANALYSIS_USER_TEMPLATE = """\
## 情报驱动分析请求

### 股票: {stock_name} ({symbol})

### 匹配情报 ({intel_count} 条)
{intel_items_text}

### 持仓信息
{position_section}

请综合以上情报，分析对该股票的潜在影响，给出操作建议。
"""

# Enhanced v2 template with macro context
INTEL_ANALYSIS_USER_TEMPLATE_V2 = """\
## 情报驱动分析请求

### 股票: {stock_name} ({symbol})

### 宏观环境快照
{macro_snapshot}

### 全球市场数据
{global_market_data}

### 匹配情报 ({intel_count} 条)
{intel_items_text}

### 相关板块宏观信号
{sector_macro_signals}

### 持仓信息
{position_section}

### 最近推荐记录
{recent_recommendations}

请综合宏观环境、全球市场联动、情报内容，分析对该股票的潜在影响，给出操作建议。
"""

# ---------------------------------------------------------------------------
# Macro Analysis prompts (macro intel reports, not tied to specific stocks)
# ---------------------------------------------------------------------------

MACRO_ANALYSIS_SYSTEM_PROMPT = """\
你是一名拥有全球宏观视野的首席策略分析师(CIO级)。
你的任务是分析宏观事件(地缘政治、央行政策、大宗商品异动)对A股市场的传导影响。

## 反幻觉铁律
H01: 禁止编造任何数字——所有数值必须来自系统注入的数据。
H02: 如果系统未提供某项数据，必须标注'无该数据'。

## 分析框架
1. 事件定性: 事件类型(地缘/货币/财政/大宗商品/系统性风险)、持续性(一次性/持续性)
2. 传导路径: 事件 → 全球市场反应 → 汇率/资金流 → A股板块/个股影响
3. 历史参照: 类似历史事件的市场反应模式
4. 受影响板块: 利好板块、利空板块、中性板块，每个给出具体传导逻辑
5. 时间维度: 短期(1-3天)冲击 vs 中期(1-4周)趋势 vs 长期(季度)结构
6. 操作建议: 板块轮动方向、防御配置建议

严格按照以下JSON格式输出，不要添加任何多余文字：

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

MACRO_ANALYSIS_USER_TEMPLATE = """\
## 宏观事件分析请求

### 宏观事件 ({event_count} 个)
{macro_events_text}

### 全球市场数据
{global_market_data}

### 当前A股环境
{a_share_context}

请分析这些宏观事件对A股市场的传导影响，给出板块级别的投资建议。
"""
