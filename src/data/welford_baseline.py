"""Welford online algorithm for temporal baselines.

Computes running mean and variance in O(1) per update, segmented by
day-of-week (5) x time-slot (half-hour, ~10 per A-share session) = 50 segments.

Used for z-score anomaly detection in price spike and volume anomaly detectors.

Per PRD v50.0 §9.5: Welford temporal baselines for real-time anomaly detection.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.welford_baseline")

# A-share trading sessions: 09:30-11:30 and 13:00-15:00
# Half-hour slots: 09:30, 10:00, 10:30, 11:00, 11:30, 13:00, 13:30, 14:00, 14:30, 15:00
# That gives us 10 slots (index 0-9)
_MORNING_START_MINUTES = 9 * 60 + 30  # 09:30
_MORNING_END_MINUTES = 11 * 60 + 30  # 11:30
_AFTERNOON_START_MINUTES = 13 * 60  # 13:00
_AFTERNOON_END_MINUTES = 15 * 60  # 15:00
_SLOT_DURATION_MINUTES = 30

# Minimum samples before z-scores are considered valid
MIN_SAMPLES = 20


def time_to_slot(hour: int, minute: int) -> int | None:
    """Convert a time (hour, minute) to a half-hour slot index.

    Returns None if the time is outside A-share trading hours.

    Args:
        hour: Hour in 24h format (0-23).
        minute: Minute (0-59).

    Returns:
        Slot index (0-9) or None if outside trading hours.
    """
    total_minutes = hour * 60 + minute

    if _MORNING_START_MINUTES <= total_minutes < _MORNING_END_MINUTES:
        return (total_minutes - _MORNING_START_MINUTES) // _SLOT_DURATION_MINUTES
    elif total_minutes == _MORNING_END_MINUTES:
        # 11:30 belongs to slot 3 (the last morning slot)
        return 3

    morning_slots = 4  # 09:30, 10:00, 10:30, 11:00 (indices 0-3)

    if _AFTERNOON_START_MINUTES <= total_minutes < _AFTERNOON_END_MINUTES:
        afternoon_offset = (
            total_minutes - _AFTERNOON_START_MINUTES
        ) // _SLOT_DURATION_MINUTES
        return morning_slots + afternoon_offset
    elif total_minutes == _AFTERNOON_END_MINUTES:
        return morning_slots + 3  # 15:00 belongs to last afternoon slot

    return None


def segment_key(day_of_week: int, slot: int) -> str:
    """Build a segment key string.

    Args:
        day_of_week: 0=Monday .. 4=Friday.
        slot: Half-hour slot index (0-9).

    Returns:
        Segment key like "d0_s3".
    """
    return f"d{day_of_week}_s{slot}"


NUM_DAYS = 5
NUM_SLOTS = 10  # adjusted: 4 morning + 4 afternoon + 2 boundary = approx 8-10
TOTAL_SEGMENTS = NUM_DAYS * NUM_SLOTS


@dataclass
class WelfordState:
    """Running statistics for a single segment using Welford's algorithm.

    Attributes:
        count: Number of samples seen.
        mean: Running mean.
        m2: Running sum of squared differences from the mean.
    """

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def update(self, value: float) -> None:
        """Incorporate a new sample.

        Args:
            value: The new observation.
        """
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        """Population variance (0.0 if fewer than 2 samples)."""
        if self.count < 2:
            return 0.0
        return self.m2 / self.count

    @property
    def std(self) -> float:
        """Population standard deviation."""
        return math.sqrt(self.variance)

    @property
    def is_valid(self) -> bool:
        """Whether enough samples have been collected for reliable z-scores."""
        return self.count >= MIN_SAMPLES

    def z_score(self, value: float) -> float | None:
        """Compute z-score for a value against this segment's baseline.

        Args:
            value: The observation to score.

        Returns:
            Z-score, or None if insufficient samples or zero variance.
        """
        if not self.is_valid:
            return None
        sigma = self.std
        if sigma < 1e-12:
            return None
        return (value - self.mean) / sigma

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict for Redis persistence."""
        return {"count": self.count, "mean": self.mean, "m2": self.m2}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WelfordState:
        """Deserialize from a dict."""
        return cls(
            count=int(d.get("count", 0)),
            mean=float(d.get("mean", 0.0)),
            m2=float(d.get("m2", 0.0)),
        )


class WelfordBaseline:
    """Temporal baseline manager using Welford's online algorithm.

    Maintains per-segment (day-of-week x time-slot) statistics for one
    metric of one symbol. Optionally persists state to Redis.

    Args:
        symbol: Stock symbol (e.g. "000001").
        metric: Metric name (e.g. "volume", "flow", "velocity", "spread").
        redis_client: Optional redis.Redis instance for persistence.
        redis_prefix: Key prefix for Redis storage.
    """

    def __init__(
        self,
        symbol: str,
        metric: str,
        redis_client: Any | None = None,
        redis_prefix: str = "welford",
    ) -> None:
        self.symbol = symbol
        self.metric = metric
        self._redis = redis_client
        self._prefix = redis_prefix
        self._segments: dict[str, WelfordState] = {}

        if self._redis is not None:
            self._load_from_redis()

    def _redis_key(self) -> str:
        """Redis hash key for this symbol+metric."""
        return f"{self._prefix}:{self.symbol}:{self.metric}"

    def _load_from_redis(self) -> None:
        """Load all segment states from Redis hash."""
        if self._redis is None:
            return
        try:
            raw = self._redis.hgetall(self._redis_key())
            for seg_key, json_str in raw.items():
                data = json.loads(json_str)
                self._segments[seg_key] = WelfordState.from_dict(data)
            if raw:
                logger.debug(
                    "Loaded %d segments from Redis for %s/%s",
                    len(raw),
                    self.symbol,
                    self.metric,
                )
        except Exception:
            logger.warning(
                "Failed to load Welford state from Redis for %s/%s",
                self.symbol,
                self.metric,
                exc_info=True,
            )

    def _save_segment(self, seg_key: str) -> None:
        """Persist a single segment to Redis."""
        if self._redis is None:
            return
        try:
            state = self._segments[seg_key]
            self._redis.hset(
                self._redis_key(),
                seg_key,
                json.dumps(state.to_dict()),
            )
        except Exception:
            logger.warning(
                "Failed to save Welford state to Redis for %s/%s/%s",
                self.symbol,
                self.metric,
                seg_key,
                exc_info=True,
            )

    def update(self, day_of_week: int, hour: int, minute: int, value: float) -> None:
        """Update the baseline with a new observation.

        Args:
            day_of_week: 0=Monday .. 4=Friday.
            hour: Hour in 24h format.
            minute: Minute.
            value: The observed metric value.
        """
        slot = time_to_slot(hour, minute)
        if slot is None:
            return  # Outside trading hours
        if not (0 <= day_of_week <= 4):
            return  # Weekend

        seg = segment_key(day_of_week, slot)
        if seg not in self._segments:
            self._segments[seg] = WelfordState()
        self._segments[seg].update(value)
        self._save_segment(seg)

    def z_score(
        self, day_of_week: int, hour: int, minute: int, value: float
    ) -> float | None:
        """Compute z-score for a value against the temporal baseline.

        Args:
            day_of_week: 0=Monday .. 4=Friday.
            hour: Hour in 24h format.
            minute: Minute.
            value: The observed metric value.

        Returns:
            Z-score, or None if outside trading hours or insufficient data.
        """
        slot = time_to_slot(hour, minute)
        if slot is None:
            return None
        if not (0 <= day_of_week <= 4):
            return None

        seg = segment_key(day_of_week, slot)
        state = self._segments.get(seg)
        if state is None:
            return None
        return state.z_score(value)

    def get_segment_state(self, day_of_week: int, slot: int) -> WelfordState | None:
        """Get the state for a specific segment.

        Args:
            day_of_week: 0=Monday .. 4=Friday.
            slot: Half-hour slot index (0-9).

        Returns:
            WelfordState or None if no data for this segment.
        """
        seg = segment_key(day_of_week, slot)
        return self._segments.get(seg)

    @property
    def segment_count(self) -> int:
        """Number of segments with at least one sample."""
        return len(self._segments)

    @property
    def valid_segment_count(self) -> int:
        """Number of segments with enough samples for valid z-scores."""
        return sum(1 for s in self._segments.values() if s.is_valid)
