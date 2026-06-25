"""LLM review agent for stock recommendation candidates.

Follows TradingAdvisor's dual-layer pattern: system prompt + structured JSON output.
Reviews screened candidates and produces finalized Recommendation objects.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from src.recommendation.models import Recommendation, StockCandidate

logger = logging.getLogger(__name__)

# Score thresholds (intentionally distinct, not a bug):
#   - LLM-reviewed path keeps only buy-grade candidates (>= BUY).
#   - The no-LLM fallback is more lenient and keeps watch-grade candidates
#     (>= WATCH) since it has no model to assign a finer action.
BUY_SCORE_THRESHOLD = 0.65
WATCH_SCORE_THRESHOLD = 0.55

_STYLE_PROMPTS: dict[str, str] = {
    "value": (
        "你是一位拥有20年经验的价值投资分析师，专精A股市场基本面研究。\n\n"
        "你的分析框架：\n"
        "1. 估值安全边际：PE/PB相对行业中位数的折价程度，而非绝对值。"
        "银行PE=5不等于便宜——要与银行业中位数比较。\n"
        "2. 盈利质量：关注ROE稳定性、现金流/净利润比率。\n"
        "3. 护城河评估：品牌力、转换成本、网络效应。\n"
        "4. 风险收益比：目标价至少30%上行空间，止损8-10%。\n\n"
        "重要原则：避免同质化推荐，低PE不是唯一标准。不同行业的合理PE差异巨大，"
        "消费品PE=25可能比银行PE=5更有投资价值。"
    ),
    "growth": (
        "你是一位专注成长股投资的资深分析师，擅长识别高增长潜力企业。\n\n"
        "你的分析框架：\n"
        "1. 增长质量：营收增速与利润增速是否匹配，警惕增收不增利。\n"
        "2. 行业天花板：所在赛道的市场空间和渗透率。\n"
        "3. 竞争壁垒：技术壁垒、规模效应、先发优势。\n"
        "4. 估值容忍度：PEG<1.5为合理，但需结合行业成长确定性。\n\n"
        "重要原则：成长股看的是未来而非当下，但也要警惕概念炒作。"
        "优先选择有真实业绩兑现的标的，而非纯故事驱动。"
    ),
    "momentum": (
        "你是一位量化动量交易专家，精通A股市场短期价格行为分析。\n\n"
        "你的分析框架：\n"
        "1. 趋势强度：价格是否突破关键均线，量能是否有效放大。\n"
        "2. 资金流向：换手率变化、大单净流入方向。\n"
        "3. 板块共振：个股动量是否有板块效应支撑。\n"
        "4. 买入时机：突破回踩确认优于追高，止损控制在3-5%。\n\n"
        "重要原则：动量不等于追涨杀跌。关注量价配合和趋势持续性，"
        "避免推荐已经连续大涨面临回调风险的个股。"
    ),
    "swing": (
        "你是一位波段操作专家，擅长捕捉A股市场中短期价格波动机会。\n\n"
        "你的分析框架：\n"
        "1. 波动率评估：ATR和价格振幅是否提供足够的操作空间。\n"
        "2. 关键价位：支撑位、压力位、通道上下轨。\n"
        "3. 技术形态：底部反转、箱体震荡、旗形整理等可操作形态。\n"
        "4. 风险控制：明确的入场点、止盈位和止损位。\n\n"
        "重要原则：波段交易需要清晰的交易计划，"
        "每笔推荐必须有明确的风险收益比(至少2:1)。"
    ),
    "dividend": (
        "你是一位专注红利收息策略的投资顾问，注重长期稳定的现金流回报。\n\n"
        "你的分析框架：\n"
        "1. 分红持续性：过去5年的分红记录和派息比率趋势。\n"
        "2. 股息率吸引力：当前股息率与同行业、与国债收益率的比较。\n"
        "3. 盈利稳定性：经营现金流能否持续覆盖分红支出。\n"
        "4. 估值保护：低估值提供下行保护。\n\n"
        "重要原则：高股息率不等于好投资，需排除因股价暴跌导致的"
        "\u201c伪高息股\u201d。关注分红的可持续性而非单次高分红。"
    ),
    "sector": (
        "你是一位板块轮动策略专家，擅长识别A股市场的行业轮动机会。\n\n"
        "你的分析框架：\n"
        "1. 板块趋势：行业整体资金流向和涨跌幅排名变化。\n"
        "2. 相对强弱：个股在板块内的相对表现排名。\n"
        "3. 催化剂识别：政策利好、行业事件、业绩拐点。\n"
        "4. 轮动节奏：当前市场是风格轮动还是行业轮动。\n\n"
        "重要原则：板块轮动要提前布局而非追涨，"
        "关注从低迷板块中寻找反转信号，避免在热门板块尾端入场。"
    ),
    "contrarian": (
        "你是一位逆向投资专家，专注于在市场恐慌或过度乐观时寻找错误定价机会。\n\n"
        "你的分析框架：\n"
        "1. 情绪极端识别：换手率骤降/骤升、连续下跌后的恐慌性抛售、超买超卖指标极端值。\n"
        "2. 基本面锚定：下跌是否已充分反映利空？基本面是否实质恶化？\n"
        "3. 筹码结构：大幅下跌后的底部放量是否暗示主力吸筹？\n"
        "4. 安全边际：当前价格距离重置价值（净资产/重置成本）的折价程度。\n\n"
        "重要原则：逆向不等于抄底——必须有基本面支撑。"
        "避免在趋势性行业衰退中逆向，区分'暂时低估'和'价值陷阱'。"
        "如果无法确认底部信号，应输出 action=watch 而非 buy。"
    ),
    "ultra_short": (
        "你是一位A股超短线交易专家，精通T+1制度下的1-3天持仓策略。\n\n"
        "你的分析框架：\n"
        "1. 量价共振：成交量持续放大（量比>1.5）+价格温和上涨（2-5%为最佳区间）。"
        "涨幅过大（>5%）意味着追高风险，T+1下无法当日止损。\n"
        "2. 分时形态：关注分时图的攻击形态——阶梯式上涨优于脉冲式拉升。"
        "尾盘急拉多为出货信号，严格回避。\n"
        "3. 封板力度：如果候选股接近涨停，评估封单量/流通市值比。"
        "封板弱（反复开板）= 高风险，次日大概率低开。\n"
        "4. 竞价强度：集合竞价高开1-3%且量能充沛为正面信号。\n"
        "5. 隔夜风险量化：必须评估'如果今天买入，明天最坏跌多少'。"
        "参考该股历史隔夜跳空数据和大涨后次日回调概率。\n\n"
        "核心纪律：\n"
        "- 当日涨幅>5%：必须 action=watch，不推荐买入\n"
        "- 涨停股：严禁推荐 buy（除非明确的趋势连板且用户授权打板）\n"
        "- 尾盘急拉（14:30后拉升>3%）：降级为 watch\n"
        "- 游资席位集中度高的股票需额外警惕次日高开低走\n"
        "- entry_price 必须基于当前实际可买入价，不用日内低点\n"
        "- stop_loss 必须设置（建议3-5%），因为T+1最早明天才能执行\n"
        "- risk_notes 必须包含'明日最大回撤预估'"
    ),
    "event_driven": (
        "你是一位事件驱动策略专家，擅长从政策发布、并购重组、业绩拐点等事件中挖掘投资机会。\n\n"
        "你的分析框架：\n"
        "1. 事件识别与分类：政策利好/利空、并购重组、股权激励、业绩预告、行业会议。\n"
        "2. 影响评估：事件对公司基本面的实质影响程度和持续时间。\n"
        "3. 市场定价效率：事件信息是否已被市场充分消化？是否存在预期差？\n"
        "4. 时间窗口：事件驱动通常有明确的时间节点，需考虑买入时机和持有期限。\n\n"
        "重要原则：事件驱动的关键是'预期差'——已被广泛报道的利好往往已在价格中。"
        "关注二阶效应（政策对上下游的传导），而非仅看直接受益标的。"
        "如果事件影响不确定或已充分反映，应输出 action=watch。"
    ),
}


class ReviewAgent:
    """LLM-powered review agent for stock recommendation candidates."""

    def __init__(
        self,
        llm_router: Any | None = None,
        trading_profile: dict[str, Any] | None = None,
    ) -> None:
        self._router = llm_router
        self._has_llm = llm_router is not None
        self._trading_profile = trading_profile or {}

    def review_candidates(
        self,
        candidates: list[StockCandidate],
        style: str,
        session: str = "unknown",
        *,
        market_context: str | None = None,
        sector_stats: dict[str, dict[str, float]] | None = None,
        news_context: dict[str, list[str]] | None = None,
        intel_context: str | None = None,
        time_budget: float = 120.0,
        run_id: str | None = None,
    ) -> list[Recommendation]:
        """Review candidates via LLM and produce finalized recommendations.

        If no LLM is available, falls back to auto-generated recommendations
        based on screening scores alone.

        Args:
            candidates: Pre-screened stock candidates.
            style: Investment style key.
            session: Trading session identifier.
            market_context: Optional market background paragraph for LLM.
            sector_stats: Optional per-sector stats for enriched prompts.
            news_context: Optional symbol -> headlines map.
            time_budget: Max seconds for all batches (prevents Celery timeout).

        Returns:
            List of Recommendation objects that passed LLM review.
        """
        if not candidates:
            return []

        if not self._has_llm:
            logger.warning(
                "No LLM available for style=%s — all %d candidates will be score-only",
                style,
                len(candidates),
            )
            return self._fallback_recommendations(
                candidates, style, session, run_id=run_id
            )

        results: list[Recommendation] = []
        # Process in batches of 5 with time budget tracking (I-074)
        batch_size = 5
        deadline = time.perf_counter() + time_budget
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]

            remaining = deadline - time.perf_counter()
            if remaining < 15.0:
                # Not enough time for another LLM call — fallback remaining
                remaining_candidates = candidates[i:]
                logger.warning(
                    "Time budget exhausted (%.1fs left) for style=%s — "
                    "falling back %d remaining candidates to score-only",
                    remaining,
                    style,
                    len(remaining_candidates),
                )
                results.extend(
                    self._fallback_recommendations(
                        remaining_candidates, style, session, run_id=run_id
                    )
                )
                break

            try:
                batch_recs = self._review_batch(
                    batch,
                    style,
                    session,
                    market_context=market_context,
                    sector_stats=sector_stats,
                    news_context=news_context,
                    intel_context=intel_context,
                    run_id=run_id,
                )
                results.extend(batch_recs)
            except Exception as exc:
                logger.error("LLM review failed for batch %d: %s", i, exc)
                # Fallback for this batch
                results.extend(
                    self._fallback_recommendations(batch, style, session, run_id=run_id)
                )

        ai_count = sum(1 for r in results if r.ai_analyzed)
        total = len(results)
        pct = round(ai_count / total * 100) if total else 0
        logger.info(
            "Review complete: style=%s, total=%d, ai_analyzed=%d (%d%% coverage)",
            style,
            total,
            ai_count,
            pct,
        )
        return results

    def _review_batch(
        self,
        candidates: list[StockCandidate],
        style: str,
        session: str,
        *,
        market_context: str | None = None,
        sector_stats: dict[str, dict[str, float]] | None = None,
        news_context: dict[str, list[str]] | None = None,
        intel_context: str | None = None,
        run_id: str | None = None,
    ) -> list[Recommendation]:
        """Send a batch of candidates to LLM for review."""
        from src.llm.base import LLMMessage, LLMProviderError
        from src.llm.router import RoutingStrategy

        system_prompt = self._build_system_prompt(
            style, market_context=market_context, intel_context=intel_context
        )
        user_prompt = self._build_user_prompt(
            candidates, sector_stats=sector_stats, news_context=news_context
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        symbols = [c.symbol for c in candidates]
        logger.info(
            "LLM review starting: style=%s, batch=%d candidates (%s)",
            style,
            len(candidates),
            ", ".join(symbols),
        )
        t0 = time.perf_counter()
        try:
            response = self._router.complete(
                messages=messages,
                caller="review_agent.review_candidates",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=8192,
                temperature=0.3,
            )
            elapsed = time.perf_counter() - t0
            logger.info(
                "LLM review completed: style=%s, %.1fs, %d/%d tokens",
                style,
                elapsed,
                response.input_tokens,
                response.output_tokens,
            )
            return self._parse_response(
                response.text, candidates, style, session, run_id=run_id
            )
        except LLMProviderError as exc:
            elapsed = time.perf_counter() - t0
            logger.error(
                "LLM review FAILED after %.1fs: style=%s, error=%s",
                elapsed,
                style,
                exc,
            )
            raise

    def _build_system_prompt(
        self,
        style: str,
        *,
        market_context: str | None = None,
        intel_context: str | None = None,
    ) -> str:
        """Build style-specific system prompt with optional market context."""
        style_desc = _STYLE_PROMPTS.get(style, _STYLE_PROMPTS["value"])

        parts = [style_desc]

        if market_context:
            parts.append(f"\n## 当前市场背景\n{market_context}")

        # Inject intel/macro context (I-089)
        if intel_context:
            parts.append(f"\n## 情报与宏观信号\n{intel_context}")

        # Inject trading profile constraints (I-090)
        horizon = self._trading_profile.get("horizon", "short")
        max_chasing = self._trading_profile.get("max_intraday_chasing", 5.0)
        if horizon == "ultra_short":
            parts.append(
                "\n## 超短线交易约束 (T+1)\n"
                "用户为超短线交易者（持仓1-3天），必须严格遵守以下规则：\n"
                f"1. **当日涨幅>{max_chasing}%的股票**：降级为 watch，不推荐 buy。"
                "追高买入后T+1无法止损，隔夜风险极高。\n"
                "2. **涨停股**：严禁推荐 buy。涨停次日平均收益为负（均值回归效应），"
                "除非有明确的连板逻辑且用户明确要求打板。\n"
                "3. **尾盘拉升股**：最后30分钟急拉的股票需额外警惕，"
                "多为游资出货行为。\n"
                "4. **隔夜风险评估**：对每只推荐股，必须在 risk_notes 中"
                "明确说明'如果今日买入明日开盘可能面临的最大回撤'。\n"
                "5. **入场价**：entry_price 必须接近当前实际可成交价，"
                "不得用日内低点作为入场参考。\n"
            )
        elif horizon == "short":
            parts.append(
                "\n## 短线交易约束 (T+1)\n"
                "用户为短线交易者（持仓1-2周），注意：\n"
                f"- 当日涨幅>{max_chasing}%的股票需格外谨慎，降低 timing 评分。\n"
                "- T+1制度下，隔夜持仓风险需在 risk_notes 中说明。\n"
            )

        parts.append(
            "\n## 多维度评估方法论\n"
            "请采用以下结构化框架对每只候选股票进行独立评估。\n\n"
            "### 子维度评分 (每维度 0-1)\n"
            "| 维度 | 代码 | 评估要点 |\n"
            "|------|------|----------|\n"
            "| 策略适配度 | style_fit | 候选股与当前投资风格核心特征的匹配程度 |\n"
            "| 催化剂强度 | catalyst | 近期是否存在明确的价格催化剂（业绩拐点、政策利好、资金进场、事件驱动）|\n"
            "| 风险收益比 | risk_reward | 目标价上行空间 vs 止损下行空间，2:1 为及格线 |\n"
            "| 流动性与资金 | liquidity | 换手率合理性、成交量趋势、大单净流入方向 |\n"
            "| 入场时机 | timing | 技术位置是否适合当前建仓（突破确认 > 追高，支撑位附近 > 无依托）|\n"
            "| 板块与市场环境 | market_env | 所属板块强弱、行业景气度、与大盘趋势的协同性 |\n\n"
            "最终评分 (final_score) = 子评分的加权综合，权重依据当前风格自行调整。\n\n"
            "### A股市场特殊因素\n"
            "评估时必须纳入A股特有的市场结构考量：\n"
            "- **T+1交易制度**：买入当日不可卖出，隔夜风险需额外评估\n"
            "- **涨跌停板**：主板±10%、创业板/科创板±20%；涨停股需权衡次日溢价 vs 高开低走\n"
            "- **北向资金**：龙虎榜显示北向资金净买入为正面信号，净卖出需警惕\n"
            "- **板块联动**：A股个股受板块效应显著影响，板块弱势中逆势做多风险高\n"
            "- **散户结构**：情绪面放大效应强于成熟市场，追涨杀跌惯性需纳入时机判断\n\n"
            "### 评分校准\n"
            "这些候选股票已通过量化多因子筛选（技术面+基本面），属于全市场前5%标的。\n"
            "基于此前置筛选质量，请使用完整0-1区间，参考以下校准锚点：\n\n"
            "**0.85-1.00 — 强烈推荐 (action=buy, confidence=high)**\n"
            "策略完美匹配 + 多重催化剂共振 + 技术形态理想 + 板块顺风\n"
            "例：价值策略 — PE低于行业中位数30%+, ROE>15%, 近期机构调研密集+北向加仓\n\n"
            "**0.70-0.84 — 推荐 (action=buy, confidence=medium)**\n"
            "策略良好匹配 + 至少一个明确催化剂 + 风险收益比≥2:1\n"
            "例：成长策略 — 营收增速>30%, PEG<1.5, 行业景气度上行周期\n\n"
            "**0.55-0.69 — 观望 (action=watch)**\n"
            "策略基本匹配但时机欠佳，或催化剂尚不明确\n"
            "例：动量策略 — 刚突破阻力位但未回踩确认，量能配合不充分\n\n"
            "**0.00-0.54 — 不推荐**\n"
            "不符合策略要求 / 市场环境不利 / 风险收益比不划算\n\n"
            "⚠ 校准纪律：每批3-5只候选中通常应有1-3只评分≥0.65。\n"
            "全部<0.65仅在以下极端情形允许：大盘单日跌>3%、候选板块集体重挫、重大系统性利空。\n\n"
            "## 输出格式\n"
            "严格输出JSON数组，不要添加任何额外文字或解释。\n\n"
            "```json\n"
            "[\n"
            "  {\n"
            '    "symbol": "股票代码",\n'
            '    "action": "buy | watch",\n'
            '    "final_score": 0.00,\n'
            '    "sub_scores": {\n'
            '      "style_fit": 0.00,\n'
            '      "catalyst": 0.00,\n'
            '      "risk_reward": 0.00,\n'
            '      "liquidity": 0.00,\n'
            '      "timing": 0.00,\n'
            '      "market_env": 0.00\n'
            "    },\n"
            '    "confidence": "high | medium | low",\n'
            '    "reason": "推荐/观望理由（结合子评分维度，具体引用该股数据）",\n'
            '    "risk_notes": "主要风险（含A股特殊风险如T+1隔夜、涨跌停等）",\n'
            '    "entry_price": null,\n'
            '    "target_price": null,\n'
            '    "stop_loss": null,\n'
            '    "risk_reward_ratio": null\n'
            "  }\n"
            "]\n"
            "```"
        )

        return "\n".join(parts)

    @staticmethod
    def _build_user_prompt(
        candidates: list[StockCandidate],
        *,
        sector_stats: dict[str, dict[str, float]] | None = None,
        news_context: dict[str, list[str]] | None = None,
    ) -> str:
        """Build user prompt with candidate details and optional context.

        Args:
            candidates: Pre-screened stock candidates.
            sector_stats: Per-sector stats (median_pe, median_pb, avg_change_pct, stock_count).
            news_context: Map of symbol -> list of recent news headlines.
        """
        lines = ["## 候选股票列表\n"]
        for c in candidates:
            block = (
                f"### {c.name} ({c.symbol})\n"
                f"- 当前价: {c.price:.2f}\n"
                f"- 涨跌幅: {c.change_pct:+.2f}%\n"
                f"- 换手率: {c.turnover_rate:.2f}%\n"
                f"- PE: {c.pe_ratio or 'N/A'}\n"
                f"- PB: {c.pb_ratio or 'N/A'}\n"
                f"- 筛选评分: {c.score:.4f}\n"
            )

            # Append sector context if available
            ss = (sector_stats or {}).get(c.sector)
            if ss:
                block += (
                    f"- 行业: {c.sector} (共{ss.get('stock_count', 0):.0f}只)\n"
                    f"- 行业中位PE: {ss.get('median_pe', 0):.1f} / "
                    f"中位PB: {ss.get('median_pb', 0):.1f}\n"
                    f"- 行业平均涨幅: {ss.get('avg_change_pct', 0):+.2f}%\n"
                )

            # Flag intraday drift risk (I-090)
            drift = c.factors.get("drift_penalty", 0)
            if drift > 0:
                block += f"- **盘中偏移警告**: 涨幅 {c.factors.get('intraday_change', c.change_pct):.1f}%，追高风险系数 {drift:.2f}\n"

            # Overnight risk data (I-090 Phase 2)
            overnight = c.factors.get("overnight_risk")
            if overnight is not None:
                gap_down = c.factors.get("gap_down_ratio", 0)
                post_rally = c.factors.get("post_rally_drawdown", 0)
                block += (
                    f"- **隔夜风险**: 综合评分 {overnight:.2f}/1.00, "
                    f"跳空为负概率 {gap_down:.0%}, "
                    f"大涨后回调概率 {post_rally:.0%}\n"
                )

            # Append news headlines if available
            headlines = (news_context or {}).get(c.symbol, [])
            if headlines:
                block += "- 近期资讯:\n"
                for h in headlines[:3]:
                    block += f"  - {h}\n"

            block += f"- 因子: {json.dumps(c.factors, ensure_ascii=False)}\n"
            lines.append(block)
        return "\n".join(lines)

    def _parse_response(
        self,
        response_text: str,
        candidates: list[StockCandidate],
        style: str,
        session: str,
        *,
        run_id: str | None = None,
    ) -> list[Recommendation]:
        """Parse LLM JSON response into Recommendation objects."""
        # Extract JSON from response (handle markdown code blocks)
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            items = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM review response: %s\nRaw (first 500): %s",
                exc,
                response_text[:500],
            )
            return self._fallback_recommendations(
                candidates, style, session, run_id=run_id
            )

        if not isinstance(items, list):
            items = [items]

        # Debug: log parsed scores and sub_scores for diagnostics
        if items:
            score_parts = []
            for it in items[:5]:
                sym = it.get("symbol", "?")
                fs = it.get("final_score", "N/A")
                ss = it.get("sub_scores", {})
                if ss:
                    dims = "/".join(f"{v}" for v in ss.values())
                    score_parts.append(f"{sym}={fs}[{dims}]")
                else:
                    score_parts.append(f"{sym}={fs}")
            logger.info(
                "LLM review scores: style=%s, %s (buy threshold=%.2f)",
                style,
                ", ".join(score_parts),
                BUY_SCORE_THRESHOLD,
            )

        # Map candidates by symbol for lookup
        candidate_map = {c.symbol: c for c in candidates}
        now = datetime.now(UTC).isoformat()
        results: list[Recommendation] = []

        for item in items:
            symbol = item.get("symbol", "")
            final_score = float(item.get("final_score", 0))

            # Only keep buy-grade candidates (score >= BUY_SCORE_THRESHOLD)
            if final_score < BUY_SCORE_THRESHOLD:
                continue

            candidate = candidate_map.get(symbol)
            if candidate is None:
                continue

            # Derive confidence from score if not explicitly provided
            raw_conf = item.get("confidence", "")
            if raw_conf in ("high", "medium", "low"):
                confidence = raw_conf
            elif final_score >= 0.8:
                confidence = "high"
            else:
                # final_score >= BUY_SCORE_THRESHOLD is guaranteed above.
                confidence = "medium"

            # Read action from LLM output; default to "buy" for backward compat
            raw_action = str(item.get("action", "buy")).lower().strip()
            if raw_action not in ("buy", "watch"):
                raw_action = "buy"

            # Extract sub_scores if present (optional, from multi-dim framework)
            raw_sub = item.get("sub_scores")
            sub_scores = None
            if isinstance(raw_sub, dict):
                sub_scores = {
                    k: round(float(v), 2)
                    for k, v in raw_sub.items()
                    if isinstance(v, (int, float))
                }

            results.append(
                Recommendation(
                    id=str(uuid.uuid4()),
                    symbol=symbol,
                    name=candidate.name,
                    action=raw_action,
                    style=style,
                    session=session,
                    score=final_score,
                    confidence=confidence,
                    reason=item.get("reason", ""),
                    risk_notes=item.get("risk_notes", ""),
                    entry_price=_safe_float(item.get("entry_price")) or candidate.price,
                    target_price=_safe_float(item.get("target_price")),
                    stop_loss=_safe_float(item.get("stop_loss")),
                    factors=candidate.factors,
                    created_at=now,
                    status="active",
                    ai_analyzed=True,
                    run_id=run_id,
                    sub_scores=sub_scores,
                )
            )

        return results

    @staticmethod
    def _fallback_recommendations(
        candidates: list[StockCandidate],
        style: str,
        session: str,
        *,
        run_id: str | None = None,
    ) -> list[Recommendation]:
        """Generate recommendations without LLM when no API key available."""
        now = datetime.now(UTC).isoformat()
        results: list[Recommendation] = []

        for c in candidates:
            if c.score < WATCH_SCORE_THRESHOLD:
                continue
            confidence = "high" if c.score >= 0.8 else "medium"
            results.append(
                Recommendation(
                    id=str(uuid.uuid4()),
                    symbol=c.symbol,
                    name=c.name,
                    action="buy",
                    style=style,
                    session=session,
                    score=c.score,
                    confidence=confidence,
                    reason=f"基于多因子筛选评分 {c.score:.2f}，该股在{style}策略下表现突出。",
                    risk_notes="此为量化筛选结果，未经AI审核，请结合自身判断。",
                    entry_price=c.price,
                    target_price=None,
                    stop_loss=None,
                    factors=c.factors,
                    created_at=now,
                    status="active",
                    ai_analyzed=False,
                    run_id=run_id,
                )
            )

        return results


def _safe_float(val: Any) -> float | None:
    """Convert value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
