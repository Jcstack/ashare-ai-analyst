"""信号质量分析器 — 封单质量、龙虎榜共识、集合竞价弱转强、订单簿质量

Provides independent analyzers that assess trade signal quality
from granular market microstructure data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.signal_quality")

__all__ = [
    "SignalQualityAnalyzer",
    "SealQuality",
    "DragonTigerEntry",
    "DragonTigerConsensus",
    "AuctionData",
    "WeakToStrongSignal",
    "OrderBookQuality",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SealQuality:
    """Limit-up seal quality assessment."""

    ratio: float  # seal_volume / day_volume
    grade: str  # "strong" | "normal" | "weak"
    next_day_premium_est: str  # e.g. "高开+6-10%"
    tradeable: bool  # True if grade != "weak"


@dataclass
class DragonTigerEntry:
    """A single seat entry on the dragon-tiger board."""

    seat_name: str
    side: str  # "buy" | "sell"
    amount: float  # 万元
    is_institutional: bool
    is_known_hot_money: bool


@dataclass
class DragonTigerConsensus:
    """Consensus signal derived from dragon-tiger board analysis."""

    signal: str  # "strong_consensus" | "consensus" | "divergence" | "distribution"
    institutional_buy_count: int
    hot_money_buy_count: int
    confidence_adjustment: float  # +0.1 for strong consensus, -0.1 for distribution
    reason: str


@dataclass
class AuctionData:
    """Call auction data for weak-to-strong detection."""

    open_pct_920: float  # % change at 9:20
    open_pct_925: float  # % change at 9:25
    auction_volume: float  # 手
    avg_volume_5d: float  # 5日均量 (手)


@dataclass
class WeakToStrongSignal:
    """Weak-to-strong pattern detection result."""

    detected: bool
    strength: str  # "strong" | "moderate" | "none"
    reason: str


@dataclass
class OrderBookQuality:
    """Order book quality assessment from Level-2 data."""

    depth_imbalance: float = 0.5  # bid vs ask volume ratio
    spread_grade: str = "unknown"  # "tight", "normal", "wide"
    institutional_flow: str = "中性"  # "买入", "卖出", "中性"
    institutional_strength: float = 0.0
    bid_wall_detected: bool = False
    ask_wall_detected: bool = False
    adjustment: float = 0.0  # confidence adjustment


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class SignalQualityAnalyzer:
    """信号质量分析器 — 封单比、龙虎榜共识度、集合竞价弱转强模式"""

    def analyze_seal_quality(
        self, seal_volume: float, day_volume: float
    ) -> SealQuality:
        """Assess limit-up board quality from seal-to-volume ratio.

        Thresholds:
        - strong: ratio >= 5x  → next-day premium est. +6-10%
        - normal: 2x <= ratio < 5x → +3-6%
        - weak:   ratio < 2x  → +1-3% or flat open
        """
        if day_volume <= 0:
            return SealQuality(
                ratio=0.0,
                grade="weak",
                next_day_premium_est="平开",
                tradeable=False,
            )

        ratio = round(seal_volume / day_volume, 2)

        if ratio >= 5.0:
            return SealQuality(
                ratio=ratio,
                grade="strong",
                next_day_premium_est="高开+6-10%",
                tradeable=True,
            )
        if ratio >= 2.0:
            return SealQuality(
                ratio=ratio,
                grade="normal",
                next_day_premium_est="高开+3-6%",
                tradeable=True,
            )
        return SealQuality(
            ratio=ratio,
            grade="weak",
            next_day_premium_est="平开至高开+1-3%",
            tradeable=False,
        )

    def analyze_dragon_tiger(
        self, entries: list[DragonTigerEntry]
    ) -> DragonTigerConsensus:
        """Detect institutional/hot-money consensus from dragon-tiger board.

        Classification logic:
        - strong_consensus: >= 2 institutional buys AND >= 1 hot-money buy
        - consensus: any institutional buy OR >= 2 hot-money buys
        - divergence: mixed buy/sell from institutions or hot money
        - distribution: institutional/hot-money primarily on sell side
        """
        inst_buys = 0
        inst_sells = 0
        hm_buys = 0
        hm_sells = 0

        for e in entries:
            if e.is_institutional:
                if e.side == "buy":
                    inst_buys += 1
                else:
                    inst_sells += 1
            if e.is_known_hot_money:
                if e.side == "buy":
                    hm_buys += 1
                else:
                    hm_sells += 1

        signal, adj, reason = self._classify_consensus(
            inst_buys, inst_sells, hm_buys, hm_sells
        )

        return DragonTigerConsensus(
            signal=signal,
            institutional_buy_count=inst_buys,
            hot_money_buy_count=hm_buys,
            confidence_adjustment=adj,
            reason=reason,
        )

    def detect_weak_to_strong(self, auction: AuctionData) -> WeakToStrongSignal:
        """Detect call auction weak-to-strong pattern.

        Pattern:
        - 9:20 shows high open (>3%) but 9:25 drops to 0-2%  →  potential
        - If the drop is significant (>3pp) and volume is above average,
          this signals genuine demand absorbing the fake-out.
        """
        drop = auction.open_pct_920 - auction.open_pct_925

        # Condition: 9:20 was high (>3%), 9:25 came down significantly
        if auction.open_pct_920 <= 3.0 or drop < 1.0:
            return WeakToStrongSignal(
                detected=False,
                strength="none",
                reason="集合竞价未出现明显弱转强形态",
            )

        # 9:25 should be in the 0-2% range (pulled back but not negative)
        if auction.open_pct_925 < -1.0:
            return WeakToStrongSignal(
                detected=False,
                strength="none",
                reason="9:25竞价跌幅过大，非弱转强而是真弱势",
            )

        # Volume confirmation: auction volume should be meaningful
        vol_ratio = (
            auction.auction_volume / auction.avg_volume_5d
            if auction.avg_volume_5d > 0
            else 0.0
        )

        if drop >= 3.0 and 0.0 <= auction.open_pct_925 <= 2.0:
            if vol_ratio >= 0.05:
                return WeakToStrongSignal(
                    detected=True,
                    strength="strong",
                    reason=(
                        f"9:20高开{auction.open_pct_920:.1f}%→"
                        f"9:25回落至{auction.open_pct_925:.1f}%，"
                        f"竞价量比{vol_ratio:.2f}，"
                        "主力洗筹后吸货，弱转强信号强烈"
                    ),
                )
            return WeakToStrongSignal(
                detected=True,
                strength="moderate",
                reason=(
                    f"9:20高开{auction.open_pct_920:.1f}%→"
                    f"9:25回落至{auction.open_pct_925:.1f}%，"
                    "弱转强形态但竞价量偏低，需盘中确认"
                ),
            )

        # Marginal case
        if drop >= 1.5 and auction.open_pct_925 >= 0.0:
            return WeakToStrongSignal(
                detected=True,
                strength="moderate",
                reason=(
                    f"9:20开{auction.open_pct_920:.1f}%→"
                    f"9:25回至{auction.open_pct_925:.1f}%，"
                    "有弱转强迹象，建议观察开盘5分钟走势确认"
                ),
            )

        return WeakToStrongSignal(
            detected=False,
            strength="none",
            reason="竞价波动幅度不足，未构成弱转强信号",
        )

    def analyze_order_book(
        self,
        snapshot: Any,
        history: Any | None = None,
        ticks: Any | None = None,
    ) -> OrderBookQuality:
        """Analyze order book quality from Level-2 data.

        Returns OrderBookQuality with confidence adjustment:
        - Strong bid imbalance (>0.65) + tight spread -> +0.08
        - Strong ask pressure (<0.35) + wide spread -> -0.08
        - Bid wall detected -> +0.05
        - Large institutional buying -> +0.06
        """
        try:
            from src.quant.orderbook_factors import OrderBookFactorEngine

            engine = OrderBookFactorEngine()
            factors = engine.compute(snapshot, history, ticks)

            depth_imb = factors["depth_imbalance"]
            spread = factors["spread_normalized"]
            large_pressure = factors["large_order_pressure"]
            bid_wall = factors["bid_wall_strength"]
            ask_wall = factors["ask_wall_strength"]

            # Spread grade
            if spread > 0.8:
                spread_grade = "tight"
            elif spread > 0.4:
                spread_grade = "normal"
            else:
                spread_grade = "wide"

            # Institutional flow
            if large_pressure > 0.6:
                inst_flow = "买入"
                inst_strength = (large_pressure - 0.5) * 2
            elif large_pressure < 0.4:
                inst_flow = "卖出"
                inst_strength = (0.5 - large_pressure) * 2
            else:
                inst_flow = "中性"
                inst_strength = 0.0

            # Confidence adjustment
            adjustment = 0.0
            if depth_imb > 0.65 and spread_grade == "tight":
                adjustment += 0.08
            elif depth_imb < 0.35 and spread_grade == "wide":
                adjustment -= 0.08
            if bid_wall > 0.7:
                adjustment += 0.05
            if ask_wall > 0.7:
                adjustment -= 0.05
            if inst_flow == "买入" and inst_strength > 0.5:
                adjustment += 0.06
            elif inst_flow == "卖出" and inst_strength > 0.5:
                adjustment -= 0.06

            adjustment = round(max(-0.15, min(0.15, adjustment)), 4)

            return OrderBookQuality(
                depth_imbalance=depth_imb,
                spread_grade=spread_grade,
                institutional_flow=inst_flow,
                institutional_strength=round(inst_strength, 4),
                bid_wall_detected=bid_wall > 0.7,
                ask_wall_detected=ask_wall > 0.7,
                adjustment=adjustment,
            )
        except Exception as exc:
            logger.debug("Order book analysis unavailable: %s", exc)
            return OrderBookQuality()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_consensus(
        inst_buys: int,
        inst_sells: int,
        hm_buys: int,
        hm_sells: int,
    ) -> tuple[str, float, str]:
        """Classify dragon-tiger consensus, return (signal, adjustment, reason)."""
        # Distribution: primarily selling
        total_sells = inst_sells + hm_sells
        total_buys = inst_buys + hm_buys
        if total_sells > 0 and total_buys == 0:
            return (
                "distribution",
                -0.1,
                f"机构卖出{inst_sells}席、游资卖出{hm_sells}席，无买入席位，资金出逃",
            )

        # Strong consensus
        if inst_buys >= 2 and hm_buys >= 1:
            return (
                "strong_consensus",
                0.1,
                f"机构买入{inst_buys}席+游资买入{hm_buys}席，多方资金高度共识",
            )

        # Consensus
        if inst_buys >= 1 or hm_buys >= 2:
            parts: list[str] = []
            if inst_buys >= 1:
                parts.append(f"机构买入{inst_buys}席")
            if hm_buys >= 2:
                parts.append(f"游资买入{hm_buys}席")
            return (
                "consensus",
                0.05,
                "、".join(parts) + "，资金方向一致",
            )

        # Divergence: mixed signals
        if total_buys > 0 and total_sells > 0:
            return (
                "divergence",
                0.0,
                f"买入{total_buys}席 vs 卖出{total_sells}席，资金分歧明显",
            )

        # No meaningful data
        return (
            "divergence",
            0.0,
            "龙虎榜无明显机构或知名游资参与",
        )
