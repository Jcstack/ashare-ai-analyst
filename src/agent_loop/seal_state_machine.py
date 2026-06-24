"""Limit-up board (涨停板) lifecycle state machine.

Tracks the full lifecycle of a limit-up board from approach to
final resolution, using order book snapshots and tick data.

States:
    APPROACHING  -- Price within 2% of limit-up, buying pressure building
    SEALED      -- Price at limit-up, seal orders holding
    BROKEN      -- Seal broke, price dropped below limit-up
    RESEALED    -- Seal reformed after a break
    FAILED      -- Price dropped >2% from limit-up, board failed

Each transition carries timing and volume data critical for
游资 decision-making (e.g., 封板时间, 开板次数, 回封速度).
"""

from __future__ import annotations

import json
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.seal_state_machine")


class SealState(str, Enum):
    NONE = "none"
    APPROACHING = "approaching"
    SEALED = "sealed"
    BROKEN = "broken"
    RESEALED = "resealed"
    FAILED = "failed"


@dataclass
class SealTransition:
    """Record of a state transition."""

    from_state: SealState
    to_state: SealState
    timestamp: float
    price: float
    volume_at_transition: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SealLifecycle:
    """Complete lifecycle tracking for one stock's limit-up board."""

    symbol: str
    board_type: str  # "main", "chinext", "star"
    limit_up_price: float
    prev_close: float

    state: SealState = SealState.NONE
    transitions: list[SealTransition] = field(default_factory=list)

    # Timing
    first_approach_time: float | None = None
    first_seal_time: float | None = None
    last_seal_time: float | None = None
    total_sealed_duration: float = 0.0  # seconds sealed

    # Break tracking
    break_count: int = 0
    max_break_depth_pct: float = 0.0  # deepest break below limit-up
    avg_reseal_speed: float = 0.0  # avg seconds to reseal after break

    # Volume
    seal_volume: int = 0  # current seal order volume
    peak_seal_volume: int = 0  # highest seal volume seen
    volume_at_seal: int = 0  # total traded volume when first sealed

    @property
    def seal_quality_score(self) -> float:
        """Compute composite seal quality score (0-1).

        Higher = stronger board. Factors:
        - Early seal time (earlier = better)
        - Low break count
        - High seal volume ratio
        - Fast reseal speed
        """
        score = 0.5  # neutral baseline

        # Seal time bonus (sealed before 10:00 = max bonus)
        if self.first_seal_time:
            seal_dt = datetime.fromtimestamp(self.first_seal_time)
            seal_t = seal_dt.time()
            if seal_t <= time(10, 0):
                score += 0.2
            elif seal_t <= time(11, 0):
                score += 0.1
            elif seal_t <= time(14, 0):
                score += 0.05

        # Break penalty
        if self.break_count == 0:
            score += 0.15
        elif self.break_count == 1:
            score += 0.05
        else:
            score -= min(self.break_count * 0.05, 0.2)

        # Seal volume strength
        if self.seal_volume > 0 and self.volume_at_seal > 0:
            ratio = self.seal_volume / self.volume_at_seal
            if ratio >= 5.0:
                score += 0.15
            elif ratio >= 2.0:
                score += 0.08

        return round(max(0.0, min(1.0, score)), 4)

    @property
    def next_day_prediction(self) -> dict[str, Any]:
        """Predict next-day opening based on lifecycle data.

        Based on empirical rules:
        - 封成比 >= 10: 高开涨停概率 >70%
        - 封成比 3-10: 高开 6-10%
        - 封成比 1-3: 高开 3-6%
        - 破板回封多次: 次日弱势概率高
        """
        ratio = self.seal_volume / self.volume_at_seal if self.volume_at_seal else 0

        if self.state == SealState.FAILED:
            return {
                "prediction": "弱势",
                "gap_estimate": "平开或低开",
                "confidence": 0.6,
            }

        if self.break_count >= 3:
            return {"prediction": "偏弱", "gap_estimate": "高开1-3%", "confidence": 0.5}

        if ratio >= 10 and self.break_count == 0:
            return {
                "prediction": "强势",
                "gap_estimate": "涨停或高开8%+",
                "confidence": 0.7,
            }
        if ratio >= 5:
            return {
                "prediction": "偏强",
                "gap_estimate": "高开6-10%",
                "confidence": 0.6,
            }
        if ratio >= 2:
            return {
                "prediction": "中性偏强",
                "gap_estimate": "高开3-6%",
                "confidence": 0.5,
            }
        if ratio >= 1:
            return {"prediction": "中性", "gap_estimate": "高开1-3%", "confidence": 0.4}
        return {"prediction": "偏弱", "gap_estimate": "平开", "confidence": 0.4}


class SealStateMachine:
    """Manages seal lifecycle state machines for multiple stocks."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._lifecycles: dict[str, SealLifecycle] = {}

    def get_lifecycle(self, symbol: str) -> SealLifecycle | None:
        return self._lifecycles.get(symbol)

    def get_all_active(self) -> dict[str, SealLifecycle]:
        """Get all stocks with active (non-NONE, non-FAILED) lifecycles."""
        return {
            sym: lc
            for sym, lc in self._lifecycles.items()
            if lc.state not in (SealState.NONE, SealState.FAILED)
        }

    def update(
        self,
        symbol: str,
        price: float,
        volume: int,
        prev_close: float,
        seal_volume: int = 0,
        timestamp: float | None = None,
        board_type: str = "main",
    ) -> SealLifecycle:
        """Update state machine with latest market data.

        Call this on every tick/quote update for monitored symbols.

        Args:
            symbol: Stock code
            price: Current price
            volume: Current total traded volume
            prev_close: Previous day's close (for limit-up calculation)
            seal_volume: Current seal order volume (0 if not at limit)
            timestamp: Unix timestamp (default: now)
            board_type: "main" (10%), "chinext"/"star" (20%)
        """
        ts = timestamp or _time.time()

        limit_pct = 20.0 if board_type in ("chinext", "star") else 10.0
        limit_up = round(prev_close * (1 + limit_pct / 100), 2)

        # Get or create lifecycle
        if symbol not in self._lifecycles:
            self._lifecycles[symbol] = SealLifecycle(
                symbol=symbol,
                board_type=board_type,
                limit_up_price=limit_up,
                prev_close=prev_close,
            )

        lc = self._lifecycles[symbol]
        old_state = lc.state

        # State transitions
        at_limit = price >= limit_up * 0.998  # within 0.2% of limit
        near_limit = price >= limit_up * 0.98  # within 2%

        if lc.state == SealState.NONE:
            if at_limit and seal_volume > 0:
                lc.state = SealState.SEALED
                lc.first_seal_time = ts
                lc.last_seal_time = ts
                lc.seal_volume = seal_volume
                lc.volume_at_seal = volume
            elif near_limit:
                lc.state = SealState.APPROACHING
                lc.first_approach_time = ts

        elif lc.state == SealState.APPROACHING:
            if at_limit and seal_volume > 0:
                lc.state = SealState.SEALED
                lc.first_seal_time = ts
                lc.last_seal_time = ts
                lc.seal_volume = seal_volume
                lc.volume_at_seal = volume
            elif not near_limit:
                lc.state = SealState.FAILED

        elif lc.state == SealState.SEALED:
            if not at_limit:
                lc.state = SealState.BROKEN
                lc.break_count += 1
                depth = (limit_up - price) / limit_up * 100
                lc.max_break_depth_pct = max(lc.max_break_depth_pct, depth)
            else:
                # Update seal metrics
                lc.seal_volume = seal_volume
                lc.peak_seal_volume = max(lc.peak_seal_volume, seal_volume)
                if lc.last_seal_time:
                    lc.total_sealed_duration += ts - lc.last_seal_time
                lc.last_seal_time = ts

        elif lc.state == SealState.BROKEN:
            if at_limit and seal_volume > 0:
                lc.state = SealState.RESEALED
                # Calculate reseal speed
                if lc.transitions:
                    last_break = next(
                        (
                            t
                            for t in reversed(lc.transitions)
                            if t.to_state == SealState.BROKEN
                        ),
                        None,
                    )
                    if last_break:
                        reseal_time = ts - last_break.timestamp
                        # Running average
                        if lc.avg_reseal_speed == 0:
                            lc.avg_reseal_speed = reseal_time
                        else:
                            lc.avg_reseal_speed = (
                                lc.avg_reseal_speed + reseal_time
                            ) / 2
                lc.seal_volume = seal_volume
                lc.last_seal_time = ts
            elif not near_limit:
                lc.state = SealState.FAILED

        elif lc.state == SealState.RESEALED:
            if not at_limit:
                lc.state = SealState.BROKEN
                lc.break_count += 1
                depth = (limit_up - price) / limit_up * 100
                lc.max_break_depth_pct = max(lc.max_break_depth_pct, depth)
            else:
                lc.seal_volume = seal_volume
                lc.peak_seal_volume = max(lc.peak_seal_volume, seal_volume)
                if lc.last_seal_time:
                    lc.total_sealed_duration += ts - lc.last_seal_time
                lc.last_seal_time = ts

        # Record transition
        if lc.state != old_state:
            lc.transitions.append(
                SealTransition(
                    from_state=old_state,
                    to_state=lc.state,
                    timestamp=ts,
                    price=price,
                    volume_at_transition=volume,
                )
            )
            logger.info(
                "Seal state: %s %s->%s @ %.2f (breaks=%d, seal_vol=%d)",
                symbol,
                old_state.value,
                lc.state.value,
                price,
                lc.break_count,
                seal_volume,
            )

            # Store in Redis
            if self._redis:
                try:
                    self._redis.set(
                        f"seal_lifecycle:{symbol}",
                        json.dumps(
                            {
                                "state": lc.state.value,
                                "break_count": lc.break_count,
                                "seal_quality": lc.seal_quality_score,
                                "prediction": lc.next_day_prediction,
                            }
                        ),
                        ex=86400,
                    )
                except Exception as exc:
                    logger.debug("Redis seal lifecycle store failed: %s", exc)

        return lc

    def reset(self, symbol: str) -> None:
        """Reset lifecycle for a symbol (new trading day)."""
        self._lifecycles.pop(symbol, None)

    def reset_all(self) -> None:
        """Reset all lifecycles (call at start of each trading day)."""
        self._lifecycles.clear()
