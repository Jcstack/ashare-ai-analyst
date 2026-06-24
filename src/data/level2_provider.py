"""Unified Level-2 data provider for order book and tick data.

Abstracts over QMT (primary) with simulation fallback for testing.
Provides order book snapshots, tick streams, and historical depth cache.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.level2_provider")


@dataclass
class OrderBookSnapshot:
    """Single point-in-time order book state."""

    symbol: str
    timestamp: float
    last_price: float
    bid_prices: list[float] = field(default_factory=list)
    bid_volumes: list[int] = field(default_factory=list)
    ask_prices: list[float] = field(default_factory=list)
    ask_volumes: list[int] = field(default_factory=list)
    spread: float = 0.0
    mid_price: float = 0.0
    total_bid_volume: int = 0
    total_ask_volume: int = 0


@dataclass
class TickTrade:
    """Single tick-level trade."""

    timestamp: float
    price: float
    volume: int
    amount: float
    direction: str  # "buy", "sell", "neutral"
    is_large: bool = False
    symbol: str = ""


class Level2Provider:
    """Unified Level-2 data provider.

    Primary: QMT (``xtdata.get_full_tick`` with depth)
    Fallback: Simulation mode (constructs from L1 quotes)

    Args:
        redis_client: Optional Redis client for snapshot persistence.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._qmt = self._init_qmt()
        self._snapshot_history: dict[str, list[OrderBookSnapshot]] = {}
        # Large order threshold: orders > this RMB value are "large"
        self._large_order_threshold = 500_000  # 50万

    def _init_qmt(self) -> Any | None:
        """Try to initialize QMT adapter."""
        try:
            from src.data.qmt_adapter import QmtDataAdapter

            adapter = QmtDataAdapter()
            if adapter.is_available():
                logger.info("Level2Provider: QMT available")
                return adapter
        except Exception:
            pass
        logger.info("Level2Provider: QMT unavailable, using simulation mode")
        return None

    @property
    def has_level2(self) -> bool:
        """Whether real Level-2 data is available (QMT connected)."""
        return self._qmt is not None

    # ------------------------------------------------------------------
    # Order book snapshots
    # ------------------------------------------------------------------

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        """Get current order book snapshot.

        Args:
            symbol: 6-digit stock code.

        Returns:
            OrderBookSnapshot or None if unavailable.
        """
        if self._qmt:
            return self._get_qmt_snapshot(symbol)
        return self._simulate_snapshot(symbol)

    def get_snapshots_batch(self, symbols: list[str]) -> dict[str, OrderBookSnapshot]:
        """Batch get order book snapshots.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            Mapping of symbol → OrderBookSnapshot. Missing symbols omitted.
        """
        if self._qmt:
            return self._get_qmt_snapshots_batch(symbols)
        # Simulation fallback: fetch one by one
        results: dict[str, OrderBookSnapshot] = {}
        for sym in symbols:
            snap = self._simulate_snapshot(sym)
            if snap is not None:
                results[sym] = snap
        return results

    # ------------------------------------------------------------------
    # Tick stream
    # ------------------------------------------------------------------

    def get_recent_ticks(self, symbol: str, count: int = 100) -> list[TickTrade]:
        """Get recent tick-level trades.

        Args:
            symbol: 6-digit stock code.
            count: Maximum number of ticks to return.

        Returns:
            List of TickTrade objects. Empty if unavailable.
        """
        if self._qmt:
            return self._get_qmt_ticks(symbol, count)
        return []

    # ------------------------------------------------------------------
    # Snapshot history
    # ------------------------------------------------------------------

    def record_snapshot(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        """Record snapshot for historical tracking (e.g. seal state machine).

        Args:
            symbol: 6-digit stock code.
            snapshot: The snapshot to record.
        """
        history = self._snapshot_history.setdefault(symbol, [])
        history.append(snapshot)
        # Keep last 200 snapshots per symbol (~ 10 minutes at 3s interval)
        if len(history) > 200:
            self._snapshot_history[symbol] = history[-200:]

        # Also store in Redis if available
        if self._redis is not None:
            try:
                key = f"l2:history:{symbol}"
                payload = json.dumps(
                    {
                        "ts": snapshot.timestamp,
                        "bid0": snapshot.bid_prices[0] if snapshot.bid_prices else 0,
                        "ask0": snapshot.ask_prices[0] if snapshot.ask_prices else 0,
                        "bid_vol0": (
                            snapshot.bid_volumes[0] if snapshot.bid_volumes else 0
                        ),
                        "ask_vol0": (
                            snapshot.ask_volumes[0] if snapshot.ask_volumes else 0
                        ),
                        "spread": snapshot.spread,
                        "mid": snapshot.mid_price,
                    }
                )
                self._redis.lpush(key, payload)
                self._redis.ltrim(key, 0, 199)
                self._redis.expire(key, 14400)  # 4 hour TTL
            except Exception as exc:
                logger.debug("Redis snapshot store failed: %s", exc)

    def get_snapshot_history(
        self, symbol: str, count: int = 50
    ) -> list[OrderBookSnapshot]:
        """Get recent snapshot history for a symbol.

        Args:
            symbol: 6-digit stock code.
            count: Maximum number of snapshots to return.

        Returns:
            List of OrderBookSnapshot (most recent last).
        """
        return (self._snapshot_history.get(symbol) or [])[-count:]

    # ------------------------------------------------------------------
    # QMT backend
    # ------------------------------------------------------------------

    def _get_qmt_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        """Extract order book from QMT ``get_order_book()``."""
        try:
            data = self._qmt.get_order_book(symbol)
            if not data:
                return None
            snap = self._dict_to_snapshot(data)
            self.record_snapshot(symbol, snap)
            return snap
        except Exception as exc:
            logger.debug("QMT order book failed for %s: %s", symbol, exc)
            return None

    def _get_qmt_snapshots_batch(
        self, symbols: list[str]
    ) -> dict[str, OrderBookSnapshot]:
        """Batch fetch order books from QMT."""
        try:
            raw = self._qmt.get_order_book_batch(symbols)
            results: dict[str, OrderBookSnapshot] = {}
            for sym, data in raw.items():
                snap = self._dict_to_snapshot(data)
                self.record_snapshot(sym, snap)
                results[sym] = snap
            return results
        except Exception as exc:
            logger.debug("QMT batch order book failed: %s", exc)
            return {}

    def _get_qmt_ticks(self, symbol: str, count: int) -> list[TickTrade]:
        """Extract tick records from QMT."""
        try:
            raw = self._qmt.get_tick_stream(symbol, count)
            return [
                TickTrade(
                    timestamp=t["timestamp"],
                    price=t["price"],
                    volume=t["volume"],
                    amount=t.get("amount", t["price"] * t["volume"]),
                    direction=t["direction"],
                    is_large=t.get("is_large", False),
                    symbol=symbol,
                )
                for t in raw
            ]
        except Exception as exc:
            logger.debug("QMT tick stream failed for %s: %s", symbol, exc)
            return []

    # ------------------------------------------------------------------
    # Simulation fallback
    # ------------------------------------------------------------------

    def _simulate_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        """Simulate order book from real-time quote (when QMT unavailable).

        Creates a synthetic 1-level book from bid/ask in quote data.
        """
        try:
            from src.data.realtime import RealtimeQuoteManager

            rtm = RealtimeQuoteManager()
            quote = rtm.get_single_quote(symbol)
            if not quote or quote.get("price") is None:
                return None

            price = float(quote["price"])
            if price <= 0:
                return None

            # Simulate spread as 0.01 (1 tick for A-shares)
            spread = 0.01
            mid = price
            bid0 = round(price - spread / 2, 2)
            ask0 = round(price + spread / 2, 2)
            vol = int(quote.get("volume", 0))

            return OrderBookSnapshot(
                symbol=symbol,
                timestamp=time.time(),
                last_price=price,
                bid_prices=[bid0],
                bid_volumes=[vol // 4],  # Rough estimate
                ask_prices=[ask0],
                ask_volumes=[vol // 4],
                spread=spread,
                mid_price=mid,
                total_bid_volume=vol // 4,
                total_ask_volume=vol // 4,
            )
        except Exception as exc:
            logger.debug("Simulation snapshot failed for %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_snapshot(data: dict[str, Any]) -> OrderBookSnapshot:
        """Convert a raw order book dict to an OrderBookSnapshot."""
        return OrderBookSnapshot(
            symbol=data.get("symbol", ""),
            timestamp=data.get("timestamp", 0),
            last_price=data.get("last_price", 0),
            bid_prices=data.get("bid_prices", []),
            bid_volumes=data.get("bid_volumes", []),
            ask_prices=data.get("ask_prices", []),
            ask_volumes=data.get("ask_volumes", []),
            spread=data.get("spread", 0),
            mid_price=data.get("mid_price", 0),
            total_bid_volume=data.get("total_bid_volume", 0),
            total_ask_volume=data.get("total_ask_volume", 0),
        )
