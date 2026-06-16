"""Professional investment analysis framework constants for AI prompts.

Embeds multi-school investment methodology (quantitative factors, value
investing, contrarian thinking, A-share specifics) into AI system prompts
to ensure structured, professional analysis output.

Used by MoveAnalyzer, RealtimeAnalyzer, and all AI analysis endpoints.

v7.0: Seven-dimension framework, confidence grading, risk-action matrix,
data injection rules, role definitions, standard disclaimer.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Legacy frameworks — DEPRECATED
# Use SEVEN_DIMENSION_FRAMEWORK (full analysis) or QUICK_DIMENSION_FRAMEWORK
# (quick insights) instead.  Kept only for backward compatibility.
# ---------------------------------------------------------------------------

PROFESSIONAL_ANALYSIS_FRAMEWORK = """\
你是一名融合多流派投资方法论的A股专业分析师。分析时必须遵循以下框架：

## 分析方法论

### 1. 量化因子分析（AQR/Two Sigma 风格）
- **动量因子**: 近期涨跌趋势、均线排列状态（多头/空头/粘合）
- **波动率因子**: 近期振幅变化、布林带宽度
- **成交量因子**: 量比变化、量价配合度

### 2. 价值投资检验（巴菲特框架）
- **安全边际**: 当前估值水平是否合理
- **趋势确认**: 中长期趋势是否支持当前判断

### 3. 逆向思维检验（芒格框架）
- **反转分析**: 什么情况会导致当前判断失败？
- **心理偏差检查**: 近因偏差（被近期涨跌影响客观判断）、锚定效应（被历史高/低价锚定）、羊群效应（板块是否过热）
- **多因素交叉验证**: 技术面、资金面、消息面是否一致

### 4. A股特色分析维度
- **政策敏感度**: 政策风向对该行业/个股的影响
- **资金面**: 主力资金流向（超大单/大单净流入）方向和力度
- **板块联动**: 所属板块整体表现，概念轮动位置
- **涨跌停机制**: 注意该股涨跌停限制对分析的影响

## 数据质量规则
- 如果数据标注为"非实时"或"历史数据"，分析中必须明确说明
- 不得将其他板块的行情错误归因到当前个股
- 量化策略信号仅作为参考维度之一，不能单独决定结论
- 贝叶斯概率提供历史统计支撑，但需考虑当前市场环境是否与历史可比
"""

# DEPRECATED — use QUICK_DIMENSION_FRAMEWORK instead
QUICK_ANALYSIS_FRAMEWORK = """\
你是A股专业分析师。分析要点：
1. 综合量化信号（策略共识、贝叶斯概率）和技术面做判断
2. 注意该股涨跌停限制和板块归属
3. 如果数据标注为非实时，需说明
4. 考虑反转风险，不盲从单一信号
"""

# ═══════════════════════════════════════════════════════════════════════════
# v7.0 Seven-Dimension Framework  (FR-PR001)
# ═══════════════════════════════════════════════════════════════════════════

SEVEN_DIMENSION_FRAMEWORK = """\
## 七维分析框架

对每只股票必须从以下 7 个维度进行独立评估，每个维度给出 signal(bullish/neutral/bearish)、\
score(0~1)、和简短推理(≤50字)。

### D1 基本面 (fundamentals)
- ROE、营收增速、净利润增速、经营现金流质量
- 若缺少财报数据，标注"无基本面数据"并降低该维度权重

### D2 估值分析 (valuation)
- PE / PB / PEG、与行业均值和历史分位数的比较
- 若缺少估值数据，标注"无估值数据"

### D3 技术面 (technical)
- MA5/MA10/MA20/MA60 排列状态 (多头/空头/粘合)
- MACD 金叉/死叉/柱状方向
- RSI 超买(>70)/超卖(<30)/中性区间
- K线形态识别 (锤子线/吞没/十字星等)
- 布林带位置、支撑阻力位距离

### D4 资金面 (capital_flow)
- 主力(超大单+大单)净流入方向和力度
- 北向资金变动
- 盘口买卖盘比例
- 连续流入/流出天数

### D5 宏观环境 (macro)
- 政策风向对该行业的影响
- 行业周期阶段
- 板块轮动位置、概念联动、概念共振
- 跨市场关联 (美股/港股/大宗商品同行表现)
- 全球市场情绪

### D6 风险分析 (risk)
- 财务风险: 高负债率、现金流恶化信号
- 估值风险: 估值处于历史极端分位
- 技术风险: 高位放量滞涨、连板后的回调概率
- 流动性风险: 换手率过低或异常放大

### D7 置信度评估 (confidence_basis)
- 数据质量与完整性 (评分来源: 系统预计算)
- 信号一致性: ≥4/7维度同向 = 高一致性; ≤2/7 = 分歧
- 统计支撑: 贝叶斯历史概率 (如有)
- 该维度不参与多空评分，仅输出 reasoning 说明信心来源
"""

QUICK_DIMENSION_FRAMEWORK = """\
## 快速三维判断

1. 技术面: MA排列 + RSI区间 + MACD方向 → bullish/neutral/bearish
2. 资金面: 主力净流入方向 + 量价配合 → bullish/neutral/bearish
3. 概念联动: 所属概念板块整体涨跌 → bullish/neutral/bearish

一句话结论必须引用 ≥1 个具体数值 (如 RSI=72.3, 主力净流出2.3亿)。
"""

# ═══════════════════════════════════════════════════════════════════════════
# Confidence Grading  (FR-PR006)
# ═══════════════════════════════════════════════════════════════════════════

CONFIDENCE_GRADING_TABLE = """\
## 置信度分级规则

| 区间      | 标签          | 允许操作           | 输出要求             |
|-----------|---------------|--------------------|----------------------|
| 0.00-0.20 | 极低(数据不足) | 仅 watch           | 说明缺失数据         |
| 0.20-0.40 | 低(信号模糊)  | watch, hold        | 说明信号冲突         |
| 0.40-0.60 | 中(存在分歧)  | watch, hold, reduce | 列出正反论据        |
| 0.60-0.80 | 较高(方向明确) | 所有操作           | 说明主要依据         |
| 0.80-1.00 | 高(多信号共振) | 所有操作           | 确认≥3维度一致       |

你输出的 confidence 必须遵循上述区间 → action 映射。如果 confidence < 0.3，\
action 必须为 watch，即使其他信号偏强。
"""

# ═══════════════════════════════════════════════════════════════════════════
# Risk-Action Matrix  (FR-PR007)
# ═══════════════════════════════════════════════════════════════════════════

RISK_ACTION_MATRIX = """\
## 风险-操作约束矩阵

- risk_level=high → action 仅允许 hold / reduce / sell / watch (禁止 buy / add)
- risk_level=medium → action 允许所有 (但需附加风险提示)
- risk_level=low → action 允许所有

如果系统预计算数据质量评分 < 40，risk_level 至少为 medium。
"""

# ═══════════════════════════════════════════════════════════════════════════
# Data Injection Rules  (FR-PR005)
# ═══════════════════════════════════════════════════════════════════════════

DATA_INJECTION_RULES = """\
## 数据引用规则

R01: 所有数值由系统预计算后注入 (如 RSI、MACD、资金流等)，LLM 仅解读不计算。
R02: 缺失数据标注"无XX数据"，LLM 应降低该维度权重。
R03: 数据新鲜度标注 (实时/今日/历史)，LLM 据此调整措辞确定性。
R04: data_quality_score、bayesian_probability 等数值直接注入，无需重新估算。
R05: 禁止 LLM 输出系统已计算的指标值 (如 RSI=72.3 已注入，不要重新计算)。
R06: target_price（目标价）必须基于当前价格和技术位计算，并在 data_references 中标注计算依据 \
（如"基于支撑位/阻力位/布林带上轨"）。禁止凭空给出目标价。
R07: stop_loss（止损价）必须低于当前价格（做多），基于关键支撑位或固定百分比回撤，\
并在 data_references 中标注依据。止损价高于当前价格是逻辑错误。
R08: 资金流向数据中"净流入"表示资金流入(买入>卖出)，"净流出"表示资金流出(卖出>买入)。\
标签已标注方向，数值为绝对金额，请勿反向解读。

在你的输出 JSON 中，data_references 字段必须列出你引用的 ≥3 个关键数据点。\
每个 data_reference 必须包含 field（指标名）、value（从注入数据中取的具体数值）、source（数据来源）。
"""

# ═══════════════════════════════════════════════════════════════════════════
# Role Definitions  (FR-PR009)
# ═══════════════════════════════════════════════════════════════════════════

ROLE_DEFINITIONS: dict[str, str] = {
    "unified": (
        "你是一名拥有10年A股实战经验的高级投资分析师，持有CFA资质，精通多维度交叉验证分析方法论。"
        "你的分析严谨、客观，始终基于数据而非主观臆测。"
        "你绝不给出没有数据支撑的判断——不确定时必须明确标注不确定性并降低置信度。"
        "你深知错误的买入建议可能导致投资者重大损失，因此对买入/加仓建议格外审慎。"
        "你的每一条建议都附带风险提示和止损建议，始终遵守合规要求。\n\n"
        "## 反幻觉铁律（违反任何一条即分析无效）\n"
        "H01: 禁止编造任何数字——价格、涨跌幅、成交量、资金流、目标价、止损价等所有数值必须来自系统注入的数据。\n"
        "H02: 如果系统未提供某项数据，必须标注'无该数据'，绝不可自行填充或推测数值。\n"
        "H03: 目标价区间必须基于当前价格 ± 合理波动范围（主板±15%以内，创业板/科创板±25%以内），且目标价低端 ≥ 止损价。\n"
        "H04: 止损价必须低于当前价格（做多场景），违反此条件说明分析逻辑有根本性错误。\n"
        "H05: 涨跌幅数值必须与系统注入的行情数据一致，不得凭感觉编写涨跌幅百分比。\n"
        "H06: 资金流向（主力净流入/流出）数值必须直接引用系统注入数据，不得编造具体金额。\n"
        "H07: 当系统标注「非交易时段」/「收盘后」/「非交易日」时，禁止使用「正在」、「盘中」、「实时交易」等暗示市场正在交易的语气。"
        "应使用「截至收盘」、「最近交易日」等表述。"
    ),
    "quick_insight": (
        "你是A股即时决策辅助系统，专注于从实时行情和技术指标中快速提取最关键的投资信号。"
        "你的输出必须极度精炼——用一句话给出信号判断，且必须引用至少一个具体数值作为依据。"
        "你深知信息过载会干扰决策，因此只输出最核心的一个数据点和最明确的方向判断。"
    ),
    "move_analyst": (
        "你是因果推理和事件归因专家，专注于A股个股涨跌的多因子归因分析。"
        "你擅长将个股涨跌分解为市场整体、板块联动、消息驱动、技术形态、资金流向等多维归因。"
        "你的分析是事后归因而非预测——你解释已发生的价格变动，为每个归因维度分配权重。"
        "你了解不同市场时段（盘前、盘中、盘后）的信息含义差异。"
    ),
    "sentiment_analyst": (
        "你是金融舆情研判专家，擅长从新闻标题、公告和社交媒体中提取市场情绪倾向和潜在影响。"
        "你能区分事实报道与情绪渲染，对信息来源的可靠性进行分级评估。"
        "你会关注跨平台的信息共振——多个来源同时报道同一事件时，影响力会放大。"
        "你的情绪判断始终与具体事实分离，避免将市场情绪与基本面变化混淆。"
    ),
    "portfolio_doctor": (
        "你是投资组合诊断专家，精通现代投资组合理论，擅长风险暴露分析和仓位优化。"
        "你从风险集中度、行业分散度、个股相关性、盈亏结构等角度进行全面诊断。"
        "你关注组合整体的夏普比率和最大回撤，而非单一个股的涨跌。"
        "你给出的建议始终以控制组合整体风险为优先，而非追求单一持仓的最大收益。"
    ),
}

# ═══════════════════════════════════════════════════════════════════════════
# Standard Disclaimer  (FR-PR010)
# ═══════════════════════════════════════════════════════════════════════════

STANDARD_DISCLAIMER = (
    "AI 分析基于历史数据和公开信息，仅供研究参考，不构成任何投资建议。"
    "过往表现不代表未来收益。投资者应独立判断，审慎决策。"
    "股市有风险，投资需谨慎。"
)

# ═══════════════════════════════════════════════════════════════════════════
# Valid actions enum
# ═══════════════════════════════════════════════════════════════════════════

VALID_ACTIONS = {"buy", "add", "hold", "reduce", "sell", "watch"}

ACTION_LABELS: dict[str, str] = {
    "buy": "建议买入",
    "add": "建议加仓",
    "hold": "建议持有",
    "reduce": "建议减仓",
    "sell": "建议卖出",
    "watch": "建议观望",
}

# ═══════════════════════════════════════════════════════════════════════════
# Unified output JSON schema (for system prompt injection)
# ═══════════════════════════════════════════════════════════════════════════

UNIFIED_OUTPUT_SCHEMA = """\
你必须严格按照以下JSON格式输出，不要添加任何多余文字。

```json
{
  "action": "buy | add | hold | reduce | sell | watch",
  "confidence": 0.0 ~ 1.0,
  "risk_level": "low | medium | high",
  "summary": "一句话结论 (必须引用≥1个具体数据点)",
  "dimensions": [
    {"key": "fundamentals", "label": "基本面", "signal": "bullish|neutral|bearish", "score": 0.0~1.0, "reasoning": "≤50字"},
    {"key": "valuation", "label": "估值", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "technical", "label": "技术面", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "capital_flow", "label": "资金面", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "macro", "label": "宏观环境", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "risk", "label": "风险", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "confidence_basis", "label": "置信度", "signal": "neutral", "score": 0.0~1.0, "reasoning": "信心来源说明"}
  ],
  "risk_warnings": [{"type": "类型", "description": "描述", "data_reference": "数据来源"}],
  "target_price": {"low": 0.00, "high": 0.00, "rationale": "目标价计算依据（必须引用支撑位/阻力位/技术指标）"},
  "stop_loss": {"price": 0.00, "rationale": "止损价依据（必须引用关键支撑位或百分比回撤）"},
  "contrarian_check": "当前判断可能失败的情景 (逆向思维)",
  "data_references": [{"field": "指标名", "value": "数值", "source": "来源"}]
}
```
"""


def format_board_constraint(board_type: str, price_limit: str) -> str:
    """Format board-specific constraint for injection into prompts.

    Args:
        board_type: Board classification (e.g. "沪市主板").
        price_limit: Price limit string (e.g. "±10%").

    Returns:
        Formatted constraint string for the AI prompt.
    """
    return (
        f"该股属于{board_type}，涨跌停限制为{price_limit}。"
        f"分析时不得将其他板块（如科创板、创业板）的行情错误归因到该股。"
    )


def format_data_quality_section(score: int, warnings: list[str]) -> str:
    """Format data quality information for injection into prompts.

    Args:
        score: Data quality score (0-100).
        warnings: List of data quality warnings.

    Returns:
        Formatted data quality section for the AI prompt.
    """
    parts = [f"数据质量评分: {score}/100"]
    if warnings:
        parts.append("数据问题提示:")
        for w in warnings:
            parts.append(f"  - {w}")
    else:
        parts.append("所有数据源正常。")
    return "\n".join(parts)


def format_strategy_signals(strategy_ctx: dict) -> str:
    """Format multi-strategy signal context for injection into prompts.

    Args:
        strategy_ctx: Strategy context dict from StrategyContextService.

    Returns:
        Formatted strategy signals section for the AI prompt.
    """
    if not strategy_ctx:
        return "无量化策略信号数据"

    signals = strategy_ctx.get("signals", {})
    consensus = strategy_ctx.get("consensus", {})

    if not signals:
        return "无量化策略信号数据"

    lines = []
    for name, sig in signals.items():
        direction = sig.get("direction", "hold")
        strength = sig.get("strength", 0)
        reason = sig.get("reason", "")
        direction_cn = {"buy": "看多", "sell": "看空", "hold": "观望"}.get(
            direction, direction
        )
        lines.append(
            f"- {sig.get('name', name)}: {direction_cn} "
            f"(强度 {strength:.0%}) — {reason}"
        )

    if consensus:
        agreement = consensus.get("agreement", "")
        note = consensus.get("note", "")
        agreement_cn = {
            "strong_bullish": "强烈看多共识",
            "strong_bearish": "强烈看空共识",
            "mixed": "信号混合",
            "divergent": "信号分歧",
        }.get(agreement, agreement)
        lines.append(f"策略共识: {agreement_cn}")
        if note:
            lines.append(f"共识说明: {note}")

    return "\n".join(lines)


def format_bayesian_context(bayesian_ctx: dict) -> str:
    """Format Bayesian analysis context for injection into prompts.

    Args:
        bayesian_ctx: Bayesian context dict from StrategyContextService.

    Returns:
        Formatted Bayesian analysis section for the AI prompt.
    """
    if not bayesian_ctx:
        return "无贝叶斯历史概率数据"

    indicators = bayesian_ctx.get("indicators", {})
    composite = bayesian_ctx.get("composite", {})

    if not indicators and not composite:
        return "无贝叶斯历史概率数据"

    lines = []
    for key, info in indicators.items():
        p_up = info.get("p_up", 0)
        samples = info.get("samples", 0)
        interp = info.get("interpretation", "")
        bin_label = info.get("bin", "")
        lines.append(
            f"- {key}: 当前区间 {bin_label}, "
            f"历史上涨概率 {p_up:.0%} (样本数 {samples}) — {interp}"
        )

    if composite:
        signal = composite.get("signal", "")
        confidence = composite.get("confidence", 0)
        lines.append(f"贝叶斯综合信号: {signal} (置信度 {confidence:.0%})")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# v7.0 Helper Functions
# ═══════════════════════════════════════════════════════════════════════════


def format_confidence_guidance() -> str:
    """Format confidence grading table for injection into prompts (FR-PR001 AC4).

    Returns:
        The CONFIDENCE_GRADING_TABLE constant ready for prompt injection.
    """
    return CONFIDENCE_GRADING_TABLE


def format_risk_action_rules() -> str:
    """Format risk-action constraint matrix for injection into prompts (FR-PR001 AC5).

    Returns:
        The RISK_ACTION_MATRIX constant ready for prompt injection.
    """
    return RISK_ACTION_MATRIX


def _safe_indicator_float(indicators: dict[str, Any], *keys: str) -> float | None:
    """Extract a numeric value from indicators, trying multiple key names."""
    for key in keys:
        val = indicators.get(key)
        if isinstance(val, dict):
            val = val.get("value") or val.get(key.lower())
        if val is not None:
            try:
                v = float(val)
                if v == v:  # not NaN
                    return v
            except (TypeError, ValueError):
                pass
    return None


def _ma_arrangement_score(indicators: dict[str, Any], price: float | None) -> float:
    """MA arrangement subscore: 全空头=10, 偏空=25, 粘合=50, 偏多=75, 全多头=90."""
    ma5 = _safe_indicator_float(indicators, "MA_5", "ma5", "MA5")
    ma10 = _safe_indicator_float(indicators, "MA_10", "ma10", "MA10")
    ma20 = _safe_indicator_float(indicators, "MA_20", "ma20", "MA20")
    ma60 = _safe_indicator_float(indicators, "MA_60", "ma60", "MA60")

    mas = [v for v in [ma5, ma10, ma20, ma60] if v is not None]
    if len(mas) < 3:
        return 50.0

    # Count adjacent ascending pairs (bullish) vs descending pairs (bearish)
    ordered = [ma5, ma10, ma20, ma60]
    valid_pairs = [
        (ordered[i], ordered[i + 1])
        for i in range(len(ordered) - 1)
        if ordered[i] is not None and ordered[i + 1] is not None
    ]
    if not valid_pairs:
        return 50.0

    bullish_pairs = sum(1 for a, b in valid_pairs if a > b)
    bearish_pairs = sum(1 for a, b in valid_pairs if a < b)
    total_pairs = len(valid_pairs)

    if bearish_pairs == total_pairs:
        score = 10.0  # 全空头
    elif bearish_pairs > bullish_pairs:
        score = 25.0  # 偏空
    elif bullish_pairs == bearish_pairs:
        score = 50.0  # 粘合
    elif bullish_pairs > bearish_pairs and bullish_pairs < total_pairs:
        score = 75.0  # 偏多
    else:
        score = 90.0  # 全多头

    # Price below MA20 penalty
    if price is not None and ma20 is not None and price < ma20:
        score = max(0, score - 10)

    return score


def _macd_subscore(indicators: dict[str, Any]) -> float:
    """MACD subscore based on DIF/DEA relationship and histogram."""
    macd_raw = indicators.get("macd") or indicators.get("MACD")
    if isinstance(macd_raw, dict):
        dif = macd_raw.get("MACD") or macd_raw.get("macd") or macd_raw.get("dif")
        dea = (
            macd_raw.get("signal") or macd_raw.get("MACD_signal") or macd_raw.get("dea")
        )
        hist = (
            macd_raw.get("histogram")
            or macd_raw.get("hist")
            or macd_raw.get("macd_hist")
        )
    else:
        dif = _safe_indicator_float(indicators, "MACD", "macd", "DIF", "dif")
        dea = _safe_indicator_float(
            indicators, "MACD_signal", "macd_signal", "DEA", "dea"
        )
        hist = _safe_indicator_float(indicators, "MACD_hist", "macd_hist", "histogram")

    try:
        dif_val = float(dif) if dif is not None else None
        dea_val = float(dea) if dea is not None else None
        hist_val = float(hist) if hist is not None else None
    except (TypeError, ValueError):
        return 50.0

    if dif_val is None and dea_val is None and hist_val is None:
        return 50.0

    # Base from DIF vs DEA
    if dif_val is not None and dea_val is not None:
        base = 60.0 if dif_val > dea_val else 40.0
    else:
        base = 50.0

    # Histogram adjustment
    if hist_val is not None:
        base += 15 if hist_val > 0 else -15

    # Both in negative territory or both positive
    if dif_val is not None and dea_val is not None:
        if dif_val < 0 and dea_val < 0:
            base -= 10
        elif dif_val > 0 and dea_val > 0:
            base += 10

    return max(0, min(100, base))


def _bb_position_score(indicators: dict[str, Any], price: float | None) -> float:
    """Bollinger Band position subscore."""
    bb_upper = _safe_indicator_float(indicators, "BB_upper", "bb_upper", "upper_band")
    bb_lower = _safe_indicator_float(indicators, "BB_lower", "bb_lower", "lower_band")
    bb_middle = _safe_indicator_float(
        indicators, "BB_middle", "bb_middle", "middle_band"
    )

    if price is None or bb_upper is None or bb_lower is None:
        return 50.0

    if bb_upper == bb_lower:
        return 50.0

    if price < bb_lower:
        return 20.0
    elif bb_middle is not None and price < bb_middle:
        return 35.0
    elif bb_middle is not None and abs(price - bb_middle) / bb_middle < 0.005:
        return 50.0
    elif bb_middle is not None and price > bb_middle and price < bb_upper:
        return 65.0
    elif price > bb_upper:
        return 80.0
    else:
        return 50.0


def _price_position_score(price: float | None, ma20: float | None) -> float:
    """Price position subscore: deviation from MA20 mapped to 0-100."""
    if price is None or ma20 is None or ma20 == 0:
        return 50.0
    # 50 + (price-MA20)/MA20 * 500, ±10% deviation maps to 0-100
    return max(0, min(100, 50 + (price - ma20) / ma20 * 500))


def _compute_tech_score(indicators: dict[str, Any], price: float | None) -> float:
    """Compute 5-subscore weighted technical score (0-100)."""
    # RSI subscore (25%) — existing mapping, no bias
    rsi = _safe_indicator_float(indicators, "rsi", "RSI")
    rsi_score = max(0, min(100, (rsi - 30) / 40 * 100)) if rsi is not None else 50.0

    # MA arrangement (30%)
    ma_score = _ma_arrangement_score(indicators, price)

    # MACD (25%)
    macd_score = _macd_subscore(indicators)

    # Bollinger Band position (10%)
    bb_score = _bb_position_score(indicators, price)

    # Price position vs MA20 (10%)
    ma20 = _safe_indicator_float(indicators, "MA_20", "ma20", "MA20")
    pp_score = _price_position_score(price, ma20)

    tech = (
        ma_score * 0.30
        + rsi_score * 0.25
        + macd_score * 0.25
        + bb_score * 0.10
        + pp_score * 0.10
    )
    return max(0, min(100, tech))


def compute_quant_signals(
    indicators: dict[str, Any] | None,
    strategy_signals: dict[str, Any] | None,
    bayesian: dict[str, Any] | None,
    *,
    current_price: float | None = None,
) -> dict[str, Any]:
    """Pre-compute quantitative signals for prompt injection (FR-PR008).

    System-computed values injected into the prompt so the LLM interprets
    rather than re-calculates.  tech_score uses 5-subscore weighted composite
    (MA arrangement 30%, RSI 25%, MACD 25%, Bollinger 10%, price position 10%)
    to eliminate the previous single-RSI bullish bias.

    Args:
        indicators: Technical indicator values from StrategyContextService.
        strategy_signals: Multi-strategy signal context.
        bayesian: Bayesian analysis context.
        current_price: Current stock price (keyword-only, optional).

    Returns:
        Dict with technical_score, momentum_score, bayesian_probability,
        strategy_consensus fields.
    """
    # --- Technical score (5-subscore weighted composite) ---
    tech_score = 50.0
    if indicators:
        tech_score = _compute_tech_score(indicators, current_price)

    # --- Momentum score ---
    momentum_score = 50.0
    if strategy_signals:
        signals = strategy_signals.get("signals", {})
        buy_count = 0
        sell_count = 0
        total = 0
        for _name, sig in signals.items():
            direction = sig.get("direction", "hold")
            strength = sig.get("strength", 0)
            total += 1
            if direction == "buy":
                buy_count += 1
                momentum_score += strength * 20
            elif direction == "sell":
                sell_count += 1
                momentum_score -= strength * 20
        momentum_score = max(0, min(100, momentum_score))

    # --- Bayesian probability ---
    bayesian_probability = 0.5
    if bayesian:
        composite = bayesian.get("composite", {})
        if composite:
            bayesian_probability = composite.get("confidence", 0.5)

    # --- Strategy consensus ---
    strategy_consensus = "无数据"
    if strategy_signals:
        consensus = strategy_signals.get("consensus", {})
        agreement = consensus.get("agreement", "")
        consensus_map = {
            "strong_bullish": "强烈看多共识",
            "strong_bearish": "强烈看空共识",
            "mixed": "信号混合",
            "divergent": "信号分歧",
        }
        strategy_consensus = consensus_map.get(agreement, agreement or "无数据")

    return {
        "technical_score": round(tech_score, 1),
        "momentum_score": round(momentum_score, 1),
        "bayesian_probability": round(bayesian_probability, 3),
        "strategy_consensus": strategy_consensus,
    }


def clamp_confidence(score: float, data_quality_score: int) -> float:
    """Clamp confidence based on data quality (FR-PR006).

    Args:
        score: Raw confidence score from LLM (0-1).
        data_quality_score: Data quality score (0-100).

    Returns:
        Clamped confidence score.
    """
    if data_quality_score >= 80:
        return score
    if data_quality_score >= 60:
        return min(score, 0.7)
    if data_quality_score >= 40:
        return min(score, 0.5)
    return min(score, 0.3)


_CONFIDENCE_LABELS = [
    (0.20, "极低(数据不足)"),
    (0.40, "低(信号模糊)"),
    (0.60, "中(存在分歧)"),
    (0.80, "较高(方向明确)"),
    (1.01, "高(多信号共振)"),
]


def get_confidence_label(score: float) -> str:
    """Map a float confidence to a five-level semantic label (FR-PR006).

    Args:
        score: Confidence score (0-1).

    Returns:
        Chinese label string.
    """
    for threshold, label in _CONFIDENCE_LABELS:
        if score < threshold:
            return label
    return "高(多信号共振)"


def format_quant_signals(quant: dict[str, Any]) -> str:
    """Format pre-computed quant signals for prompt injection (FR-PR008).

    Args:
        quant: Dict from compute_quant_signals().

    Returns:
        Formatted string for the user prompt.
    """
    return (
        f"技术面综合评分: {quant.get('technical_score', 50)}/100\n"
        f"动量因子评分: {quant.get('momentum_score', 50)}/100\n"
        f"贝叶斯上涨概率: {quant.get('bayesian_probability', 0.5):.1%}\n"
        f"策略共识: {quant.get('strategy_consensus', '无数据')}"
    )


def _format_yuan(value: Any, *, signed: bool = True) -> str:
    """Format a yuan value into human-readable string (亿/万).

    Args:
        value: Numeric value in yuan.
        signed: If True (default), prefix with +/- sign. If False, show
            absolute magnitude only (used when direction is in the label).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    fmt = "+.2f" if signed else ".2f"
    if abs(v) >= 1e8:
        return f"{v / 1e8:{fmt}}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:{fmt}}万"
    return f"{v:{fmt}}"


def format_fund_flow(fund_flow: dict[str, Any] | None) -> str:
    """Format fund flow data for unified prompt injection.

    Shows source label and per-order-size breakdown (super_large/large/
    medium/small) when available, in addition to the main_net aggregate.

    Args:
        fund_flow: Fund flow data dict or list.

    Returns:
        Formatted string for the user prompt.
    """
    import datetime as _dt

    if not fund_flow:
        return "无资金流向数据"

    # Handle both dict and list formats
    rows = fund_flow if isinstance(fund_flow, list) else [fund_flow]
    lines = []

    # Detect source from first row
    source = ""
    for row in rows[:1]:
        if isinstance(row, dict):
            src = row.get("_source", "")
            if src:
                source_labels = {
                    "eastmoney": "东方财富",
                    "eastmoney_adata": "东方财富",
                    "eastmoney_rank": "东方财富",
                    "baidu": "百度财经",
                }
                source = source_labels.get(src, src)
    if source:
        lines.append(f"[来源: {source}]")

    # Annotate when data is not from today
    today_str = _dt.date.today().isoformat()
    first_date = ""
    if rows and isinstance(rows[0], dict):
        first_date = str(rows[0].get("date", ""))[:10]
    if first_date and first_date != today_str:
        lines.append(f"[注意: 以下资金流向数据为 {first_date} 数据，非当日实时]")

    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        date = row.get("date", "")
        main = row.get("main_net", row.get("主力净流入", 0))
        try:
            main_val = float(main)
        except (TypeError, ValueError):
            main_val = 0.0
        main_direction = "净流入" if main_val >= 0 else "净流出"
        line = f"[{date}] 主力{main_direction}: {_format_yuan(abs(main_val), signed=False)}"

        # Per-order-size breakdown
        detail_parts = []
        for key, label in [
            ("super_large_net", "超大单"),
            ("large_net", "大单"),
            ("medium_net", "中单"),
            ("small_net", "小单"),
        ]:
            val = row.get(key)
            if val is not None:
                detail_parts.append(f"{label}{_format_yuan(val)}")
        if detail_parts:
            line += f" ({', '.join(detail_parts)})"

        retail = row.get("retail_net", row.get("散户净流入", ""))
        if retail:
            try:
                retail_val = float(retail)
            except (TypeError, ValueError):
                retail_val = 0.0
            retail_direction = "净流入" if retail_val >= 0 else "净流出"
            line += f", 散户{retail_direction}: {_format_yuan(abs(retail_val), signed=False)}"
        lines.append(line)
    return "\n".join(lines) if lines else "无资金流向数据"


def format_valuation(valuation: dict[str, Any] | None) -> str:
    """Format valuation indicators for unified prompt injection.

    Args:
        valuation: Valuation dict with pe_ttm, pb, ps_ttm, dv_ratio, total_mv.

    Returns:
        Formatted string for the user prompt.
    """
    if not valuation:
        return "无估值数据"

    lines: list[str] = []
    if "pe_ttm" in valuation:
        lines.append(f"PE(TTM): {valuation['pe_ttm']:.2f}")
    if "pb" in valuation:
        lines.append(f"PB: {valuation['pb']:.2f}")
    if "ps_ttm" in valuation:
        lines.append(f"PS(TTM): {valuation['ps_ttm']:.2f}")
    if "dv_ratio" in valuation:
        lines.append(f"股息率: {valuation['dv_ratio']:.2f}%")
    if "total_mv" in valuation:
        mv = valuation["total_mv"]
        if mv >= 1e8:
            lines.append(f"总市值: {mv / 1e8:.2f}亿")
        elif mv >= 1e4:
            lines.append(f"总市值: {mv / 1e4:.2f}万")
        else:
            lines.append(f"总市值: {mv:.2f}")

    return "\n".join(lines) if lines else "无估值数据"


def format_sector_info(sector_info: dict[str, Any] | None) -> str:
    """Format concept sector info for unified prompt injection.

    Args:
        sector_info: Sector info dict with concepts, resonance, industry.

    Returns:
        Formatted string for the user prompt.
    """
    if not sector_info:
        return "无概念板块数据"

    lines: list[str] = []
    industry = sector_info.get("industry", "")
    if industry:
        lines.append(f"行业: {industry}")

    concepts = sector_info.get("concepts", [])
    if concepts:
        lines.append(f"所属概念 (共 {len(concepts)} 个):")
        for c in concepts[:10]:
            name = c.get("name", "") if isinstance(c, dict) else str(c)
            pct = c.get("pct_change", 0) if isinstance(c, dict) else 0
            parts = [f"{name}: {pct:+.2f}%"]
            if isinstance(c, dict):
                zt = c.get("zt_count", 0)
                dt = c.get("dt_count", 0)
                if zt or dt:
                    limit_parts = []
                    if zt:
                        limit_parts.append(f"涨停{zt}")
                    if dt:
                        limit_parts.append(f"跌停{dt}")
                    parts.append(f"({'/'.join(limit_parts)})")
            lines.append(f"  - {' '.join(parts)}")

    resonance = sector_info.get("resonance", {})
    level = resonance.get("level", "none")
    if level != "none":
        lines.append(f"概念共振: {level}")

    return "\n".join(lines) if lines else "无概念板块数据"


def format_news_context(news_context: list[dict[str, Any]] | None) -> str:
    """Format news context for unified prompt injection.

    Args:
        news_context: List of matched news items.

    Returns:
        Formatted string for the user prompt.
    """
    if not news_context:
        return "无匹配舆情"
    lines = []
    for item in news_context[:8]:
        title = item.get("title", "")
        platform = item.get("platform", "")
        heat = item.get("heat_score", 0)
        lines.append(f"[{platform}] {title} (热度: {heat:.2f})")
    return "\n".join(lines)


def format_global_context(global_context: dict[str, Any] | None) -> str:
    """Format global market context for unified prompt injection.

    Args:
        global_context: Global market snapshot dict.

    Returns:
        Formatted string for the user prompt.
    """
    if not global_context:
        return "无全球市场数据"
    indices = global_context.get("indices", [])
    if not indices:
        return "无全球市场数据"
    lines = [
        f"{idx.get('name', '')}: {idx.get('change_pct', 0):+.2f}%"
        for idx in indices[:6]
    ]
    return " | ".join(lines)


def format_support_resistance(levels: list[dict[str, Any]] | None) -> str:
    """Format support/resistance levels for unified prompt injection.

    Args:
        levels: List of S/R level dicts with keys: level, type, touches.

    Returns:
        Formatted string for the user prompt.
    """
    if not levels:
        return "无支撑阻力位数据"

    lines: list[str] = []
    supports = [lv for lv in levels if lv.get("type") == "support"]
    resistances = [lv for lv in levels if lv.get("type") == "resistance"]

    if supports:
        s_str = ", ".join(
            f"{lv.get('level', 0):.2f}(触及{lv.get('touches', 0)}次)"
            for lv in sorted(supports, key=lambda x: x.get("level", 0), reverse=True)[
                :3
            ]
        )
        lines.append(f"支撑位: {s_str}")

    if resistances:
        r_str = ", ".join(
            f"{lv.get('level', 0):.2f}(触及{lv.get('touches', 0)}次)"
            for lv in sorted(resistances, key=lambda x: x.get("level", 0))[:3]
        )
        lines.append(f"阻力位: {r_str}")

    return "\n".join(lines) if lines else "无支撑阻力位数据"


def format_dragon_tiger(stats: list[dict[str, Any]] | None) -> str:
    """Format dragon-tiger (龙虎榜) stats for unified prompt injection.

    Args:
        stats: List of dragon-tiger stat records.

    Returns:
        Formatted string for the user prompt.
    """
    if not stats:
        return "近期未上龙虎榜"

    lines: list[str] = []
    for rec in stats[:3]:
        appearances = rec.get("appearances", rec.get("上榜次数", 0))
        net_amount = rec.get("net_amount", rec.get("机构净买额", 0))
        inst_net = rec.get("inst_net_amount", rec.get("机构买入额", 0))
        if net_amount:
            net_yi = net_amount / 1e8 if abs(net_amount) > 1e6 else net_amount
            lines.append(f"近三月上榜{appearances}次, 净买入{net_yi:.2f}亿")
            if inst_net:
                inst_yi = inst_net / 1e8 if abs(inst_net) > 1e6 else inst_net
                lines[-1] += f", 机构净买{inst_yi:.2f}亿"
        else:
            lines.append(f"近三月上榜{appearances}次")

    return "\n".join(lines) if lines else "近期未上龙虎榜"


def format_fund_flow_detail(detail: dict[str, Any] | None) -> str:
    """Format per-order-size fund flow detail for unified prompt injection.

    Args:
        detail: Fund flow detail dict with inflow/outflow by order size.

    Returns:
        Formatted string for the user prompt.
    """
    if not detail:
        return "无资金流明细数据"

    lines: list[str] = []

    # Try to extract per-size breakdown
    for size_key, size_label in [
        ("super_large", "超大单"),
        ("large", "大单"),
        ("medium", "中单"),
        ("small", "小单"),
    ]:
        inflow = detail.get(f"{size_key}_inflow", detail.get(f"{size_label}流入", None))
        outflow = detail.get(
            f"{size_key}_outflow", detail.get(f"{size_label}流出", None)
        )
        net = detail.get(f"{size_key}_net", detail.get(f"{size_label}净额", None))

        if net is not None:
            lines.append(f"{size_label}净额: {net}")
        elif inflow is not None and outflow is not None:
            lines.append(f"{size_label}: 流入{inflow}, 流出{outflow}")

    # Fallback: try aggregate fields
    if not lines:
        net = detail.get("net", detail.get("净额", None))
        inflow = detail.get("inflow", detail.get("流入", None))
        outflow = detail.get("outflow", detail.get("流出", None))
        if net is not None:
            lines.append(f"净额: {net}")
        if inflow is not None:
            lines.append(f"总流入: {inflow}")
        if outflow is not None:
            lines.append(f"总流出: {outflow}")

    return "\n".join(lines) if lines else "无资金流明细数据"


_SECTOR_ANALYSIS_HINTS: dict[str, str] = {
    "银行": (
        "行业特化: 银行股应使用PB(而非PE)作为核心估值指标。"
        "关注净息差(NIM)、不良贷款率(NPL)、拨备覆盖率等银行业核心指标。"
        "银行PE普遍偏低(5-8x)属于行业特性，不等于低估。"
    ),
    "医药": (
        "行业特化: 医药股估值应关注研发管线价值和临床进度，而非仅看当期利润。"
        "创新药企亏损期PE无意义，应关注PB和研发占比。"
        "注意集采政策对仿制药企业的压缩效应。"
    ),
    "房地产": (
        "行业特化: 地产股应重点关注预售数据、土地储备、现金短债比。"
        "高度关注债务风险和再融资能力。PE/PB可能因会计处理失真。"
        "政策变动（限购限贷）对行业影响极大。"
    ),
    "有色金属": (
        "行业特化: 有色金属股的核心驱动因素是大宗商品价格走势。"
        "关注伦铜/沪铜、伦铝、黄金等关联品种价格。"
        "周期性强，盈利波动大，PE在周期底部可能虚高。"
    ),
    "石油石化": (
        "行业特化: 能源股核心驱动是国际油价走势。"
        "关注OPEC+产量政策、全球需求预期和地缘政治风险。"
        "周期性强，高油价时的高利润不可简单线性外推。"
    ),
    "半导体": (
        "行业特化: 半导体行业应关注国产替代进度和研发投入占比。"
        "估值容忍度较高，PEG比PE更有参考价值。"
        "注意区分设计/制造/封测/设备等细分环节的差异。"
    ),
    "煤炭": (
        "行业特化: 煤炭股核心驱动是动力煤/焦煤价格和长协比例。"
        "关注安全生产政策和产能释放节奏。"
        "高分红是行业特色，但需关注价格下行周期的盈利韧性。"
    ),
}


def format_limit_constraint(quote: dict[str, Any] | None, price_limit: str) -> str:
    """Generate dynamic constraint text when stock is at price limit.

    Args:
        quote: Real-time quote dict with keys: price, high_limit, low_limit,
            or pct_change.
        price_limit: Board price limit string (e.g. "±10%", "±20%").

    Returns:
        Constraint string for prompt injection, or empty string if not at limit.
    """
    if not quote:
        return ""

    pct = quote.get("pct_change", 0)
    try:
        pct_val = float(pct)
    except (TypeError, ValueError):
        return ""

    price = quote.get("price")
    high_limit = quote.get("high_limit") or quote.get("涨停价")
    low_limit = quote.get("low_limit") or quote.get("跌停价")

    at_upper = False
    at_lower = False

    # Check by price == limit price
    if price and high_limit:
        try:
            at_upper = abs(float(price) - float(high_limit)) < 0.01
        except (TypeError, ValueError):
            pass
    if price and low_limit:
        try:
            at_lower = abs(float(price) - float(low_limit)) < 0.01
        except (TypeError, ValueError):
            pass

    # Fallback: check by pct_change threshold
    if not at_upper and not at_lower:
        # Parse limit percentage from price_limit string
        try:
            limit_pct = float(price_limit.replace("±", "").replace("%", ""))
        except (TypeError, ValueError):
            limit_pct = 10.0
        if pct_val >= limit_pct - 0.5:
            at_upper = True
        elif pct_val <= -(limit_pct - 0.5):
            at_lower = True

    if at_upper:
        return (
            "⚠ 涨停约束: 该股当前处于涨停状态。"
            "追涨风险极高；T+1制度下无法当日卖出；"
            "confidence需 >= 0.7 且有明确催化剂才可建议买入。"
            "需警惕次日开板回落风险。"
        )
    if at_lower:
        return (
            "⚠ 跌停约束: 该股当前处于跌停状态。"
            "已持仓可能因封单无法卖出；不应建议抄底跌停股；"
            "应重点关注跌停原因（利空、主力出逃、系统性风险等）。"
            "action建议为watch或hold（已持仓）。"
        )

    return ""


def format_sector_analysis_hint(industry: str) -> str:
    """Generate sector-specific analysis hint based on industry classification.

    Args:
        industry: Industry name from sector_info (e.g. "银行", "医药").

    Returns:
        Sector-specific analysis hint, or empty string if no match.
    """
    if not industry:
        return ""
    # Direct match first
    hint = _SECTOR_ANALYSIS_HINTS.get(industry)
    if hint:
        return hint
    # Partial match (e.g. "有色金属开采" matches "有色金属")
    for key, val in _SECTOR_ANALYSIS_HINTS.items():
        if key in industry or industry in key:
            return val
    return ""


def format_divergence_signals(signals: list[dict[str, Any]] | None) -> str:
    """Format price-flow divergence signals for unified prompt injection.

    Args:
        signals: List of divergence signal dicts.

    Returns:
        Formatted string for the user prompt.
    """
    if not signals:
        return ""

    lines: list[str] = []
    for sig in signals:
        desc = sig.get("description", "")
        severity = sig.get("severity", "warning")
        severity_label = "⚠️ 预警" if severity == "warning" else "🔴 警报"
        if desc:
            lines.append(f"{severity_label}: {desc}")

    return "\n".join(lines) if lines else ""
