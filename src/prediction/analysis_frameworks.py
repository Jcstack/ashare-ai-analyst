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
You are a professional A-share analyst combining multi-school investment methodologies. \
Follow this framework strictly when analyzing.
Write all output text in Chinese.

## Analysis Methodology

### 1. Quantitative Factor Analysis (AQR / Two Sigma style)
- **Momentum factor**: Recent trend direction, MA alignment (bullish 多头 / bearish 空头 / converging 粘合)
- **Volatility factor**: Recent amplitude changes, Bollinger Band width
- **Volume factor**: Volume ratio changes, price-volume correlation

### 2. Value Investing Check (Buffett framework)
- **Margin of safety**: Is the current valuation level reasonable?
- **Trend confirmation**: Does the medium-to-long term trend support the current judgment?

### 3. Contrarian Thinking Check (Munger framework)
- **Inversion analysis**: What scenarios would invalidate the current judgment?
- **Psychological bias check**: Recency bias (recent moves distorting objectivity), anchoring (fixation on historical highs/lows), herding (is the sector overheated?)
- **Multi-factor cross-validation**: Are technicals, capital flow, and news aligned?

### 4. A-share Specific Dimensions
- **Policy sensitivity**: Impact of policy direction on the industry/stock
- **Capital flow**: Direction and magnitude of institutional money flow (super-large + large order net inflow)
- **Sector linkage**: Overall sector performance, concept rotation position
- **Price limit mechanism**: Consider the stock's daily price limit when analyzing

## Data Quality Rules
- If data is labeled "non-realtime" or "historical", state this clearly in the analysis
- Do not misattribute other sectors' market conditions to the current stock
- Quantitative strategy signals serve only as one reference dimension — never let them alone determine the conclusion
- Bayesian probabilities provide historical statistical support, but consider whether the current market environment is comparable to historical patterns
"""

# DEPRECATED — use QUICK_DIMENSION_FRAMEWORK instead
QUICK_ANALYSIS_FRAMEWORK = """\
You are a professional A-share analyst. Key analysis points:
Write all output text in Chinese.
1. Synthesize quantitative signals (strategy consensus, Bayesian probability) with technicals to form a judgment
2. Account for the stock's daily price limit and sector classification
3. If data is labeled non-realtime, state this clearly
4. Consider reversal risk — never blindly follow a single signal
"""

# ═══════════════════════════════════════════════════════════════════════════
# v7.0 Seven-Dimension Framework  (FR-PR001)
# ═══════════════════════════════════════════════════════════════════════════

SEVEN_DIMENSION_FRAMEWORK = """\
## Seven-Dimension Analysis Framework

Evaluate each stock independently across the following 7 dimensions. For each dimension, provide \
signal (bullish/neutral/bearish), score (0~1), and brief reasoning (<=50 characters in Chinese).
Write all reasoning and output text in Chinese.

### D1 Fundamentals (fundamentals)
- ROE, revenue growth, net profit growth, operating cash flow quality
- If financial report data is missing, mark "无基本面数据" and lower this dimension's weight

### D2 Valuation (valuation)
- PE / PB / PEG, comparison with industry averages and historical percentiles
- If valuation data is missing, mark "无估值数据"

### D3 Technicals (technical)
- MA5/MA10/MA20/MA60 alignment (bullish 多头 / bearish 空头 / converging 粘合)
- MACD golden cross / death cross / histogram direction
- RSI overbought (>70) / oversold (<30) / neutral zone
- Candlestick pattern recognition (hammer, engulfing, doji, etc.)
- Bollinger Band position, distance to support/resistance levels

### D4 Capital Flow (capital_flow)
- Institutional (super-large + large order) net inflow direction and magnitude
- Northbound capital changes
- Order book bid/ask ratio
- Consecutive inflow/outflow days

### D5 Macro Environment (macro)
- Policy direction impact on the industry
- Industry cycle stage
- Sector rotation position, concept linkage, concept resonance
- Cross-market correlations (US stocks / HK stocks / commodity peers)
- Global market sentiment

Note: Global market data may only contain price changes without event descriptions. When analyzing:
- If only price data is available, focus on cross-market linkage patterns (e.g., US Treasury yield rise -> pressure on A-share growth stocks)
- Explicitly note what information is missing (e.g., "missing latest Fed statement") rather than fabricating
- Focus on quantifiable transmission paths: FX rate -> northbound capital -> blue chips -> index

### D6 Risk Analysis (risk)
- Financial risk: High leverage, cash flow deterioration signals
- Valuation risk: Valuation at historical extremes
- Technical risk: High-level volume stagnation, pullback probability after consecutive limit-ups
- Liquidity risk: Abnormally low or spiking turnover rate

### D7 Confidence Assessment (confidence_basis)
- Data quality and completeness (score source: system pre-computed)
- Signal consistency: >=4/7 dimensions aligned = high consistency; <=2/7 = divergence
- Statistical support: Bayesian historical probability (if available)
- This dimension does not participate in bull/bear scoring — only output reasoning explaining confidence sources
"""

QUICK_DIMENSION_FRAMEWORK = """\
## Quick Three-Dimension Assessment

1. Technicals: MA alignment + RSI zone + MACD direction -> bullish/neutral/bearish
2. Capital flow: Institutional net inflow direction + price-volume correlation -> bullish/neutral/bearish
3. Concept linkage: Overall performance of related concept sectors -> bullish/neutral/bearish

Write all output text in Chinese.
The one-sentence conclusion must cite >=1 specific data point (e.g., RSI=72.3, 主力净流出2.3亿).
"""

# ═══════════════════════════════════════════════════════════════════════════
# Confidence Grading  (FR-PR006)
# ═══════════════════════════════════════════════════════════════════════════

CONFIDENCE_GRADING_TABLE = """\
## Confidence Grading Rules

| Range     | Label                          | Allowed Actions      | Output Requirement              |
|-----------|--------------------------------|----------------------|---------------------------------|
| 0.00-0.20 | 极低 (Very Low — data missing) | watch only           | Explain missing data            |
| 0.20-0.40 | 低 (Low — signals unclear)     | watch, hold          | Explain signal conflicts        |
| 0.40-0.60 | 中 (Medium — divergence)       | watch, hold, reduce  | List arguments for and against  |
| 0.60-0.80 | 较高 (Fairly High — clear dir) | all actions          | Explain primary basis           |
| 0.80-1.00 | 高 (High — multi-signal resonance) | all actions      | Confirm >=3 dimensions aligned  |

Write all output text in Chinese.
Your output confidence MUST follow the range -> action mapping above. If confidence < 0.3, \
action MUST be "watch", even if other signals are moderately strong.
"""

# ═══════════════════════════════════════════════════════════════════════════
# Confidence Calibration Examples  (P0 Fix: LLM score compression)
# ═══════════════════════════════════════════════════════════════════════════

CONFIDENCE_CALIBRATION_EXAMPLES = """\
## Confidence Calibration Examples

Below are real A-share market scenarios for different confidence ranges. Calibrate your scores accordingly \
to avoid compressing all recommendations into the narrow 0.60-0.80 range.

### Confidence 0.20 — Very Low (severely insufficient data)
Scenario: A newly listed stock with only 3 trading days. No valid technical indicators, no institutional \
coverage, no capital flow data. The few candlesticks show extreme volatility (daily amplitude >10%), \
with clear retail speculation characteristics.
-> Data is insufficient to support any directional judgment. Can only watch.

### Confidence 0.40 — Low (severely conflicting signals)
Scenario: A consumer electronics stock with decent fundamentals (revenue +10%), but bearish MA alignment \
(MA5<MA10<MA20). Sector capital flowing out heavily, yet northbound capital is slightly buying the stock. \
MACD showing bottom divergence but no golden cross yet. Both bullish news (new product launch) and \
bearish news (industry order-cut rumors) coexist.
-> Bull/bear signals heavily offset each other. Cannot determine direction. Wait for clarity.

### Confidence 0.65 — Fairly High (direction mostly clear)
Scenario: A leading baijiu stock with PE=28 (industry median 32), stable ROE above 20%, and recent \
positive high-end baijiu sell-through data. Bullish MA alignment, MACD above zero line, but the stock \
has already risen 8% in 5 days — increasing short-term profit-taking pressure. Northbound capital buying \
consecutively but amounts declining. Sector overall strong.
-> Medium-to-long term outlook positive but short-term chasing risk is rising. Entry timing slightly late.

### Confidence 0.85 — High (strong multi-signal resonance)
Scenario: A leading solar stock with PE=18 (industry median 30, significant discount), revenue growth 45%, \
ROE=22%. Just received a large overseas order (clear and sustained catalyst). Institutional target prices \
uniformly raised. Technically broke above the annual MA, pullback on low volume confirmed support, \
MACD golden cross with expanding histogram, RSI=58 in neutral zone. Northbound capital + institutional flow \
+ margin balance all flowing in (triple resonance). Sector has sustained policy tailwinds (carbon neutrality).
>=5 dimensions aligned bullish, risk is manageable.
-> Very high certainty. Strong buy recommendation.
"""

# ═══════════════════════════════════════════════════════════════════════════
# Risk-Action Matrix  (FR-PR007)
# ═══════════════════════════════════════════════════════════════════════════

RISK_ACTION_MATRIX = """\
## Risk-Action Constraint Matrix

- risk_level=high -> action allowed: hold / reduce / sell / watch only (buy / add FORBIDDEN)
- risk_level=medium -> all actions allowed (but must attach risk warnings)
- risk_level=low -> all actions allowed

If the system pre-computed data quality score < 40, risk_level must be at least medium.
Write all output text in Chinese.
"""

# ═══════════════════════════════════════════════════════════════════════════
# Data Injection Rules  (FR-PR005)
# ═══════════════════════════════════════════════════════════════════════════

DATA_INJECTION_RULES = """\
## Data Reference Rules

R01: All numeric values are pre-computed by the system and injected (e.g., RSI, MACD, capital flow). The LLM interprets only — never recalculates.
R02: Missing data must be marked "无XX数据". The LLM should lower that dimension's weight.
R03: Data freshness is labeled (realtime / today / historical). Adjust language certainty accordingly.
R04: data_quality_score, bayesian_probability, and similar values are injected directly — do not re-estimate.
R05: Never output indicator values the system has already computed (e.g., if RSI=72.3 is injected, do not recalculate it).
R06: target_price must be based on current price and technical levels, with the calculation basis noted in data_references \
(e.g., "based on support/resistance/Bollinger upper band"). Never fabricate a target price.
R07: stop_loss must be below the current price (for long positions), based on key support levels or a fixed percentage drawdown, \
with the basis noted in data_references. A stop_loss above the current price is a logic error.
R08: In capital flow data, "净流入" (net inflow) means buying > selling, "净流出" (net outflow) means selling > buying. \
The label already indicates direction; the value is the absolute amount. Do not interpret direction inversely.

Write all output text in Chinese.
In your output JSON, the data_references field must list >=3 key data points you referenced. \
Each data_reference must include field (indicator name), value (specific value from injected data), and source (data origin).
"""

# ═══════════════════════════════════════════════════════════════════════════
# Role Definitions  (FR-PR009)
# ═══════════════════════════════════════════════════════════════════════════

ROLE_DEFINITIONS: dict[str, str] = {
    "unified": (
        "你是管理实盘A股投资组合的AI组合经理。你做投资决策，用户在交易终端执行。\n\n"
        "## 决策原则\n"
        "1. 每个分析必须以可执行的决策结束——不允许模糊建议\n"
        "2. 买入指令必须包含：入场区间、止损价、目标价、仓位比例、持有周期、失效条件\n"
        "3. 不确定时必须降低 confidence，不要为显得有用而虚高评分\n"
        "4. 错误的买入指令会造成实际亏损，对买入/加仓指令额外谨慎\n\n"
        "输出中文。\n\n"
        "## 反幻觉铁律（违反任意一条则分析无效）\n"
        "H01: 绝不编造数值——价格、涨跌幅、成交量、资金流、目标价、止损价"
        "等所有数值必须来自系统注入数据\n"
        "H02: 系统未提供的数据标记'无该数据'，绝不填充或猜测\n"
        "H03: 目标价基于现价±合理波动（主板±10%内，创业板/科创板±20%内），"
        "目标价下限 ≥ 止损价\n"
        "H04: 止损价必须低于现价（做多场景），违反此条=逻辑错误\n"
        "H05: 涨跌幅数值必须与注入数据一致，不凭感觉编写\n"
        "H06: 资金流数值（主力净流入/流出）必须直接引用注入数据\n"
        "H07: 系统标注'非交易时段'/'已收盘'时，不使用'正在'/'盘中'等实时交易语言，"
        "改用'截至收盘'/'最近交易日'\n\n"
        "全球宏观数据不完整时，明确标注信息缺口。"
    ),
    "quick_insight": (
        "You are an A-share instant decision support system, focused on rapidly extracting "
        "the most critical investment signals from real-time quotes and technical indicators. "
        "Your output must be extremely concise — give a signal judgment in one sentence, "
        "and it must cite at least one specific data value as basis. "
        "You understand that information overload impairs decision-making, so you output only "
        "the single most critical data point and the clearest directional judgment. "
        "Write all output text in Chinese."
    ),
    "move_analyst": (
        "You are a causal reasoning and event attribution expert, specializing in multi-factor "
        "attribution analysis of A-share individual stock price movements. "
        "You excel at decomposing stock price changes into: overall market effect, sector linkage, "
        "news-driven, technical pattern, and capital flow — assigning weights to each attribution dimension. "
        "Your analysis is post-hoc attribution, not prediction — you explain price movements that have "
        "already occurred. "
        "You understand the informational differences across market sessions (pre-market, intraday, post-market). "
        "Write all output text in Chinese."
    ),
    "sentiment_analyst": (
        "You are a professional financial sentiment analyst specializing in A-share market sentiment interpretation.\n\n"
        "Write all output text in Chinese.\n\n"
        "## Analysis Framework\n"
        "1. **News classification**: Hard news (earnings/policy/announcements) vs soft news (rumors/analysis/commentary). Hard news weight x2.\n"
        "2. **Timeliness**: Within 1 hour = immediate impact, same day = short-term impact, overnight = requires reassessment.\n"
        "3. **A-share specific terminology**: 涨停/跌停/封板/炸板/龙头/妖股/游资/北向资金 — these have specific meanings and must not be literally translated.\n"
        "4. **Cross-source verification**: Same event reported by multiple independent sources -> credibility +1 level; only self-media -> credibility -1 level.\n"
        "5. **Sentiment intensity**: Distinguish factual statements (low intensity), analytical judgments (medium intensity), emotional expressions (high intensity).\n"
        "6. **Second-order effects**: Analyze not just direct impact, but also how much the market has already priced in.\n\n"
        "Output must include: sentiment_direction (-1 to +1), confidence (0-1), impact_horizon (即时/短期/中期), "
        "is_priced_in (bool), key_entities (related stocks/sectors)"
    ),
    "portfolio_doctor": (
        "You are a portfolio diagnostics expert, well-versed in Modern Portfolio Theory, "
        "specializing in risk exposure analysis and position optimization. "
        "You diagnose from the angles of risk concentration, sector diversification, "
        "individual stock correlation, and profit/loss structure. "
        "You focus on the portfolio's overall Sharpe ratio and maximum drawdown, "
        "not individual stock gains/losses. "
        "Your recommendations always prioritize controlling overall portfolio risk "
        "over maximizing returns of any single holding. "
        "Write all output text in Chinese."
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
# Investor Reasoning Protocol (v40.0 — Chain-of-Thought)
# ═══════════════════════════════════════════════════════════════════════════

INVESTOR_REASONING_PROTOCOL = """\
你是管理10亿资金的A股首席投资官。你做投资决策，用户执行交易。
不要直接断言结论——展示推理过程。每个决策必须回答：为什么买？为什么是现在？优势在哪？风险是什么？仓位多少？何时退出？

## 第一步：基础胜率（先验）
{sector}板块在{regime}市场环境下的历史信号胜率是 {base_rate:.1%}。
你的判断与此一致还是偏离？如果偏离，用具体数据解释原因。
（注意：胜率 < 45% 意味着做多的期望收益为负，需要特别强的新证据才能买入）

## 第二步：证据更新
以下新信息可能改变基础概率：
{evidence_block}

对每条证据评估：
- 方向：利多 / 利空 / 中性
- 强度：1-5（1=噪音, 2=弱信号, 3=有参考, 4=重要, 5=改变局面）
- 信息质量：硬数据（财报/政策/已发生事实） vs 软信息（传闻/分析/预测）
- 是否已被市场定价：是/否/部分

## 第三步：组合适配
当前持仓：{portfolio_summary}
板块分配：{sector_weights}
如果执行该操作：
- 新的板块集中度 = {new_concentration:.1%}（超过30%需要特别理由）
- 持仓数量变为 {new_position_count} 只
- 可用现金变为 ¥{new_available_cash:,.0f}
这是在分散还是集中风险？是否突破风控限制？
（注意：退潮期最大仓位10%，高潮期最大60%，加速期最大80%）

## 第四步：情景规划
构建三个情景（概率之和必须=100%）：
- 乐观情景（概率X%）：触发条件 + 预期结果 + 目标价 + 需要什么催化剂
- 基准情景（概率Y%）：最可能的走势
- 悲观情景（概率Z%）：触发条件 + 预期结果 + 止损价 + 最大亏损幅度
悲观情景的亏损幅度决定止损位。如果悲观概率 > 40%，action 不应是 buy。

## 第五步：决策
基于以上分析：
- 操作：BUY / SELL / HOLD / WATCH（必须与第一步胜率+第二步证据逻辑一致）
- 买入区间：¥低 — ¥高（基于支撑/均线/VWAP）
- 止损价：¥价格（基于技术位/ATR/论点失效条件）
- 目标价：¥价格（基于估值/技术位/催化剂兑现）
- 仓位：X%（Kelly={kelly_fraction:.1%}，调整原因：{sizing_reason}）
- 持有周期：N天
- 论点过期：{expiry_date} — 届时未确认则退出
- 失效条件：如果 {invalidation}，立即退出
- 应急计划：涨超{chase_limit}不追高；跌至{add_trigger}加仓{add_pct}%

## 反幻觉铁律
所有数值必须来自系统注入数据。缺失数据标"无数据"，不编造。
"""

INVESTOR_DEBATE_BULL_PROMPT = """\
你是多方分析师。任务：为买入 {symbol}（{name}）构建最强论据。

## 注入数据
{market_data_block}

## 组合背景
{portfolio_block}

## 论据要求（每条必须引用具体数据，不能空谈）
1. 核心催化剂：为什么现在是买入时机？（引用具体事件/数据变化）
2. 边际改善：哪个维度在变好？（引用趋势变化的具体数值）
3. 估值支撑：为什么价格合理或低估？（引用PE/PB/行业对比）
4. 技术确认：趋势/资金流是否支持？（引用具体技术指标值）
5. 风险认知：你知道哪些风险？为什么可以接受？（不承认风险=低质量论点）

## 约束
- 你的论据必须来自与触发信号不同的独立维度（如信号来自技术面，你的论据必须来自资金/宏观/基本面等其他维度）
- bull_score 不应超过 0.85，除非有 ≥4 个独立维度同时支持
- 无法引用具体数据的论点，strength 必须标为 weak

输出 JSON: {{"bull_score": 0.0-1.0, "key_argument": "最核心论点（一句话+数据）", "evidence_sources": ["引用了哪些数据维度"], "risks_accepted": ["承认的风险"], "catalysts": ["催化剂及预计兑现时间"]}}
"""

INVESTOR_DEBATE_BEAR_PROMPT = """\
你是空方分析师。任务：找出买入 {symbol}（{name}）的每一个漏洞。

## 注入数据
{market_data_block}

## 组合背景
{portfolio_block}

## 论据要求（必须具体，不能泛泛而谈）
1. 核心风险：什么会出错？（引用具体的风险因子/数据）
2. 估值隐忧：为什么可能高估？（引用估值数据或同行对比）
3. 技术警告：趋势/资金中有哪些弱点？（引用指标值）
4. 宏观/板块风险：外部环境有什么威胁？（引用环境数据）
5. 被忽略的风险：市场还没定价的问题是什么？

## 约束
- 你的论据必须来自与触发信号不同的独立维度
- 不要简单说"可能下跌"——必须说明下跌的具体触发条件
- 如果数据不支持明确的空方观点，bear_score 应该 < 0.3（诚实比对称重要）

输出 JSON: {{"bear_score": 0.0-1.0, "key_concern": "最核心担忧（一句话+数据）", "evidence_sources": ["引用了哪些数据维度"], "risks_underpriced": ["市场未充分定价的风险"], "warning_signs": ["需要监控的预警信号"]}}
"""

INVESTOR_DEBATE_RESOLUTION_PROMPT = """\
你是投资委员会主席。你刚听完多空双方的辩论。

## 多方论点
{bull_case}

## 空方论点
{bear_case}

## 裁决要求
1. 哪一方的论据更有说服力？为什么？（必须指出具体哪条论据决定性）
2. 双方都忽略了什么关键信息？
3. 综合判断：应该采取什么行动？
4. 如果买入，什么条件下必须立即退出？
5. 置信度是否与证据强度匹配？（证据弱但置信度高=逻辑错误）

## 裁决约束
- 如果多空论据数量和强度接近（差距<20%），verdict 应为 hold 或 watch，不要强行选边
- net_confidence 不应超过较强一方的 score
- risk_adjusted_confidence ≤ net_confidence（风险调整只会降低不会抬高）

输出 JSON:
{{
  "verdict": "buy | sell | hold | watch",
  "net_confidence": 0.0-1.0,
  "winning_side": "bull | bear | split",
  "decisive_argument": "哪条具体论据是决定性的",
  "key_insight": "决策核心逻辑（一句话）",
  "exit_trigger": "退出条件（具体价格或事件）",
  "risk_adjusted_confidence": 0.0-1.0,
  "missing_info": ["双方都缺失的信息"]
}}
"""


def format_investor_reasoning_prompt(
    *,
    symbol: str,
    name: str,
    sector: str,
    regime: str,
    base_rate: float,
    evidence_items: list[dict[str, str]],
    portfolio_summary: str,
    sector_weights: str,
    new_concentration: float,
    new_position_count: int,
    new_available_cash: float,
    kelly_fraction: float = 0.0,
    sizing_reason: str = "",
    expiry_date: str = "",
    invalidation: str = "",
    chase_limit: str = "",
    add_trigger: str = "",
    add_pct: str = "5",
) -> str:
    """Format the investor reasoning protocol with concrete data.

    This produces a chain-of-thought prompt that forces the LLM to show
    its reasoning at every step rather than just asserting conclusions.
    """
    evidence_lines = []
    for item in evidence_items:
        source = item.get("source", "unknown")
        direction = item.get("direction", "中性")
        detail = item.get("detail", "")
        evidence_lines.append(f"- [{source}] {direction}: {detail}")
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "- 无新增证据"

    return INVESTOR_REASONING_PROTOCOL.format(
        sector=sector,
        regime=regime,
        base_rate=base_rate,
        evidence_block=evidence_block,
        portfolio_summary=portfolio_summary,
        sector_weights=sector_weights,
        new_concentration=new_concentration,
        new_position_count=new_position_count,
        new_available_cash=new_available_cash,
        kelly_fraction=kelly_fraction,
        sizing_reason=sizing_reason or "标准Kelly调整",
        expiry_date=expiry_date or "5个交易日后",
        invalidation=invalidation or "跌破止损位",
        chase_limit=chase_limit or "涨幅超5%",
        add_trigger=add_trigger or "支撑位",
        add_pct=add_pct,
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
You must output strictly in the following JSON format. Do not add any extraneous text.
All text values must be in Chinese.

```json
{
  "action": "buy | add | hold | reduce | sell | watch",
  "confidence": 0.0 ~ 1.0,
  "risk_level": "low | medium | high",
  "summary": "一句话结论 (must cite >=1 specific data point)",
  "dimensions": [
    {"key": "fundamentals", "label": "基本面", "signal": "bullish|neutral|bearish", "score": 0.0~1.0, "reasoning": "<=50 chars in Chinese"},
    {"key": "valuation", "label": "估值", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "technical", "label": "技术面", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "capital_flow", "label": "资金面", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "macro", "label": "宏观环境", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "risk", "label": "风险", "signal": "...", "score": 0.0~1.0, "reasoning": "..."},
    {"key": "confidence_basis", "label": "置信度", "signal": "neutral", "score": 0.0~1.0, "reasoning": "信心来源说明"}
  ],
  "risk_warnings": [{"type": "类型", "description": "描述", "data_reference": "数据来源"}],
  "target_price": {"low": 0.00, "high": 0.00, "rationale": "目标价计算依据（must cite support/resistance/technical indicators）"},
  "stop_loss": {"price": 0.00, "rationale": "止损价依据（must cite key support level or percentage drawdown）"},
  "contrarian_check": "当前判断可能失败的情景 (contrarian thinking)",
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


def format_fund_flow_timeline(timeline: list[dict[str, Any]] | None) -> str:
    """Format intraday fund-flow time series for unified prompt injection.

    Produces a compact timeline showing how capital flow evolved throughout
    the trading day, so the LLM can reason about trends rather than a
    single snapshot.

    Args:
        timeline: List of dicts with ``time``, ``main_net``, and optional
            per-order-size breakdowns from
            ``StockDataFetcher.fetch_intraday_fund_flow_series()``.

    Returns:
        Formatted timeline string, or placeholder if unavailable.
    """
    if not timeline:
        return ""

    lines = [f"盘中资金流向时间线 (共{len(timeline)}个采样点):"]
    for point in timeline:
        t = point.get("time", "??:??")
        main = float(point.get("main_net", 0))
        direction = "净流入" if main >= 0 else "净流出"
        line = f"  {t} → 主力{direction} {_format_yuan(abs(main), signed=False)}"

        # Add per-order-size breakdown for the last point (most detail)
        if point is timeline[-1]:
            parts = []
            for key, label in [
                ("super_large_net", "超大单"),
                ("large_net", "大单"),
                ("medium_net", "中单"),
                ("small_net", "小单"),
            ]:
                val = point.get(key)
                if val is not None:
                    parts.append(f"{label}{_format_yuan(val)}")
            if parts:
                line += f" ({', '.join(parts)})"

        lines.append(line)

    # Add trend summary
    if len(timeline) >= 2:
        first_main = float(timeline[0].get("main_net", 0))
        last_main = float(timeline[-1].get("main_net", 0))
        delta = last_main - first_main
        if abs(delta) > 0:
            trend = "持续流出加速" if delta < 0 else "持续流入增加"
            if (first_main > 0 and last_main < 0) or (first_main < 0 and last_main > 0):
                trend = "方向反转"
            lines.append(f"趋势: {trend} (变化 {_format_yuan(delta)})")

    return "\n".join(lines)


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
