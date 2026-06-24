"""Reflexivity loop detector -- Soros-inspired feedback loop analysis.

Detects self-reinforcing price-volume feedback loops and identifies
when they are strengthening (trend continuation) vs. exhausting
(imminent reversal).

Core metric: Reflexivity Score = price_acceleration * volume_acceleration
- Positive score = loop strengthening (price and volume both accelerating)
- Negative score = loop exhausting (one or both decelerating)
- Near zero = no feedback loop active

Reference: George Soros, "The Alchemy of Finance" (1987)
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("agent_loop.reflexivity_detector")

__all__ = [
    "ReflexivityDetector",
    "ReflexivityResult",
]


@dataclasses.dataclass
class ReflexivityResult:
    """Result of reflexivity feedback loop analysis."""

    symbol: str
    reflexivity_score: float  # -1 to +1, compound acceleration metric
    loop_state: str  # "strengthening" | "exhausting" | "breaking" | "none"
    price_acceleration: float  # 2nd derivative of price (normalized)
    volume_acceleration: float  # 2nd derivative of volume (normalized)
    loop_duration_bars: int  # consecutive bars with same-sign score
    reversal_probability: float  # 0-1, estimated probability of reversal
    direction: str  # "bullish" | "bearish"
    severity: float  # 0-1, for signal aggregator compatibility
    description: str  # Chinese description


class ReflexivityDetector:
    """Detect and score reflexivity feedback loops from minute bar data."""

    # Minimum bars needed for acceleration calculation
    MIN_BARS = 15  # ~75 minutes at 5-min resolution
    # Acceleration smoothing window
    SMOOTH_WINDOW = 5
    # Score threshold for loop detection
    LOOP_THRESHOLD = 0.01

    def analyze(self, bars: pd.DataFrame, symbol: str) -> ReflexivityResult:
        """Analyze bars for reflexivity feedback loops.

        Args:
            bars: DataFrame with [datetime, open, high, low, close, volume, amount]
            symbol: stock code

        Returns:
            ReflexivityResult with loop analysis
        """
        if bars is None or bars.empty or len(bars) < self.MIN_BARS:
            logger.debug(
                "Insufficient bars for %s (%d < %d), returning neutral",
                symbol,
                0 if bars is None else len(bars),
                self.MIN_BARS,
            )
            return self._neutral_result(symbol)

        df = bars.copy()

        # --- Price acceleration (2nd derivative) ---
        returns = df["close"].pct_change()
        r_smooth = returns.rolling(self.SMOOTH_WINDOW).mean()
        r_accel_series = r_smooth.diff()
        price_accel_raw = r_accel_series.iloc[-1]
        price_accel = (
            float(np.tanh(price_accel_raw * 100)) if pd.notna(price_accel_raw) else 0.0
        )

        # --- Volume acceleration (2nd derivative) ---
        v_change = df["volume"].pct_change()
        v_smooth = v_change.rolling(self.SMOOTH_WINDOW).mean()
        v_accel_series = v_smooth.diff()
        vol_accel_raw = v_accel_series.iloc[-1]
        vol_accel = (
            float(np.tanh(vol_accel_raw * 10)) if pd.notna(vol_accel_raw) else 0.0
        )

        # --- Reflexivity score ---
        score = price_accel * vol_accel

        # --- Score time series for loop duration ---
        score_series = np.tanh(r_accel_series * 100) * np.tanh(v_accel_series * 10)
        score_values = score_series.dropna().values
        loop_duration = self._compute_loop_duration(score_values)

        # --- Direction from price momentum (1st derivative) ---
        last_momentum = r_smooth.iloc[-1] if pd.notna(r_smooth.iloc[-1]) else 0.0
        direction = "bullish" if last_momentum > 0 else "bearish"
        direction_cn = "看多" if direction == "bullish" else "看空"

        # --- Loop state classification ---
        # Check history: was the score positive before?
        prev_positive_run = self._prev_positive_run(score_values)
        loop_state = self._classify_loop_state(score, loop_duration, prev_positive_run)

        # --- Reversal probability ---
        reversal_prob = self._compute_reversal_probability(
            loop_state, loop_duration, score
        )

        # --- Severity ---
        severity = self._compute_severity(loop_state, score)

        # --- Chinese description ---
        description = self._build_description(
            loop_state, direction_cn, reversal_prob, score, price_accel, vol_accel
        )

        return ReflexivityResult(
            symbol=symbol,
            reflexivity_score=round(score, 4),
            loop_state=loop_state,
            price_acceleration=round(price_accel, 4),
            volume_acceleration=round(vol_accel, 4),
            loop_duration_bars=loop_duration,
            reversal_probability=round(reversal_prob, 4),
            direction=direction,
            severity=round(severity, 4),
            description=description,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_loop_duration(score_values: np.ndarray) -> int:
        """Count consecutive bars at the end with the same score sign."""
        if len(score_values) == 0:
            return 0
        last_sign = 1 if score_values[-1] > 0 else -1
        count = 0
        for val in reversed(score_values):
            if (val > 0 and last_sign > 0) or (val <= 0 and last_sign <= 0):
                count += 1
            else:
                break
        return count

    @staticmethod
    def _prev_positive_run(score_values: np.ndarray) -> int:
        """Count the positive run length before the current negative streak."""
        if len(score_values) == 0:
            return 0
        # Skip current negative streak
        idx = len(score_values) - 1
        while idx >= 0 and score_values[idx] <= 0:
            idx -= 1
        # Count positive run
        run = 0
        while idx >= 0 and score_values[idx] > 0:
            run += 1
            idx -= 1
        return run

    def _classify_loop_state(
        self, score: float, loop_duration: int, prev_positive_run: int
    ) -> str:
        """Classify the current feedback loop state."""
        if abs(score) < self.LOOP_THRESHOLD:
            return "none"
        if score > self.LOOP_THRESHOLD and loop_duration >= 3:
            return "strengthening"
        if score > self.LOOP_THRESHOLD and loop_duration < 3:
            # Positive but not yet persisting — still "none"
            return "none"
        if score < -self.LOOP_THRESHOLD:
            if prev_positive_run >= 5 and score < -0.05:
                return "breaking"
            return "exhausting"
        return "none"

    @staticmethod
    def _compute_reversal_probability(
        loop_state: str, loop_duration: int, score: float
    ) -> float:
        """Estimate reversal probability based on loop dynamics."""
        base_prob = min(0.8, loop_duration / 20.0)

        if loop_state == "exhausting":
            prob = base_prob * 1.3
        elif loop_state == "breaking":
            prob = min(0.95, base_prob * 1.5)
        elif loop_state == "strengthening":
            prob = max(0.05, 1.0 - base_prob)
        else:
            prob = 0.1  # No active loop — low reversal probability

        return max(0.0, min(1.0, prob))

    @staticmethod
    def _compute_severity(loop_state: str, score: float) -> float:
        """Compute severity for signal aggregator compatibility."""
        if loop_state in ("exhausting", "breaking"):
            return min(1.0, abs(score) * 2)
        if loop_state == "strengthening":
            return min(1.0, score)
        return 0.0

    @staticmethod
    def _build_description(
        loop_state: str,
        direction_cn: str,
        reversal_prob: float,
        score: float,
        price_accel: float,
        vol_accel: float,
    ) -> str:
        """Build Chinese description of the reflexivity state."""
        continuation_pct = f"{(1 - reversal_prob) * 100:.0f}%"
        reversal_pct = f"{reversal_prob * 100:.0f}%"

        if loop_state == "strengthening":
            return (
                f"反身性循环加强中：价量双双加速，"
                f"趋势{direction_cn}延续概率{continuation_pct}"
            )

        if loop_state == "exhausting":
            if abs(price_accel) > abs(vol_accel):
                detail = "量能衰减但价格仍在运动"
            else:
                detail = "价格动能减弱"
            return f"反身性循环衰竭：{detail}，反转概率{reversal_pct}"

        if loop_state == "breaking":
            if abs(price_accel) > abs(vol_accel):
                detail = "价量加速分离，循环已无法自我维持"
            else:
                detail = "量价反馈断裂，趋势失去支撑"
            return f"\u26a0\ufe0f 反身性循环断裂！{detail}，高度警惕反转"

        return "未检测到反身性循环"

    @staticmethod
    def _neutral_result(symbol: str) -> ReflexivityResult:
        """Return a neutral result when data is insufficient."""
        return ReflexivityResult(
            symbol=symbol,
            reflexivity_score=0.0,
            loop_state="none",
            price_acceleration=0.0,
            volume_acceleration=0.0,
            loop_duration_bars=0,
            reversal_probability=0.0,
            direction="bullish",
            severity=0.0,
            description="数据不足，无法分析反身性循环",
        )
