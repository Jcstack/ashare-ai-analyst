"""Large order tracking -- merge individual ticks into institutional orders.

Detects institutional buying/selling patterns by aggregating
consecutive same-direction trades and identifying clusters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.large_order_tracker")


@dataclass
class MergedOrder:
    """A merged institutional order reconstructed from tick stream."""

    symbol: str
    direction: str  # "buy" or "sell"
    total_volume: int
    total_amount: float
    avg_price: float
    tick_count: int  # number of individual trades merged
    start_time: float
    end_time: float
    is_iceberg: bool = False  # suspected iceberg order

    @property
    def size_category(self) -> str:
        """Classify order size: super-large / large / medium / small."""
        if self.total_amount >= 1_000_000:  # >=100万
            return "超大单"
        if self.total_amount >= 200_000:  # >=20万
            return "大单"
        if self.total_amount >= 40_000:  # >=4万
            return "中单"
        return "小单"


class LargeOrderTracker:
    """Track and merge individual trades into institutional-scale orders.

    Merge logic: consecutive same-direction trades within a time window
    (default 3 seconds) are merged into a single order.  This reconstructs
    institutional orders that get split by exchange matching engine.

    Also detects iceberg orders: repeated fills of identical size.

    Args:
        merge_window_seconds: Maximum gap between ticks to merge.
        redis_client: Optional Redis client (reserved for future use).
    """

    def __init__(
        self,
        merge_window_seconds: float = 3.0,
        redis_client: Any | None = None,
    ) -> None:
        self._merge_window = merge_window_seconds
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Tick merging
    # ------------------------------------------------------------------

    def merge_ticks(self, ticks: list[Any]) -> list[MergedOrder]:
        """Merge a list of TickTrade objects into institutional orders.

        Args:
            ticks: List of TickTrade objects, sorted by timestamp ascending.

        Returns:
            List of MergedOrder objects.
        """
        if not ticks:
            return []

        merged: list[MergedOrder] = []

        current_direction = ticks[0].direction
        current_volume = 0
        current_amount = 0.0
        current_count = 0
        current_start = ticks[0].timestamp
        current_end = ticks[0].timestamp
        current_symbol: str = getattr(ticks[0], "symbol", "")
        tick_volumes: list[int] = []

        for tick in ticks:
            same_direction = tick.direction == current_direction
            within_window = (tick.timestamp - current_end) <= self._merge_window

            if same_direction and within_window and tick.direction != "neutral":
                # Merge into current order
                current_volume += tick.volume
                current_amount += tick.amount
                current_count += 1
                current_end = tick.timestamp
                tick_volumes.append(tick.volume)
            else:
                # Finalize current order if non-trivial
                if current_volume > 0 and current_direction != "neutral":
                    merged.append(
                        MergedOrder(
                            symbol=current_symbol,
                            direction=current_direction,
                            total_volume=current_volume,
                            total_amount=current_amount,
                            avg_price=(
                                round(current_amount / current_volume, 4)
                                if current_volume
                                else 0
                            ),
                            tick_count=current_count,
                            start_time=current_start,
                            end_time=current_end,
                            is_iceberg=self._detect_iceberg(tick_volumes),
                        )
                    )

                # Start new group
                current_direction = tick.direction
                current_volume = tick.volume
                current_amount = tick.amount
                current_count = 1
                current_start = tick.timestamp
                current_end = tick.timestamp
                current_symbol = getattr(tick, "symbol", current_symbol)
                tick_volumes = [tick.volume]

        # Finalize last group
        if current_volume > 0 and current_direction != "neutral":
            merged.append(
                MergedOrder(
                    symbol=current_symbol,
                    direction=current_direction,
                    total_volume=current_volume,
                    total_amount=current_amount,
                    avg_price=(
                        round(current_amount / current_volume, 4)
                        if current_volume
                        else 0
                    ),
                    tick_count=current_count,
                    start_time=current_start,
                    end_time=current_end,
                    is_iceberg=self._detect_iceberg(tick_volumes),
                )
            )

        return merged

    # ------------------------------------------------------------------
    # Flow summary
    # ------------------------------------------------------------------

    def compute_flow_summary(self, merged_orders: list[MergedOrder]) -> dict[str, Any]:
        """Compute net institutional flow from merged orders.

        Args:
            merged_orders: List of MergedOrder objects.

        Returns:
            Dict with net flow amounts, counts, direction, and strength.
        """
        large_categories = ("大单", "超大单")

        buy_large = sum(
            o.total_amount
            for o in merged_orders
            if o.direction == "buy" and o.size_category in large_categories
        )
        sell_large = sum(
            o.total_amount
            for o in merged_orders
            if o.direction == "sell" and o.size_category in large_categories
        )
        buy_super = sum(
            o.total_amount
            for o in merged_orders
            if o.direction == "buy" and o.size_category == "超大单"
        )
        sell_super = sum(
            o.total_amount
            for o in merged_orders
            if o.direction == "sell" and o.size_category == "超大单"
        )

        net_large = buy_large - sell_large
        net_super = buy_super - sell_super
        total = buy_large + sell_large

        if total == 0:
            direction = "中性"
            strength = 0.0
        elif net_large > 0:
            direction = "买入"
            strength = min(net_large / total, 1.0)
        else:
            direction = "卖出"
            strength = min(abs(net_large) / total, 1.0)

        return {
            "net_large_flow": round(net_large, 2),
            "net_super_large_flow": round(net_super, 2),
            "buy_large_amount": round(buy_large, 2),
            "sell_large_amount": round(sell_large, 2),
            "large_buy_count": sum(
                1
                for o in merged_orders
                if o.direction == "buy" and o.size_category in large_categories
            ),
            "large_sell_count": sum(
                1
                for o in merged_orders
                if o.direction == "sell" and o.size_category in large_categories
            ),
            "iceberg_count": sum(1 for o in merged_orders if o.is_iceberg),
            "institutional_direction": direction,
            "institutional_strength": round(strength, 4),
        }

    # ------------------------------------------------------------------
    # Iceberg detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_iceberg(tick_volumes: list[int]) -> bool:
        """Detect iceberg order pattern: >=5 consecutive fills of identical size.

        Args:
            tick_volumes: List of individual trade volumes in the group.

        Returns:
            True if an iceberg pattern is detected.
        """
        if len(tick_volumes) < 5:
            return False

        max_consecutive = 1
        current = 1
        for i in range(1, len(tick_volumes)):
            if tick_volumes[i] == tick_volumes[i - 1] and tick_volumes[i] > 0:
                current += 1
                max_consecutive = max(max_consecutive, current)
            else:
                current = 1
        return max_consecutive >= 5
