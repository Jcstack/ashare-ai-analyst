"""情绪周期检测器 — 基于游资 meta-framework (冰点→启动→加速→高潮→退潮)

Uses a weighted voting system where 5 quantitative signals each vote
for the most likely sentiment phase, and confidence reflects agreement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SentimentCycleDetector",
    "SentimentSignals",
    "SentimentPhase",
]


@dataclass
class SentimentSignals:
    """Raw market-breadth signals fed into the cycle detector."""

    limit_up_count: int = 0
    max_consecutive_board: int | None = None
    limit_down_count: int | None = None
    volume_change_pct: float | None = None
    northbound_net_flow: float | None = None  # 亿元
    # v70: quantified 游资 signals
    board_break_rate: float | None = None  # 炸板率: sum(break_count) / total_limit_ups
    promotion_1to2: float | None = None  # 一板→二板晋级率
    promotion_2to3: float | None = None  # 二板→三板晋级率


@dataclass
class SentimentPhase:
    """Detected sentiment phase with position-sizing guidance."""

    phase: str  # "freezing" | "ignition" | "acceleration" | "climax" | "ebb"
    phase_cn: str  # "冰点" | "启动" | "加速" | "高潮" | "退潮"
    confidence: float  # 0-1
    max_position_pct: float  # e.g. 0.2 for freezing, 0.8 for acceleration
    max_single_stock_pct: float  # e.g. 0.05 for freezing, 0.15 for acceleration
    stop_loss_pct: float  # tighter in cold phases
    advice: str  # plain Chinese advice
    signal_count: int = 5  # how many of the signals were actually available
    raw_signals: dict[str, Any] = field(
        default_factory=dict
    )  # v70: full quantified data


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_PHASES = ("freezing", "ignition", "acceleration", "climax", "ebb")

_PHASE_CN = {
    "freezing": "冰点",
    "ignition": "启动",
    "acceleration": "加速",
    "climax": "高潮",
    "ebb": "退潮",
}

_POSITION_PARAMS: dict[str, tuple[float, float, float]] = {
    # (max_position_pct, max_single_stock_pct, stop_loss_pct)
    "freezing": (0.20, 0.05, 0.01),
    "ignition": (0.50, 0.10, 0.015),
    "acceleration": (0.80, 0.15, 0.02),
    "climax": (0.50, 0.10, 0.015),
    "ebb": (0.10, 0.03, 0.01),
}

_ADVICE: dict[str, str] = {
    "freezing": "市场处于冰点，控制仓位观望为主，仅关注超跌反弹机会",
    "ignition": "市场情绪开始回暖，可小仓位试探性参与龙头",
    "acceleration": "赚钱效应扩散，可加大仓位跟随主线龙头",
    "climax": "市场情绪过热，注意高位风险，逐步兑现利润",
    "ebb": "退潮期亏钱效应增加，大幅降低仓位，严格止损",
}

# Signal weights (v70: redistributed to include board-break and promotion)
_WEIGHT_LIMIT_UP = 0.25
_WEIGHT_CONSECUTIVE = 0.15
_WEIGHT_LIMIT_DOWN = 0.10
_WEIGHT_VOLUME = 0.10
_WEIGHT_NORTHBOUND = 0.15
_WEIGHT_BOARD_BREAK = 0.15  # 炸板率 — high = ebb, low = acceleration
_WEIGHT_PROMOTION = 0.10  # 晋级率 — high = acceleration, low = ebb


@dataclass
class _PhaseVotes:
    """Accumulates weighted votes per phase."""

    scores: dict[str, float] = field(default_factory=lambda: {p: 0.0 for p in _PHASES})

    def vote(self, phase: str, weight: float) -> None:
        """Cast a weighted vote for *phase*."""
        self.scores[phase] += weight

    def winner(self) -> tuple[str, float]:
        """Return (phase, confidence) where confidence is winner's share."""
        total = sum(self.scores.values())
        if total == 0:
            return "freezing", 0.0
        best = max(self.scores, key=lambda p: self.scores[p])
        confidence = self.scores[best] / total
        return best, round(confidence, 3)


class SentimentCycleDetector:
    """情绪周期检测器 — 从量化信号判断当前市场情绪阶段

    Uses 5 signals: limit-up count, consecutive board height,
    limit-down count, market volume change, northbound flow.
    """

    def detect(self, signals: SentimentSignals) -> SentimentPhase:
        """Return the current sentiment phase with confidence and position advice.

        Dynamically adjusts weights based on which signals are actually
        available (not None).  If fewer than 2 signals are available,
        returns a low-confidence "unknown"-like result mapped to freezing
        for safety.
        """
        # Build list of (voter_fn, weight, value) for available signals
        signal_slots: list[tuple[Any, float, Any]] = [
            (self._vote_limit_up, _WEIGHT_LIMIT_UP, signals.limit_up_count),
        ]
        # Optional signals — only include when not None
        if signals.max_consecutive_board is not None:
            signal_slots.append(
                (
                    self._vote_consecutive,
                    _WEIGHT_CONSECUTIVE,
                    signals.max_consecutive_board,
                )
            )
        if signals.limit_down_count is not None:
            signal_slots.append(
                (self._vote_limit_down, _WEIGHT_LIMIT_DOWN, signals.limit_down_count)
            )
        if signals.volume_change_pct is not None:
            signal_slots.append(
                (self._vote_volume, _WEIGHT_VOLUME, signals.volume_change_pct)
            )
        if signals.northbound_net_flow is not None:
            signal_slots.append(
                (self._vote_northbound, _WEIGHT_NORTHBOUND, signals.northbound_net_flow)
            )
        if signals.board_break_rate is not None:
            signal_slots.append(
                (self._vote_board_break, _WEIGHT_BOARD_BREAK, signals.board_break_rate)
            )
        if signals.promotion_1to2 is not None:
            signal_slots.append(
                (self._vote_promotion, _WEIGHT_PROMOTION, signals.promotion_1to2)
            )

        signal_count = len(signal_slots)

        # Not enough data for reliable detection
        if signal_count < 2:
            pos_pct, single_pct, sl_pct = _POSITION_PARAMS["freezing"]
            return SentimentPhase(
                phase="freezing",
                phase_cn=_PHASE_CN["freezing"],
                confidence=0.0,
                max_position_pct=pos_pct,
                max_single_stock_pct=single_pct,
                stop_loss_pct=sl_pct,
                advice="信号不足，无法可靠判断情绪周期，默认保守策略",
                signal_count=signal_count,
            )

        # Renormalize weights so available signals sum to 1.0
        total_weight = sum(w for _, w, _ in signal_slots)
        votes = _PhaseVotes()
        for voter_fn, weight, value in signal_slots:
            normalized_weight = weight / total_weight
            voter_fn(value, votes, weight_override=normalized_weight)

        phase, confidence = votes.winner()

        # Penalize confidence when signals are sparse (< 3 available)
        if signal_count < 3:
            confidence = round(confidence * 0.6, 3)

        pos_pct, single_pct, sl_pct = _POSITION_PARAMS[phase]

        raw = {
            "limit_up_count": signals.limit_up_count,
            "max_consecutive_board": signals.max_consecutive_board,
            "limit_down_count": signals.limit_down_count,
            "volume_change_pct": signals.volume_change_pct,
            "northbound_net_flow_yi": signals.northbound_net_flow,
            "board_break_rate": signals.board_break_rate,
            "promotion_1to2": signals.promotion_1to2,
            "promotion_2to3": signals.promotion_2to3,
        }

        return SentimentPhase(
            phase=phase,
            phase_cn=_PHASE_CN[phase],
            confidence=confidence,
            max_position_pct=pos_pct,
            max_single_stock_pct=single_pct,
            stop_loss_pct=sl_pct,
            advice=_ADVICE[phase],
            signal_count=signal_count,
            raw_signals={k: v for k, v in raw.items() if v is not None},
        )

    # ------------------------------------------------------------------
    # Individual signal voters
    # ------------------------------------------------------------------

    @staticmethod
    def _vote_limit_up(
        count: int, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on limit-up count thresholds."""
        w = weight_override if weight_override is not None else _WEIGHT_LIMIT_UP
        if count < 20:
            votes.vote("freezing", w)
        elif count < 50:
            votes.vote("ignition", w)
        elif count < 80:
            votes.vote("acceleration", w)
        else:
            votes.vote("climax", w)
        # A sharp drop from previous high also signals ebb, but we only
        # have the absolute count here. Ebb is captured by limit_down and
        # volume signals instead.

    @staticmethod
    def _vote_consecutive(
        height: int, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on max consecutive board height."""
        w = weight_override if weight_override is not None else _WEIGHT_CONSECUTIVE
        if height < 3:
            votes.vote("freezing", w)
        elif height <= 4:
            votes.vote("ignition", w)
        elif height <= 6:
            votes.vote("acceleration", w)
        else:
            # 7+ boards = climax territory
            votes.vote("climax", w)

    @staticmethod
    def _vote_limit_down(
        count: int, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on limit-down count (inverse sentiment indicator)."""
        w = weight_override if weight_override is not None else _WEIGHT_LIMIT_DOWN
        if count > 10:
            # High limit-down: either freezing or ebb.
            # Split vote between them (both are cold phases).
            votes.vote("freezing", w * 0.5)
            votes.vote("ebb", w * 0.5)
        elif count > 5:
            votes.vote("ignition", w)
        elif count > 3:
            votes.vote("acceleration", w)
        else:
            votes.vote("climax", w)

    @staticmethod
    def _vote_volume(
        change_pct: float, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on market volume change vs 5-day average."""
        w = weight_override if weight_override is not None else _WEIGHT_VOLUME
        if change_pct < -20.0:
            votes.vote("freezing", w * 0.5)
            votes.vote("ebb", w * 0.5)
        elif change_pct < 0.0:
            votes.vote("ignition", w * 0.5)
            votes.vote("freezing", w * 0.5)
        elif change_pct < 20.0:
            votes.vote("ignition", w)
        elif change_pct < 50.0:
            votes.vote("acceleration", w)
        else:
            votes.vote("climax", w)

    @staticmethod
    def _vote_northbound(
        flow: float, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on northbound net flow (亿元)."""
        w = weight_override if weight_override is not None else _WEIGHT_NORTHBOUND
        if flow < -30.0:
            votes.vote("ebb", w)
        elif flow < 0.0:
            votes.vote("freezing", w)
        elif flow < 30.0:
            votes.vote("ignition", w)
        elif flow < 80.0:
            votes.vote("acceleration", w)
        else:
            votes.vote("climax", w)

    @staticmethod
    def _vote_board_break(
        rate: float, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on board-break rate (炸板率).

        High break rate means weak seal strength, market losing conviction.
        Low break rate means strong seals, momentum intact.
        """
        w = weight_override if weight_override is not None else _WEIGHT_BOARD_BREAK
        if rate > 0.4:
            votes.vote("ebb", w)
        elif rate > 0.3:
            votes.vote("climax", w)  # High break + high limit-up = peak
        elif rate > 0.15:
            votes.vote("ignition", w)
        else:
            votes.vote("acceleration", w)  # Very low break = strong momentum

    @staticmethod
    def _vote_promotion(
        rate_1to2: float, votes: _PhaseVotes, *, weight_override: float | None = None
    ) -> None:
        """Vote based on first-to-second board promotion rate (晋级率).

        High promotion = strong market leadership continuity.
        Low promotion = leaders failing, trend weakening.
        """
        w = weight_override if weight_override is not None else _WEIGHT_PROMOTION
        if rate_1to2 < 0.10:
            votes.vote("ebb", w * 0.5)
            votes.vote("freezing", w * 0.5)
        elif rate_1to2 < 0.20:
            votes.vote("ignition", w)
        elif rate_1to2 < 0.40:
            votes.vote("acceleration", w)
        else:
            votes.vote("climax", w)
