"""龙头股识别器 — 基于游资选股体系 (赵老哥/炒股养家)

Scores and ranks stocks by leader characteristics: first-mover advantage,
seal strength, sector followership, capital consensus, board resilience,
and microstructure quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger("agent_loop.leader_detector")

__all__ = [
    "LeaderDetector",
    "LeaderCandidate",
    "LeaderScore",
]


@dataclass
class LeaderCandidate:
    """Raw attributes of a potential leader stock."""

    symbol: str
    name: str
    sector: str
    is_limit_up: bool = False
    limit_up_time: str | None = None  # HH:MM:SS — earlier is stronger
    seal_volume: float = 0.0  # 封单量 (手)
    total_volume: float = 0.0  # 总成交量 (手)
    consecutive_boards: int = 0  # 连板数
    sector_limit_up_count: int = 0  # 同板块涨停数
    turnover_rate: float = 0.0  # 换手率 %
    has_institutional_buy: bool = False  # 龙虎榜机构买入
    has_hot_money_buy: bool = False  # 龙虎榜游资买入
    board_resealed: bool = False  # 开板回封


@dataclass
class LeaderScore:
    """Scoring result for a leader candidate."""

    symbol: str
    name: str
    sector: str
    total_score: float  # 0-100
    is_leader: bool  # True if total_score > 70
    scores: dict[str, float] = field(default_factory=dict)  # breakdown
    reason: str = ""  # plain Chinese explanation
    confidence_level: str = "high"  # "high" | "medium" | "low"
    dimensions_with_data: int = 5  # how many of 6 dimensions had data


# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_MAX_FIRST_MOVER = 30.0
_MAX_SEAL_STRENGTH = 20.0
_MAX_SECTOR_FOLLOWERS = 15.0
_MAX_CAPITAL_CONSENSUS = 20.0
_MAX_BOARD_RESILIENCE = 15.0
_MAX_MICROSTRUCTURE = 10.0

_LEADER_THRESHOLD = 70.0


class LeaderDetector:
    """龙头股识别器 — 多维度评分排序，选出板块辨识度最高的股票"""

    def identify_leaders(self, candidates: list[LeaderCandidate]) -> list[LeaderScore]:
        """Score and rank stocks by leader characteristics.

        Returns a list sorted by total_score descending.
        """
        verified = self._verify_realtime(candidates)
        results = [self._score_candidate(c) for c in verified]
        results.sort(key=lambda s: s.total_score, reverse=True)
        return results

    def _verify_realtime(
        self, candidates: list[LeaderCandidate]
    ) -> list[LeaderCandidate]:
        """Filter candidates against realtime prices. Remove stale/incorrect entries."""
        if not candidates:
            return candidates
        try:
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager()
            symbols = [c.symbol for c in candidates if c.symbol]
            if not symbols:
                return candidates

            # Batch fetch
            quotes: dict[str, dict] = {}
            for sym in symbols:
                q = mgr.get_single_quote(sym)
                if q and q.get("price") is not None:
                    quotes[sym] = q

            verified: list[LeaderCandidate] = []
            for c in candidates:
                q = quotes.get(c.symbol)
                if not q:
                    # No quote data — keep (don't block on missing data)
                    verified.append(c)
                    continue

                pct_change = float(q.get("pct_change", 0) or 0)

                # If scanner says "涨停" but stock is actually DOWN → remove
                if pct_change < 0:
                    logger.warning(
                        "Filtered %s (%s): scanner says leader but "
                        "pct_change=%.1f%% (actually down)",
                        c.symbol,
                        c.name,
                        pct_change,
                    )
                    continue

                # If scanner says "涨停" but pct_change < 5% → likely stale → remove
                if pct_change < 5.0 and c.limit_up_time:
                    logger.warning(
                        "Filtered %s (%s): claimed limit-up at %s but "
                        "current pct_change=%.1f%%",
                        c.symbol,
                        c.name,
                        c.limit_up_time,
                        pct_change,
                    )
                    continue

                verified.append(c)

            if len(verified) < len(candidates):
                logger.info(
                    "Realtime verification: %d/%d candidates passed",
                    len(verified),
                    len(candidates),
                )
            return verified
        except Exception as exc:
            logger.debug("Realtime verification failed: %s", exc)
            return candidates  # On error, don't filter

    def _score_candidate(self, c: LeaderCandidate) -> LeaderScore:
        """Compute individual scores for a single candidate."""
        scores: dict[str, float] = {}

        scores["first_mover"] = self._score_first_mover(c)
        scores["seal_strength"] = self._score_seal_strength(c)
        scores["sector_followers"] = self._score_sector_followers(c)
        scores["capital_consensus"] = self._score_capital_consensus(c)
        scores["board_resilience"] = self._score_board_resilience(c)

        # 6. Microstructure quality (微观结构) — max 10 pts
        micro_score, micro_available = self._score_microstructure(c)
        scores["microstructure"] = micro_score

        total = sum(scores.values())

        # Determine data completeness -> confidence level
        dimensions_with_data = self._count_data_dimensions(
            c, scores, micro_available=micro_available
        )
        if dimensions_with_data >= 6:
            confidence_level = "high"
        elif dimensions_with_data >= 4:
            confidence_level = "medium"
        elif dimensions_with_data >= 3:
            confidence_level = "medium"
        else:
            confidence_level = "low"

        reason = self._build_reason(c, scores, total)

        return LeaderScore(
            symbol=c.symbol,
            name=c.name,
            sector=c.sector,
            total_score=round(total, 1),
            is_leader=(
                (total >= _LEADER_THRESHOLD and confidence_level != "low")
                or c.consecutive_boards >= 5  # Hard rule: 5连板+ = 自动龙头
            ),
            scores=scores,
            reason=reason,
            confidence_level=confidence_level,
            dimensions_with_data=dimensions_with_data,
        )

    @staticmethod
    def _count_data_dimensions(
        c: LeaderCandidate,
        scores: dict[str, float],
        *,
        micro_available: bool = False,
    ) -> int:
        """Count how many of the 6 scoring dimensions have meaningful data.

        A dimension "has data" when the candidate provided the raw input
        needed to produce a non-trivial score (not just a zero-default).
        """
        count = 0
        # 1. first_mover: needs is_limit_up
        if c.is_limit_up:
            count += 1
        # 2. seal_strength: needs is_limit_up + total_volume > 0
        if c.is_limit_up and c.total_volume > 0:
            count += 1
        # 3. sector_followers: needs sector_limit_up_count > 0
        if c.sector_limit_up_count > 0:
            count += 1
        # 4. capital_consensus: needs institutional or hot money flag
        if c.has_institutional_buy or c.has_hot_money_buy:
            count += 1
        # 5. board_resilience: needs is_limit_up (board_resealed is optional detail)
        if c.is_limit_up:
            count += 1
        # 6. microstructure: needs Level-2 data availability
        if micro_available:
            count += 1
        return count

    # ------------------------------------------------------------------
    # Criterion scorers (each returns 0 to its max)
    # ------------------------------------------------------------------

    @staticmethod
    def _score_first_mover(c: LeaderCandidate) -> float:
        """首板辨识度: 30pts — earliest limit-up in sector gets full score."""
        if not c.is_limit_up:
            return 0.0

        if c.limit_up_time is None:
            # Limit-up but unknown time — give partial credit.
            return _MAX_FIRST_MOVER * 0.4

        # Parse HH:MM:SS and reward earlier times.
        parts = c.limit_up_time.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            return _MAX_FIRST_MOVER * 0.4

        minutes_since_open = (hour - 9) * 60 + (minute - 30)
        if minutes_since_open < 0:
            minutes_since_open = 0

        # Best case: limit-up at open (0 min) = 30pts
        # Worst case: limit-up near close (240 min) = 6pts
        # Linear decay from 30 to 6.
        max_trading_minutes = 240.0
        ratio = min(minutes_since_open / max_trading_minutes, 1.0)
        return round(_MAX_FIRST_MOVER * (1.0 - 0.8 * ratio), 1)

    @staticmethod
    def _score_seal_strength(c: LeaderCandidate) -> float:
        """封单强度: 20pts — seal_volume / total_volume ratio.

        Typical A-share seal ratios: 5-30% of total volume.
        >= 30% is very strong (full score), < 3% is weak (zero).
        """
        if not c.is_limit_up or c.total_volume <= 0:
            return 0.0

        ratio = c.seal_volume / c.total_volume
        # ratio >= 0.30 → full score; ratio <= 0.03 → zero
        if ratio >= 0.30:
            return _MAX_SEAL_STRENGTH
        if ratio <= 0.03:
            return 0.0
        # Linear interpolation between 0.03 and 0.30
        return round(_MAX_SEAL_STRENGTH * (ratio - 0.03) / 0.27, 1)

    @staticmethod
    def _score_sector_followers(c: LeaderCandidate) -> float:
        """板块跟风: 15pts — sector_limit_up_count >= 3 for full score."""
        count = c.sector_limit_up_count
        if count >= 5:
            return _MAX_SECTOR_FOLLOWERS
        if count >= 3:
            return _MAX_SECTOR_FOLLOWERS * 0.8
        if count >= 1:
            return _MAX_SECTOR_FOLLOWERS * 0.4
        return 0.0

    @staticmethod
    def _score_capital_consensus(c: LeaderCandidate) -> float:
        """资金共识: 20pts — institutional + hot money on dragon-tiger buy side."""
        score = 0.0
        if c.has_institutional_buy:
            score += _MAX_CAPITAL_CONSENSUS * 0.5
        if c.has_hot_money_buy:
            score += _MAX_CAPITAL_CONSENSUS * 0.5
        return score

    @staticmethod
    def _score_board_resilience(c: LeaderCandidate) -> float:
        """封板韧性: 15pts — opened but re-sealed shows demand resilience."""
        if not c.is_limit_up:
            return 0.0
        if c.board_resealed:
            return _MAX_BOARD_RESILIENCE
        # Never opened = decent but not tested resilience.
        return _MAX_BOARD_RESILIENCE * 0.6

    @staticmethod
    def _score_microstructure(c: LeaderCandidate) -> tuple[float, bool]:
        """微观结构: 10pts -- order book quality from Level-2 data.

        Returns:
            Tuple of (score, data_available). Score is 0 if L2 unavailable.
            Existing functionality is unaffected when L2 is absent.
        """
        micro_score = 0.0
        micro_available = False
        try:
            from src.data.level2_provider import Level2Provider
            from src.quant.orderbook_factors import OrderBookFactorEngine

            l2 = Level2Provider()
            if l2.has_level2:
                snapshot = l2.get_snapshot(c.symbol)
                if snapshot:
                    engine = OrderBookFactorEngine()
                    factors = engine.compute(snapshot)

                    # Strong depth imbalance (buying pressure) = up to 4 pts
                    depth_imb = factors.get("depth_imbalance", 0.5)
                    if depth_imb > 0.6:
                        micro_score += min(4.0, (depth_imb - 0.5) * 20)

                    # Tight spread = up to 3 pts (liquid, institutional)
                    spread = factors.get("spread_normalized", 0.5)
                    if spread > 0.7:
                        micro_score += 3.0
                    elif spread > 0.5:
                        micro_score += 1.0

                    # Buy-initiated trade dominance = up to 3 pts
                    trade_dir = factors.get("trade_direction_ratio", 0.5)
                    if trade_dir > 0.6:
                        micro_score += min(3.0, (trade_dir - 0.5) * 15)

                    micro_available = True
        except Exception:
            pass

        return round(micro_score, 1), micro_available

    # ------------------------------------------------------------------
    # Reason builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_reason(
        c: LeaderCandidate, scores: dict[str, float], total: float
    ) -> str:
        """Build a plain Chinese explanation of the score."""
        parts: list[str] = []

        if scores.get("first_mover", 0) >= _MAX_FIRST_MOVER * 0.7:
            time_str = c.limit_up_time or "早盘"
            parts.append(f"{time_str}率先涨停，辨识度高")
        if scores.get("seal_strength", 0) >= _MAX_SEAL_STRENGTH * 0.7:
            parts.append("封单量大，资金锁仓意愿强")
        if scores.get("sector_followers", 0) >= _MAX_SECTOR_FOLLOWERS * 0.7:
            parts.append(f"板块{c.sector_limit_up_count}家涨停跟风，主线确认")
        if scores.get("capital_consensus", 0) >= _MAX_CAPITAL_CONSENSUS * 0.7:
            actors: list[str] = []
            if c.has_institutional_buy:
                actors.append("机构")
            if c.has_hot_money_buy:
                actors.append("游资")
            parts.append(f"{'和'.join(actors)}龙虎榜买入，资金共识")
        if scores.get("board_resilience", 0) >= _MAX_BOARD_RESILIENCE * 0.7:
            parts.append("开板回封展现韧性")
        if scores.get("microstructure", 0) >= _MAX_MICROSTRUCTURE * 0.7:
            parts.append("订单簿买盘厚实，微观结构健康")

        if not parts:
            parts.append("综合评分偏低，暂不具备龙头特征")

        return f"[{c.name}] 龙头评分{total:.0f}分: " + "；".join(parts)
