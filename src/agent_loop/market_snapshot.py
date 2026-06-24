"""MarketSnapshot — unified data structure for LLM analysis of a single symbol.

Replaces the old approach of sending only news + position cost to the LLM.
Now ALL computed signals are injected via a single, structured snapshot that
aggregates context from every available module.

The ContextBuilder gathers data in parallel with graceful degradation:
if a module is unavailable or errors, that dimension is simply None.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from src.agent_loop.bayesian_belief import BayesianBeliefEngine
    from src.agent_loop.convergence_engine import ConvergenceEngine
    from src.agent_loop.intraday_patterns import IntradayPatternDetector
    from src.agent_loop.reflexivity_detector import ReflexivityDetector
    from src.agent_loop.sentiment_cycle import SentimentCycleDetector
    from src.agent_loop.thesis_tracker import ThesisTracker
    from src.data.macro_flow_fetcher import MacroFlowFetcher
    from src.data.minute_bar import MinuteBarFetcher
    from src.data.realtime import RealtimeQuoteManager
    from src.data.sector_flow_fetcher import SectorFlowFetcher
    from src.intelligence_hub.info_store import InfoStore
    from src.quant.multi_timeframe import MultiTimeframeEngine
    from src.quant.qlib_alpha import QlibAlphaEngine
    from src.quant.vpin import VpinCalculator
    from src.quant.vwap_trigger import VwapTriggerEngine
    from src.web.services.portfolio_store import PortfolioStore

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")

__all__ = [
    "MarketSnapshot",
    "ContextBuilder",
]


# ---------------------------------------------------------------------------
# MarketSnapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    """Complete context for LLM analysis of a single symbol.

    This replaces the old approach of sending only news + position cost to
    the LLM.  Now ALL computed signals are injected so the LLM can reason
    over the full picture.
    """

    # Identity
    symbol: str
    name: str
    snapshot_time: datetime

    # Price action
    current_price: float | None = None
    price_change_pct: float | None = None
    volume_ratio: float | None = None  # vs 20d avg

    # Quant signals (from existing modules)
    vpin_score: float | None = None  # 0-1, from src/quant/vpin.py
    vpin_toxicity: str | None = None  # low/moderate/elevated/high
    vwap_signals: list[dict] = field(default_factory=list)  # from vwap_trigger.py
    mtf_alignment: str | None = None  # bullish_aligned/bearish_aligned/mixed
    mtf_confidence_boost: float | None = None  # +/-0.15
    reflexivity_state: str | None = None  # strengthening/exhausting/breaking
    reflexivity_score: float | None = None
    reversal_probability: float | None = None
    intraday_patterns: list[str] = field(default_factory=list)  # detected pattern names

    # Alpha factors (from src/quant/qlib_alpha.py)
    momentum_score: float | None = None
    quality_score: float | None = None
    composite_alpha: float | None = None

    # Capital flow (from macro_flow_fetcher, sector_flow_fetcher)
    main_net_inflow_wan: float | None = None  # 万元
    northbound_net_wan: float | None = None
    margin_balance_change_wan: float | None = None
    sector_net_inflow_wan: float | None = None

    # Intelligence (from src/intelligence_hub/)
    news_sentiment: str | None = None  # bullish/bearish/neutral
    news_sentiment_intensity: float | None = None  # 0-1
    key_events: list[str] = field(default_factory=list)  # top events, one-line each
    cross_verification_score: float | None = None  # 0-1
    intel_item_count: int = 0

    # Market regime (from existing modules)
    sentiment_phase: str | None = None  # 冰点/启动/加速/高潮/退潮
    market_regime: str | None = None  # bull/bear/consolidation
    sector_rank: int | None = None

    # Portfolio context (if held)
    position_shares: int | None = None
    cost_price: float | None = None
    unrealized_pnl_pct: float | None = None
    position_weight_pct: float | None = None
    days_held: int | None = None

    # Risk state (from decision pipeline)
    daily_pnl_pct: float | None = None
    consecutive_stops: int = 0
    bayesian_posterior: float | None = None  # P(bullish)
    convergence_score: float | None = None
    convergence_sources: int = 0

    # Active thesis (if any)
    thesis_direction: str | None = None
    thesis_conviction: float | None = None
    thesis_text: str | None = None

    # Corporate events (v54 — cninfo, EastMoney datacenter)
    announcements: list[str] = field(default_factory=list)  # recent high-impact titles
    lockup_upcoming_pct: float | None = None  # % shares unlocking in 30 days
    lockup_days_until: int | None = None  # days to nearest unlock
    block_trade_net_wan: float | None = None  # 30-day net block trade amount
    block_trade_discount: float | None = None  # avg block trade discount %
    insider_net_direction: str | None = None  # increase/decrease/neutral
    earnings_forecast_type: str | None = None  # 预增/预减/扭亏/首亏 etc
    earnings_yoy_change_pct: float | None = None  # midpoint of YoY range

    # Global macro context (v53 — GDELT, FRED, Polymarket)
    gdelt_global_tone: float | None = None  # -10 to +10
    gdelt_china_tone: float | None = None  # China-specific tone
    gdelt_tone_trend: str | None = None  # improving/deteriorating/stable
    fred_snapshot_text: str | None = None  # pre-formatted macro string
    polymarket_risk_text: str | None = None  # pre-formatted geopolitical risk

    # ------------------------------------------------------------------
    # Serialization for LLM injection
    # ------------------------------------------------------------------

    def serialize_for_llm(self) -> str:
        """Serialize to annotated text for LLM context injection.

        Key principles:
        - Every numeric field includes unit or scale annotation
        - Scores include range and directionality (higher=better or worse)
        - Timestamps and freshness are explicit
        - Chinese labels for user-facing output
        - Skip None/missing: only include available data
        """
        parts: list[str] = []

        # Header with timestamp
        ts_str = (
            self.snapshot_time.strftime("%Y-%m-%d %H:%M")
            if self.snapshot_time
            else "未知"
        )
        header = f"=== {self.symbol} {self.name} | 数据截止: {ts_str}"
        if self.current_price is not None:
            header += f" | 现价: \u00a5{self.current_price:.2f}"
        if self.price_change_pct is not None:
            arrow = "\u2191" if self.price_change_pct >= 0 else "\u2193"
            header += f" {arrow}{self.price_change_pct:+.2f}%"
        if self.volume_ratio is not None:
            header += (
                f" | 量比: {self.volume_ratio:.2f}(1.0=近20日均量, >1.5放量, <0.7缩量)"
            )
        header += " ==="
        parts.append(header)

        # [量化信号] block
        quant_lines = self._build_quant_block()
        if quant_lines:
            parts.append("")
            parts.append("[\u91cf\u5316\u4fe1\u53f7]")
            parts.extend(quant_lines)

        # [资金] block
        flow_line = self._build_flow_block()
        if flow_line:
            parts.append("")
            parts.append("[\u8d44\u91d1]")
            parts.append(flow_line)

        # [情报] block
        intel_lines = self._build_intel_block()
        if intel_lines:
            parts.append("")
            parts.append("[\u60c5\u62a5]")
            parts.extend(intel_lines)

        # [环境] block
        env_line = self._build_env_block()
        if env_line:
            parts.append("")
            parts.append("[\u73af\u5883]")
            parts.append(env_line)

        # [持仓] block
        pos_line = self._build_position_block()
        if pos_line:
            parts.append("")
            parts.append("[\u6301\u4ed3]")
            parts.append(pos_line)

        # [风险] block
        risk_line = self._build_risk_block()
        if risk_line:
            parts.append("")
            parts.append("[\u98ce\u9669]")
            parts.append(risk_line)

        # [宏观] block (FRED macro data)
        macro_line = self._build_macro_block()
        if macro_line:
            parts.append("")
            parts.append("[\u5b8f\u89c2]")
            parts.append(macro_line)

        # [公司事件] block (announcements, lockup, block trades, insider, earnings)
        corp_lines = self._build_corporate_block()
        if corp_lines:
            parts.append("")
            parts.append("[公司事件]")
            parts.extend(corp_lines)

        # [地缘] block (GDELT tone + Polymarket risk)
        geo_lines = self._build_geo_block()
        if geo_lines:
            parts.append("")
            parts.append("[\u5730\u7f18]")
            parts.extend(geo_lines)

        # [论点] block
        thesis_line = self._build_thesis_block()
        if thesis_line:
            parts.append("")
            parts.append("[\u8bba\u70b9]")
            parts.append(thesis_line)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Block builders (private)
    # ------------------------------------------------------------------

    def _build_quant_block(self) -> list[str]:
        """Build quantitative signals block with annotated units/ranges."""
        lines: list[str] = []
        segments: list[str] = []

        # VPIN (Volume-synchronized Probability of Informed Trading)
        if self.vpin_score is not None:
            tox = f",毒性={self.vpin_toxicity}" if self.vpin_toxicity else ""
            segments.append(
                f"VPIN: {self.vpin_score:.2f}(范围0-1, >0.7=高毒性预警{tox})"
            )

        # VWAP signals
        if self.vwap_signals:
            descs = []
            for sig in self.vwap_signals:
                sig_type = sig.get("signal_type", "unknown")
                direction = sig.get("direction", "")
                z = sig.get("z_score")
                dir_cn = "偏多" if direction == "bullish" else "偏空"
                z_str = f",偏离{z:.1f}个标准差" if z is not None else ""
                descs.append(f"{sig_type}({dir_cn}{z_str})")
            segments.append(f"VWAP信号: {'; '.join(descs)}")

        # MTF alignment (Multi-Timeframe: 5min/15min/30min/daily)
        if self.mtf_alignment is not None:
            boost = ""
            if self.mtf_confidence_boost is not None:
                sign = "增强" if self.mtf_confidence_boost > 0 else "削弱"
                boost = f",置信度{sign}{abs(self.mtf_confidence_boost):.2f}"
            alignment_cn = {
                "bullish_aligned": "多头一致",
                "bearish_aligned": "空头一致",
                "mixed": "方向分歧",
            }.get(self.mtf_alignment, self.mtf_alignment)
            segments.append(f"多周期(5m/15m/30m/日): {alignment_cn}{boost}")

        if segments:
            lines.append(" | ".join(segments))

        # Reflexivity (Soros-style feedback loop detection)
        segments2: list[str] = []
        if self.reflexivity_state is not None and self.reflexivity_state != "none":
            state_cn = {
                "strengthening": "正反馈增强中",
                "exhausting": "反馈力度衰减",
                "breaking": "反馈断裂(反转信号)",
            }.get(self.reflexivity_state, self.reflexivity_state)
            ref_parts = [f"反身性: {state_cn}"]
            if self.reflexivity_score is not None:
                ref_parts[0] += f"(强度{self.reflexivity_score:.2f},范围0-1)"
            if self.reversal_probability is not None:
                ref_parts.append(f"反转概率{self.reversal_probability:.0%}")
            segments2.append(", ".join(ref_parts))

        # Intraday patterns
        if self.intraday_patterns:
            segments2.append(f"日内形态: {', '.join(self.intraday_patterns)}")

        if segments2:
            lines.append(" | ".join(segments2))

        # Alpha factors (Qlib-computed, cross-sectional percentile rank 0-1)
        alpha_parts: list[str] = []
        if self.momentum_score is not None:
            alpha_parts.append(f"动量={self.momentum_score:.2f}")
        if self.quality_score is not None:
            alpha_parts.append(f"质量={self.quality_score:.2f}")
        if self.composite_alpha is not None:
            alpha_parts.append(f"综合={self.composite_alpha:.2f}")
        if alpha_parts:
            lines.append(f"因子(0-1, 越高越好): {' | '.join(alpha_parts)}")

        return lines

    def _build_flow_block(self) -> str:
        """Build capital flow block with explicit units and direction."""
        parts: list[str] = []
        if self.main_net_inflow_wan is not None:
            dir_cn = "净流入" if self.main_net_inflow_wan >= 0 else "净流出"
            parts.append(
                f"主力资金(大单+超大单): {dir_cn}{abs(self.main_net_inflow_wan):.0f}万元"
            )
        if self.northbound_net_wan is not None:
            dir_cn = "净买入" if self.northbound_net_wan >= 0 else "净卖出"
            parts.append(f"北向资金: {dir_cn}{abs(self.northbound_net_wan):.0f}万元")
        if self.margin_balance_change_wan is not None:
            dir_cn = "增加" if self.margin_balance_change_wan >= 0 else "减少"
            parts.append(
                f"融资余额变化: {dir_cn}{abs(self.margin_balance_change_wan):.0f}万元"
            )
        if self.sector_net_inflow_wan is not None:
            dir_cn = "净流入" if self.sector_net_inflow_wan >= 0 else "净流出"
            parts.append(
                f"所属板块资金: {dir_cn}{abs(self.sector_net_inflow_wan):.0f}万元"
            )
        return " | ".join(parts) if parts else ""

    def _build_intel_block(self) -> list[str]:
        """Build intelligence/news block with semantic labels."""
        lines: list[str] = []
        meta_parts: list[str] = []

        if self.news_sentiment is not None:
            sent_cn = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(
                self.news_sentiment, self.news_sentiment
            )
            intensity = ""
            if self.news_sentiment_intensity is not None:
                intensity = f",强度{self.news_sentiment_intensity:.2f}(0-1)"
            meta_parts.append(f"舆情方向: {sent_cn}{intensity}")

        if self.cross_verification_score is not None:
            meta_parts.append(
                f"多源交叉验证: {self.cross_verification_score:.2f}(0-1, >0.7=高可信)"
            )

        if self.intel_item_count > 0:
            meta_parts.append(f"情报条数: {self.intel_item_count}")

        if meta_parts:
            lines.append(" | ".join(meta_parts))

        for event in self.key_events:
            lines.append(f"  - {event}")

        return lines

    def _build_env_block(self) -> str:
        """Build market environment block with interpretive labels."""
        parts: list[str] = []
        if self.sentiment_phase is not None:
            phase_desc = {
                "冰点": "冰点(极度悲观,反弹窗口)",
                "启动": "启动(情绪回暖,选龙头)",
                "加速": "加速(赚钱效应扩散,跟随趋势)",
                "高潮": "高潮(过热,开始防守)",
                "退潮": "退潮(亏钱效应,空仓等待)",
            }.get(self.sentiment_phase, self.sentiment_phase)
            parts.append(f"情绪周期: {phase_desc}")
        if self.market_regime is not None:
            regime_cn = {"bull": "牛市", "bear": "熊市", "consolidation": "震荡"}.get(
                self.market_regime, self.market_regime
            )
            parts.append(f"大盘状态: {regime_cn}")
        if self.sector_rank is not None:
            parts.append(f"板块排名: 第{self.sector_rank}名(越小越强)")
        return " | ".join(parts) if parts else ""

    def _build_position_block(self) -> str:
        """Build portfolio position block with explicit semantics."""
        if self.position_shares is None:
            return ""
        parts: list[str] = []
        cost_str = (
            f", 成本价\u00a5{self.cost_price:.2f}"
            if self.cost_price is not None
            else ""
        )
        parts.append(f"持有{self.position_shares}股{cost_str}")
        if self.unrealized_pnl_pct is not None:
            label = "浮盈" if self.unrealized_pnl_pct >= 0 else "浮亏"
            parts.append(f"{label}{abs(self.unrealized_pnl_pct):.2f}%")
        if self.position_weight_pct is not None:
            parts.append(f"占组合{self.position_weight_pct:.1f}%")
        if self.days_held is not None:
            parts.append(f"已持有{self.days_held}天")
        return " | ".join(parts)

    def _build_risk_block(self) -> str:
        """Build risk state block with interpretation guides."""
        parts: list[str] = []
        if self.daily_pnl_pct is not None:
            label = "盈利" if self.daily_pnl_pct >= 0 else "亏损"
            parts.append(f"当日组合{label}{abs(self.daily_pnl_pct):.2f}%")
        if self.consecutive_stops > 0:
            parts.append(f"近期连续止损{self.consecutive_stops}次(>2次应降低仓位)")
        if self.bayesian_posterior is not None:
            direction = (
                "偏多"
                if self.bayesian_posterior > 0.55
                else ("偏空" if self.bayesian_posterior < 0.45 else "中性")
            )
            parts.append(
                f"贝叶斯后验P(涨)={self.bayesian_posterior:.2f}({direction}, 范围0-1)"
            )
        if self.convergence_score is not None:
            src_str = (
                f", {self.convergence_sources}个独立源"
                if self.convergence_sources > 0
                else ""
            )
            parts.append(
                f"信号收敛度={self.convergence_score:.2f}(越高=方向越一致{src_str})"
            )
        return " | ".join(parts) if parts else ""

    def _build_corporate_block(self) -> list[str]:
        """Build corporate events block (v54)."""
        lines: list[str] = []

        if self.announcements:
            lines.append("公告: " + " | ".join(self.announcements[:3]))

        if self.lockup_upcoming_pct is not None and self.lockup_upcoming_pct > 0:
            days_str = (
                f"{self.lockup_days_until}天后"
                if self.lockup_days_until is not None
                else ""
            )
            lines.append(f"解禁: 30日内解禁{self.lockup_upcoming_pct:.1f}%, {days_str}")

        if self.block_trade_net_wan is not None and self.block_trade_net_wan != 0:
            direction = "净买入" if self.block_trade_net_wan > 0 else "净卖出"
            disc = ""
            if self.block_trade_discount is not None:
                disc = f"(折价{self.block_trade_discount:+.1f}%)"
            lines.append(
                f"大宗交易: 近30日{direction}{abs(self.block_trade_net_wan):.0f}万{disc}"
            )

        if (
            self.insider_net_direction is not None
            and self.insider_net_direction != "neutral"
        ):
            dir_cn = "净增持" if self.insider_net_direction == "increase" else "净减持"
            lines.append(f"增减持: 大股东近90日{dir_cn}")

        if self.earnings_forecast_type:
            yoy = ""
            if self.earnings_yoy_change_pct is not None:
                yoy = f" {self.earnings_yoy_change_pct:+.0f}%"
            lines.append(f"业绩预告: {self.earnings_forecast_type}{yoy}")

        return lines

    def _build_thesis_block(self) -> str:
        """Build active thesis block."""
        if self.thesis_direction is None:
            return ""
        parts: list[str] = []
        dir_cn = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}.get(
            self.thesis_direction, self.thesis_direction
        )
        conv = ""
        if self.thesis_conviction is not None:
            conv = f", 确信度{self.thesis_conviction:.2f}(0-1)"
        parts.append(f"当前论点: {dir_cn}{conv}")
        if self.thesis_text:
            parts.append(self.thesis_text)
        return " | ".join(parts)

    def _build_macro_block(self) -> str:
        """Build global macro block (FRED data)."""
        if self.fred_snapshot_text:
            return self.fred_snapshot_text
        return ""

    def _build_geo_block(self) -> list[str]:
        """Build geopolitical block (GDELT tone + Polymarket risk)."""
        lines: list[str] = []
        tone_parts: list[str] = []
        if self.gdelt_global_tone is not None:
            tone_parts.append(f"\u5168\u7403tone:{self.gdelt_global_tone:+.1f}")
        if self.gdelt_china_tone is not None:
            tone_parts.append(f"\u4e2d\u56fdtone:{self.gdelt_china_tone:+.1f}")
        if self.gdelt_tone_trend is not None:
            tone_parts.append(f"\u8d8b\u52bf:{self.gdelt_tone_trend}")
        if tone_parts:
            lines.append("GDELT: " + " | ".join(tone_parts))
        if self.polymarket_risk_text:
            lines.append(self.polymarket_risk_text)
        return lines


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------


class ContextBuilder:
    """Builds MarketSnapshot by gathering from all available modules.

    Designed for graceful degradation -- each data source is optional.
    If a module is unavailable or errors, that section is simply None.
    """

    def __init__(
        self,
        realtime: RealtimeQuoteManager | None = None,
        minute_bar_fetcher: MinuteBarFetcher | None = None,
        vpin_calculator: VpinCalculator | None = None,
        vwap_engine: VwapTriggerEngine | None = None,
        mtf_engine: MultiTimeframeEngine | None = None,
        reflexivity_detector: ReflexivityDetector | None = None,
        pattern_detector: IntradayPatternDetector | None = None,
        alpha_engine: QlibAlphaEngine | None = None,
        macro_flow_fetcher: MacroFlowFetcher | None = None,
        sector_flow_fetcher: SectorFlowFetcher | None = None,
        info_store: InfoStore | None = None,
        sentiment_detector: SentimentCycleDetector | None = None,
        portfolio_store: PortfolioStore | None = None,
        bayesian_engine: BayesianBeliefEngine | None = None,
        convergence_engine: ConvergenceEngine | None = None,
        thesis_tracker: ThesisTracker | None = None,
        # v53: Global intelligence sources
        gdelt_fetcher: Any | None = None,
        fred_fetcher: Any | None = None,
        polymarket_fetcher: Any | None = None,
        # v54: Corporate event sources
        cninfo_fetcher: Any | None = None,
        lockup_fetcher: Any | None = None,
        block_trade_fetcher: Any | None = None,
        insider_fetcher: Any | None = None,
        earnings_fetcher: Any | None = None,
    ) -> None:
        self._realtime = realtime
        self._minute_bar = minute_bar_fetcher
        self._vpin = vpin_calculator
        self._vwap = vwap_engine
        self._mtf = mtf_engine
        self._reflexivity = reflexivity_detector
        self._patterns = pattern_detector
        self._alpha = alpha_engine
        self._macro_flow = macro_flow_fetcher
        self._sector_flow = sector_flow_fetcher
        self._info_store = info_store
        self._sentiment = sentiment_detector
        self._portfolio = portfolio_store
        self._bayesian = bayesian_engine
        self._convergence = convergence_engine
        self._thesis_tracker = thesis_tracker
        # v53: Global intelligence
        self._gdelt = gdelt_fetcher
        self._fred = fred_fetcher
        self._polymarket = polymarket_fetcher
        # v54: Corporate events
        self._cninfo = cninfo_fetcher
        self._lockup = lockup_fetcher
        self._block_trade = block_trade_fetcher
        self._insider = insider_fetcher
        self._earnings = earnings_fetcher

    async def build(self, symbol: str, name: str = "") -> MarketSnapshot:
        """Build complete snapshot for a symbol.  Gathers in parallel."""
        snap = MarketSnapshot(
            symbol=symbol,
            name=name,
            snapshot_time=datetime.now(_CST),
        )

        # Gather all data dimensions in parallel
        results = await asyncio.gather(
            self._fill_price(snap),
            self._fill_minute_bar_derived(snap),
            self._fill_alpha(snap),
            self._fill_macro_flow(snap),
            self._fill_intel(snap),
            self._fill_sentiment(snap),
            self._fill_portfolio(snap),
            self._fill_thesis(snap),
            self._fill_gdelt(snap),
            self._fill_fred(snap),
            self._fill_polymarket(snap),
            self._fill_announcements(snap),
            self._fill_lockup(snap),
            self._fill_block_trades(snap),
            self._fill_insider(snap),
            self._fill_earnings(snap),
            return_exceptions=True,
        )

        # Log any exceptions from the gather
        dimension_names = [
            "price",
            "minute_bar_derived",
            "alpha",
            "macro_flow",
            "intel",
            "sentiment",
            "portfolio",
            "thesis",
            "gdelt",
            "fred",
            "polymarket",
            "announcements",
            "lockup",
            "block_trades",
            "insider",
            "earnings",
        ]
        collected: list[str] = []
        failed: list[str] = []
        for dim_name, result in zip(dimension_names, results):
            if isinstance(result, BaseException):
                failed.append(f"{dim_name}({result!r})")
            else:
                collected.append(dim_name)

        logger.info(
            "Snapshot %s: collected=[%s]%s",
            symbol,
            ",".join(collected),
            f" failed=[{','.join(failed)}]" if failed else "",
        )

        return snap

    async def build_batch(self, symbols: list[tuple[str, str]]) -> list[MarketSnapshot]:
        """Build snapshots for multiple symbols in parallel."""
        tasks = [self.build(sym, name) for sym, name in symbols]
        return await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Dimension fillers (each wraps its own try/except)
    # ------------------------------------------------------------------

    async def _fill_price(self, snap: MarketSnapshot) -> None:
        """Fill price action from RealtimeQuoteManager."""
        if self._realtime is None:
            return
        try:
            quote = await asyncio.to_thread(
                self._realtime.get_single_quote, snap.symbol
            )
            if not quote or quote.get("price") is None:
                return
            snap.current_price = float(quote["price"])
            if "pct_change" in quote and quote["pct_change"] is not None:
                snap.price_change_pct = float(quote["pct_change"])
            # Volume ratio is not directly available from quote;
            # will be enriched from minute bars if available.
        except Exception as exc:
            logger.debug("Price fill failed for %s: %s", snap.symbol, exc)

    async def _fill_minute_bar_derived(self, snap: MarketSnapshot) -> None:
        """Fill VPIN, VWAP, MTF, reflexivity, intraday patterns from minute bars."""
        if self._minute_bar is None:
            return
        try:
            bars = await asyncio.to_thread(
                self._minute_bar.get_today_bars, snap.symbol, "5"
            )
            if bars is None or bars.empty:
                return
        except Exception as exc:
            logger.debug("Minute bar fetch failed for %s: %s", snap.symbol, exc)
            return

        # Run all minute-bar-derived analyses in parallel threads
        await asyncio.gather(
            self._fill_vpin(snap, bars),
            self._fill_vwap(snap, bars),
            self._fill_mtf(snap, bars),
            self._fill_reflexivity(snap, bars),
            self._fill_intraday_patterns(snap, bars),
            return_exceptions=True,
        )

    async def _fill_vpin(self, snap: MarketSnapshot, bars: Any) -> None:
        """Fill VPIN score from VpinCalculator."""
        if self._vpin is None:
            return
        try:
            result = await asyncio.to_thread(self._vpin.calculate, bars, snap.symbol)
            if result is None:
                return
            snap.vpin_score = result.vpin
            snap.vpin_toxicity = result.toxicity_level
        except Exception as exc:
            logger.debug("VPIN fill failed for %s: %s", snap.symbol, exc)

    async def _fill_vwap(self, snap: MarketSnapshot, bars: Any) -> None:
        """Fill VWAP signals from VwapTriggerEngine."""
        if self._vwap is None:
            return
        try:
            signals = await asyncio.to_thread(self._vwap.analyze, bars, snap.symbol)
            if not signals:
                return
            snap.vwap_signals = [
                {
                    "signal_type": s.signal_type,
                    "direction": s.direction,
                    "z_score": s.z_score,
                    "deviation_pct": s.deviation_pct,
                    "confidence": s.confidence,
                }
                for s in signals
            ]
        except Exception as exc:
            logger.debug("VWAP fill failed for %s: %s", snap.symbol, exc)

    async def _fill_mtf(self, snap: MarketSnapshot, bars: Any) -> None:
        """Fill multi-timeframe alignment from MultiTimeframeEngine."""
        if self._mtf is None:
            return
        try:
            result = await asyncio.to_thread(
                self._mtf.analyze,
                bars,
                snap.symbol,
                snap.price_change_pct,
            )
            snap.mtf_alignment = result.confirmed_direction
            snap.mtf_confidence_boost = result.confidence_boost
        except Exception as exc:
            logger.debug("MTF fill failed for %s: %s", snap.symbol, exc)

    async def _fill_reflexivity(self, snap: MarketSnapshot, bars: Any) -> None:
        """Fill reflexivity state from ReflexivityDetector."""
        if self._reflexivity is None:
            return
        try:
            result = await asyncio.to_thread(
                self._reflexivity.analyze, bars, snap.symbol
            )
            snap.reflexivity_state = result.loop_state
            snap.reflexivity_score = result.reflexivity_score
            snap.reversal_probability = result.reversal_probability
        except Exception as exc:
            logger.debug("Reflexivity fill failed for %s: %s", snap.symbol, exc)

    async def _fill_intraday_patterns(self, snap: MarketSnapshot, bars: Any) -> None:
        """Fill intraday patterns from IntradayPatternDetector."""
        if self._patterns is None:
            return
        try:
            # Build a minimal quote dict from snapshot for pattern detection
            quote: dict[str, Any] = {}
            if snap.current_price is not None:
                quote["price"] = snap.current_price
            if bars is not None and not bars.empty:
                quote.setdefault("open", float(bars["open"].iloc[0]))
                quote.setdefault("prev_close", float(bars["open"].iloc[0]))
                quote.setdefault("high", float(bars["high"].max()))
                quote.setdefault("low", float(bars["low"].min()))

            patterns = await asyncio.to_thread(
                self._patterns.detect_all, snap.symbol, bars, quote
            )
            snap.intraday_patterns = [p.pattern_type for p in patterns]
        except Exception as exc:
            logger.debug("Intraday pattern fill failed for %s: %s", snap.symbol, exc)

    async def _fill_alpha(self, snap: MarketSnapshot) -> None:
        """Fill alpha factors from QlibAlphaEngine."""
        if self._alpha is None:
            return
        try:
            factors = await asyncio.to_thread(self._alpha.compute_factors, snap.symbol)
            if not factors.available:
                return
            snap.momentum_score = round(factors.momentum_score, 4)
            snap.quality_score = round(factors.quality_score, 4)
            snap.composite_alpha = factors.composite_score
        except Exception as exc:
            logger.debug("Alpha fill failed for %s: %s", snap.symbol, exc)

    async def _fill_macro_flow(self, snap: MarketSnapshot) -> None:
        """Fill capital flow data from MacroFlowFetcher."""
        if self._macro_flow is None:
            return
        try:
            snapshot = await asyncio.to_thread(self._macro_flow.get_latest_snapshot)
            # Northbound net is in 亿元 from the API; convert to 万元
            if snapshot.northbound_net:
                snap.northbound_net_wan = round(snapshot.northbound_net * 10000, 0)
            if snapshot.margin_balance_change:
                snap.margin_balance_change_wan = round(
                    snapshot.margin_balance_change * 10000, 0
                )
        except Exception as exc:
            logger.debug("Macro flow fill failed for %s: %s", snap.symbol, exc)

        # Sector flow for this symbol's sector (best effort)
        if self._sector_flow is not None:
            try:
                df = await asyncio.to_thread(
                    self._sector_flow.fetch_industry_flow, "today"
                )
                if df is not None and not df.empty and "net_inflow" in df.columns:
                    # Sum total sector net inflow as a market-wide signal
                    # Individual stock-level flow requires per-stock API
                    total = df["net_inflow"].sum()
                    snap.sector_net_inflow_wan = round(total / 10000, 0)
            except Exception as exc:
                logger.debug("Sector flow fill failed for %s: %s", snap.symbol, exc)

    async def _fill_intel(self, snap: MarketSnapshot) -> None:
        """Fill intelligence data from InfoStore."""
        if self._info_store is None:
            return
        try:
            items = await asyncio.to_thread(self._query_intel_for_symbol, snap.symbol)
            if not items:
                return

            snap.intel_item_count = len(items)

            # Aggregate sentiment from items
            bullish = 0
            bearish = 0
            total_score = 0.0
            events: list[str] = []
            cv_scores: list[float] = []

            for item in items:
                title = item.get("title", "")
                if title:
                    events.append(title[:60])

                # Use content_score as a proxy for sentiment intensity
                score = item.get("content_score")
                if score is not None:
                    total_score += float(score)
                    cv_scores.append(float(score))

                priority = item.get("priority", "normal")
                if priority in ("breaking", "high"):
                    bullish += 1  # High-priority items tend to be actionable
                else:
                    bearish += 0  # Neutral items don't add to count

            if events:
                snap.key_events = events[:5]  # Top 5 events

            if cv_scores:
                snap.cross_verification_score = round(
                    sum(cv_scores) / len(cv_scores), 2
                )
                avg = total_score / len(items)
                if avg > 0.6:
                    snap.news_sentiment = "bullish"
                elif avg < 0.4:
                    snap.news_sentiment = "bearish"
                else:
                    snap.news_sentiment = "neutral"
                snap.news_sentiment_intensity = round(abs(avg - 0.5) * 2, 2)

        except Exception as exc:
            logger.debug("Intel fill failed for %s: %s", snap.symbol, exc)

    def _query_intel_for_symbol(self, symbol: str) -> list[dict[str, Any]]:
        """Query InfoStore for items related to a symbol.

        Uses a SQL query against the related_symbols JSON column.
        """
        if self._info_store is None:
            return []
        import sqlite3

        try:
            conn = sqlite3.connect(str(self._info_store._db_path))
            conn.row_factory = sqlite3.Row
            # Search for symbol in JSON array column, last 24h
            rows = conn.execute(
                """
                SELECT title, summary, priority, content_score
                FROM info_items
                WHERE related_symbols LIKE ?
                  AND created_at > datetime('now', '-1 day')
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (f"%{symbol}%",),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("Intel query failed for %s: %s", symbol, exc)
            return []

    async def _fill_sentiment(self, snap: MarketSnapshot) -> None:
        """Fill sentiment cycle phase from SentimentCycleDetector."""
        if self._sentiment is None:
            return
        try:
            from src.agent_loop.sentiment_cycle import SentimentSignals

            # SentimentCycleDetector.detect() requires SentimentSignals;
            # we pass empty signals to get at least the default phase.
            # In production, the trading loop provides populated signals.
            signals = SentimentSignals()
            phase = await asyncio.to_thread(self._sentiment.detect, signals)
            snap.sentiment_phase = phase.phase_cn
        except Exception as exc:
            logger.debug("Sentiment fill failed for %s: %s", snap.symbol, exc)

    async def _fill_portfolio(self, snap: MarketSnapshot) -> None:
        """Fill portfolio position context from PortfolioStore."""
        if self._portfolio is None:
            return
        try:
            positions = await asyncio.to_thread(self._portfolio.list_positions)
            if not positions:
                return

            # Find position matching this symbol
            pos = None
            for p in positions:
                if p.get("symbol") == snap.symbol:
                    pos = p
                    break

            if pos is None:
                return

            snap.position_shares = int(pos.get("shares", 0))
            snap.cost_price = float(pos.get("cost_price", 0))

            # Compute unrealized PnL %
            if (
                snap.current_price is not None
                and snap.cost_price
                and snap.cost_price > 0
            ):
                snap.unrealized_pnl_pct = round(
                    (snap.current_price - snap.cost_price) / snap.cost_price * 100,
                    2,
                )

            # Compute position weight
            total_value = 0.0
            for p2 in positions:
                shares = int(p2.get("shares", 0))
                cost = float(p2.get("cost_price", 0))
                total_value += shares * cost
            if total_value > 0 and snap.position_shares and snap.cost_price:
                snap.position_weight_pct = round(
                    snap.position_shares * snap.cost_price / total_value * 100,
                    1,
                )

            # Days held
            buy_date = pos.get("buy_date", "")
            if buy_date:
                try:
                    bd = datetime.fromisoformat(buy_date)
                    snap.days_held = (datetime.now(_CST).date() - bd.date()).days
                except (ValueError, TypeError):
                    pass

        except Exception as exc:
            logger.debug("Portfolio fill failed for %s: %s", snap.symbol, exc)

    async def _fill_thesis(self, snap: MarketSnapshot) -> None:
        """Fill active thesis from ThesisTracker."""
        if self._thesis_tracker is None:
            return
        try:
            theses = await asyncio.to_thread(
                self._thesis_tracker.list_theses,
                status="active",
                symbol=snap.symbol,
            )
            if not theses:
                # Also check weakening theses
                theses = await asyncio.to_thread(
                    self._thesis_tracker.list_theses,
                    status="weakening",
                    symbol=snap.symbol,
                )

            if not theses:
                return

            thesis = theses[0]  # Most recent active thesis
            snap.thesis_direction = thesis.direction
            snap.thesis_conviction = thesis.current_confidence
            snap.thesis_text = thesis.narrative[:100] if thesis.narrative else None
        except Exception as exc:
            logger.debug("Thesis fill failed for %s: %s", snap.symbol, exc)

    # ------------------------------------------------------------------
    # v53: Global intelligence dimension fillers
    # ------------------------------------------------------------------

    async def _fill_gdelt(self, snap: MarketSnapshot) -> None:
        """Fill GDELT global event tone data."""
        if self._gdelt is None:
            return
        try:
            # fetch_china_relevant returns dict[str, GdeltToneSummary]
            summaries = await self._gdelt.fetch_china_relevant()
            if not summaries:
                return

            # Compute global average tone
            tones = [s.avg_tone for s in summaries.values() if s.avg_tone is not None]
            if tones:
                snap.gdelt_global_tone = round(sum(tones) / len(tones), 1)

            # China-specific tone
            china_summary = summaries.get("china_economy")
            if china_summary:
                snap.gdelt_china_tone = round(china_summary.avg_tone, 1)
                snap.gdelt_tone_trend = china_summary.tone_trend
        except Exception as exc:
            logger.debug("GDELT fill failed: %s", exc)

    async def _fill_fred(self, snap: MarketSnapshot) -> None:
        """Fill FRED macro economic snapshot."""
        if self._fred is None:
            return
        try:
            macro = await self._fred.get_macro_snapshot()
            if macro is not None:
                snap.fred_snapshot_text = macro.to_snapshot_text()
        except Exception as exc:
            logger.debug("FRED fill failed: %s", exc)

    async def _fill_polymarket(self, snap: MarketSnapshot) -> None:
        """Fill Polymarket geopolitical risk signals."""
        if self._polymarket is None:
            return
        try:
            signals = await self._polymarket.get_geopolitical_signals()
            if signals is not None:
                snap.polymarket_risk_text = signals.to_snapshot_text()
        except Exception as exc:
            logger.debug("Polymarket fill failed: %s", exc)

    # -- v54: Corporate event fillers -----------------------------------------

    async def _fill_announcements(self, snap: MarketSnapshot) -> None:
        """Fill corporate announcements from cninfo."""
        if self._cninfo is None:
            return
        try:
            anns = await self._cninfo.fetch_for_symbol(snap.symbol, days=7)
            if anns:
                snap.announcements = [a.title for a in anns if a.is_high_impact][:3]
        except Exception as exc:
            logger.debug("Announcements fill failed for %s: %s", snap.symbol, exc)

    async def _fill_lockup(self, snap: MarketSnapshot) -> None:
        """Fill lock-up expiry data."""
        if self._lockup is None:
            return
        try:
            entries = await self._lockup.fetch_for_symbol(snap.symbol, days=30)
            if entries:
                upcoming = [e for e in entries if e.days_until_unlock >= 0]
                if upcoming:
                    snap.lockup_upcoming_pct = sum(
                        e.shares_pct_of_total for e in upcoming
                    )
                    snap.lockup_days_until = min(e.days_until_unlock for e in upcoming)
        except Exception as exc:
            logger.debug("Lockup fill failed for %s: %s", snap.symbol, exc)

    async def _fill_block_trades(self, snap: MarketSnapshot) -> None:
        """Fill block trade data."""
        if self._block_trade is None:
            return
        try:
            trades = await self._block_trade.fetch_for_symbol(snap.symbol, days=30)
            if trades:
                snap.block_trade_net_wan = sum(t.amount_wan for t in trades)
                discounts = [t.discount_pct for t in trades if t.discount_pct != 0]
                if discounts:
                    snap.block_trade_discount = sum(discounts) / len(discounts)
        except Exception as exc:
            logger.debug("Block trade fill failed for %s: %s", snap.symbol, exc)

    async def _fill_insider(self, snap: MarketSnapshot) -> None:
        """Fill insider activity data."""
        if self._insider is None:
            return
        try:
            snap.insider_net_direction = await self._insider.net_direction(
                snap.symbol, days=90
            )
        except Exception as exc:
            logger.debug("Insider fill failed for %s: %s", snap.symbol, exc)

    async def _fill_earnings(self, snap: MarketSnapshot) -> None:
        """Fill earnings forecast data."""
        if self._earnings is None:
            return
        try:
            forecasts = await self._earnings.fetch_for_symbol(snap.symbol)
            if forecasts:
                latest = forecasts[0]  # sorted by publish date desc
                snap.earnings_forecast_type = latest.forecast_type
                snap.earnings_yoy_change_pct = latest.yoy_midpoint
        except Exception as exc:
            logger.debug("Earnings fill failed for %s: %s", snap.symbol, exc)
