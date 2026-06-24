"""Order book microstructure factor engine.

Computes factors from Level-2 order book snapshots that capture
institutional positioning and short-horizon price dynamics.

Academic basis: Order Flow Imbalance (OFI) has near-linear
relationship with short-horizon price changes (Cont et al., 2014).
"""

from __future__ import annotations

import math

from src.utils.logger import get_logger

logger = get_logger("quant.orderbook_factors")

__all__ = [
    "OrderBookFactorEngine",
]

# Large order threshold in RMB (50万)
_LARGE_ORDER_THRESHOLD = 500_000


class OrderBookFactorEngine:
    """Compute microstructure factors from order book data.

    All factors normalized to [0, 1] with 0.5 = neutral, matching
    the convention used by IntradayFactorEngine.

    Expected data shapes:
        snapshot: object with attributes
            - bid_prices: list[float]  (descending, best first)
            - bid_volumes: list[float]
            - ask_prices: list[float]  (ascending, best first)
            - ask_volumes: list[float]
        history: list of snapshot objects (oldest first)
        ticks: list of objects with attributes
            - price: float
            - volume: float
            - amount: float
            - direction: int  (+1 = buy-initiated, -1 = sell-initiated)
    """

    def compute(
        self,
        snapshot: object | None,
        history: list | None = None,
        ticks: list | None = None,
    ) -> dict[str, float]:
        """Compute all order book factors.

        Args:
            snapshot: OrderBookSnapshot (current state)
            history: list of recent OrderBookSnapshot objects
            ticks: list of recent TickTrade objects

        Returns dict of factors, all in [0, 1].
        """
        if snapshot is None:
            return self._neutral_factors()

        factors: dict[str, float] = {}
        factors["depth_imbalance"] = self._depth_imbalance(snapshot)
        factors["spread_normalized"] = self._spread_factor(snapshot)
        factors["order_flow_imbalance"] = (
            self._ofi(history) if history and len(history) >= 2 else 0.5
        )
        factors["bid_wall_strength"] = self._wall_detection(snapshot, side="bid")
        factors["ask_wall_strength"] = self._wall_detection(snapshot, side="ask")
        factors["trade_direction_ratio"] = (
            self._trade_direction(ticks) if ticks else 0.5
        )
        factors["large_order_pressure"] = (
            self._large_order_pressure(ticks) if ticks else 0.5
        )
        factors["depth_resilience"] = (
            self._depth_resilience(history) if history and len(history) >= 2 else 0.5
        )
        factors["micro_momentum"] = (
            self._micro_momentum(history) if history and len(history) >= 2 else 0.5
        )
        factors["volume_imbalance_ratio"] = self._volume_imbalance(snapshot)

        return factors

    def compute_batch(self, data: dict) -> dict[str, dict[str, float]]:
        """Batch compute.

        Args:
            data: {symbol: {"snapshot": ..., "history": ..., "ticks": ...}}
        """
        result: dict[str, dict[str, float]] = {}
        for symbol, d in data.items():
            try:
                result[symbol] = self.compute(
                    d.get("snapshot"), d.get("history"), d.get("ticks")
                )
            except Exception as exc:
                logger.debug("Orderbook factors failed for %s: %s", symbol, exc)
                result[symbol] = self._neutral_factors()
        return result

    # ------------------------------------------------------------------
    # Factor computations
    # ------------------------------------------------------------------

    @staticmethod
    def _depth_imbalance(snapshot: object) -> float:
        """Bid/ask volume ratio across all visible levels.

        = total_bid_volume / (total_bid_volume + total_ask_volume)
        >0.5 = more buy pressure, <0.5 = more sell pressure.
        """
        bid_vols = getattr(snapshot, "bid_volumes", [])
        ask_vols = getattr(snapshot, "ask_volumes", [])

        total_bid = sum(v for v in bid_vols if v > 0)
        total_ask = sum(v for v in ask_vols if v > 0)
        total = total_bid + total_ask

        if total <= 0:
            return 0.5

        return round(total_bid / total, 4)

    @staticmethod
    def _spread_factor(snapshot: object) -> float:
        """Bid-ask spread relative to mid price.

        Tight spread = high value (liquid), wide spread = low value.
        = 1.0 - min(spread / (mid_price * 0.005), 1.0)
        """
        bid_prices = getattr(snapshot, "bid_prices", [])
        ask_prices = getattr(snapshot, "ask_prices", [])

        if not bid_prices or not ask_prices:
            return 0.5

        best_bid = bid_prices[0]
        best_ask = ask_prices[0]

        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            return 0.5

        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0

        if mid_price <= 0:
            return 0.5

        # Normalize: spread / (mid * 0.5%) — 0.5% spread is "wide"
        normalized = spread / (mid_price * 0.005)
        return round(max(0.0, min(1.0, 1.0 - normalized)), 4)

    @staticmethod
    def _ofi(history: list) -> float:
        """Order Flow Imbalance: change in best bid vol minus change in best ask vol.

        Positive OFI = buying pressure building, negative = selling.
        Normalized via sigmoid to [0, 1].
        """
        if not history or len(history) < 2:
            return 0.5

        current = history[-1]
        previous = history[0] if len(history) <= 5 else history[-5]

        cur_bid_vol = (
            getattr(current, "bid_volumes", [0])[0]
            if getattr(current, "bid_volumes", [])
            else 0
        )
        prev_bid_vol = (
            getattr(previous, "bid_volumes", [0])[0]
            if getattr(previous, "bid_volumes", [])
            else 0
        )
        cur_ask_vol = (
            getattr(current, "ask_volumes", [0])[0]
            if getattr(current, "ask_volumes", [])
            else 0
        )
        prev_ask_vol = (
            getattr(previous, "ask_volumes", [0])[0]
            if getattr(previous, "ask_volumes", [])
            else 0
        )

        delta_bid = cur_bid_vol - prev_bid_vol
        delta_ask = cur_ask_vol - prev_ask_vol
        ofi = delta_bid - delta_ask

        # Normalize: large values are meaningful; scale by average volume
        avg_vol = max((cur_bid_vol + cur_ask_vol) / 2.0, 1.0)
        ofi_scaled = ofi / avg_vol  # relative change

        # Sigmoid normalization
        return round(1.0 / (1.0 + math.exp(-ofi_scaled * 3.0)), 4)

    @staticmethod
    def _wall_detection(snapshot: object, side: str = "bid") -> float:
        """Detect large order walls.

        Factor = max(vol_i / avg_vol) / 5, clamped to [0, 1].
        High = strong wall present.
        """
        if side == "bid":
            volumes = getattr(snapshot, "bid_volumes", [])
        else:
            volumes = getattr(snapshot, "ask_volumes", [])

        if not volumes or len(volumes) < 2:
            return 0.5

        vols = [v for v in volumes if v > 0]
        if not vols:
            return 0.5

        avg_vol = sum(vols) / len(vols)
        if avg_vol <= 0:
            return 0.5

        max_ratio = max(v / avg_vol for v in vols)
        # Wall if any level > 3x average; normalize by /5 for [0, 1] range
        factor = max_ratio / 5.0
        return round(max(0.0, min(1.0, factor)), 4)

    @staticmethod
    def _trade_direction(ticks: list) -> float:
        """Buy/sell trade classification ratio.

        = buy_count / (buy_count + sell_count)
        >0.5 = more aggressive buying.
        """
        if not ticks:
            return 0.5

        buy_count = 0
        sell_count = 0
        for t in ticks:
            direction = getattr(t, "direction", 0)
            if direction > 0:
                buy_count += 1
            elif direction < 0:
                sell_count += 1

        total = buy_count + sell_count
        if total == 0:
            return 0.5

        return round(buy_count / total, 4)

    @staticmethod
    def _large_order_pressure(ticks: list) -> float:
        """Net direction of large orders (>50万 RMB).

        = large_buy_amount / (large_buy_amount + large_sell_amount)
        >0.5 = institutional buying, <0.5 = institutional selling.
        """
        if not ticks:
            return 0.5

        large_buy = 0.0
        large_sell = 0.0

        for t in ticks:
            amount = getattr(t, "amount", 0.0)
            direction = getattr(t, "direction", 0)

            if amount < _LARGE_ORDER_THRESHOLD:
                continue

            if direction > 0:
                large_buy += amount
            elif direction < 0:
                large_sell += amount

        total = large_buy + large_sell
        if total <= 0:
            return 0.5

        return round(large_buy / total, 4)

    @staticmethod
    def _depth_resilience(history: list) -> float:
        """How quickly bid levels recover after being hit.

        Compare current best bid volume to average of recent snapshots.
        Recovery after drop = resilient (bullish).
        """
        if not history or len(history) < 2:
            return 0.5

        # Collect best bid volumes from history
        bid_vols: list[float] = []
        for snap in history:
            vols = getattr(snap, "bid_volumes", [])
            if vols:
                bid_vols.append(vols[0])

        if len(bid_vols) < 2:
            return 0.5

        current_vol = bid_vols[-1]
        # Average of earlier snapshots (exclude current)
        avg_past = sum(bid_vols[:-1]) / len(bid_vols[:-1])

        if avg_past <= 0:
            return 0.5

        # Ratio: >1 means recovered/grew, <1 means depleted
        ratio = current_vol / avg_past

        # Check if there was a recent dip (min in middle < avg)
        min_vol = min(bid_vols)
        had_dip = min_vol < avg_past * 0.7

        if had_dip and ratio >= 0.9:
            # Recovered from a dip — resilient
            resilience = min(ratio / 1.5, 1.0)
            return round(0.5 + resilience * 0.3, 4)

        # No significant dip — use simple ratio
        # ratio ~1 → 0.5, ratio > 1 → higher, ratio < 1 → lower
        normalized = 1.0 / (1.0 + math.exp(-(ratio - 1.0) * 5.0))
        return round(normalized, 4)

    @staticmethod
    def _micro_momentum(history: list) -> float:
        """Short-term mid-price direction via linear fit.

        Compare mid_price of last 5 snapshots.
        Trending up → >0.5, down → <0.5.
        """
        if not history or len(history) < 2:
            return 0.5

        # Use last 5 snapshots (or fewer if not available)
        recent = history[-5:] if len(history) >= 5 else history

        mid_prices: list[float] = []
        for snap in recent:
            bids = getattr(snap, "bid_prices", [])
            asks = getattr(snap, "ask_prices", [])
            if bids and asks and bids[0] > 0 and asks[0] > 0:
                mid_prices.append((bids[0] + asks[0]) / 2.0)

        if len(mid_prices) < 2:
            return 0.5

        # Simple linear regression slope
        n = len(mid_prices)
        x_mean = (n - 1) / 2.0
        y_mean = sum(mid_prices) / n

        numerator = sum((i - x_mean) * (p - y_mean) for i, p in enumerate(mid_prices))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator <= 0:
            return 0.5

        slope = numerator / denominator
        # Normalize slope relative to price level
        rel_slope = slope / y_mean if y_mean > 0 else 0.0

        # Sigmoid: ±0.1% per step is significant
        return round(1.0 / (1.0 + math.exp(-rel_slope * 1000.0)), 4)

    @staticmethod
    def _volume_imbalance(snapshot: object) -> float:
        """Best-level-only bid/ask volume imbalance.

        = bid_vol[0] / (bid_vol[0] + ask_vol[0])
        Different from depth_imbalance which uses all levels.
        """
        bid_vols = getattr(snapshot, "bid_volumes", [])
        ask_vols = getattr(snapshot, "ask_volumes", [])

        if not bid_vols or not ask_vols:
            return 0.5

        best_bid_vol = bid_vols[0]
        best_ask_vol = ask_vols[0]
        total = best_bid_vol + best_ask_vol

        if total <= 0:
            return 0.5

        return round(best_bid_vol / total, 4)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _neutral_factors() -> dict[str, float]:
        """Return neutral (no-signal) factors when data unavailable."""
        return {
            "depth_imbalance": 0.5,
            "spread_normalized": 0.5,
            "order_flow_imbalance": 0.5,
            "bid_wall_strength": 0.5,
            "ask_wall_strength": 0.5,
            "trade_direction_ratio": 0.5,
            "large_order_pressure": 0.5,
            "depth_resilience": 0.5,
            "micro_momentum": 0.5,
            "volume_imbalance_ratio": 0.5,
        }
