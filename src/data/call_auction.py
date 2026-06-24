"""Call auction (集合竞价) data collector and analyzer.

Captures real-time quote snapshots during the 9:15-9:25 call auction
window and analyzes price/volume trajectories to detect weak-to-strong
transitions, volume acceleration, and other auction signals.

Uses RealtimeQuoteManager for live quote snapshots and Redis sorted sets
for trajectory storage.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.call_auction")

# Auction window boundaries (HH:MM)
_AUCTION_START = "09:15"
_AUCTION_MID = "09:20"
_AUCTION_END = "09:25"


class CallAuctionCollector:
    """Collect and analyze call auction (集合竞价) data.

    Uses real-time quote snapshots during 9:15-9:25 to detect:
    - Price trajectory during auction
    - Volume accumulation pattern
    - Weak-to-strong transitions (9:20-9:25)

    Args:
        redis_client: Optional Redis client for storing auction snapshots.
            If None, snapshots are stored in-memory only (lost between calls).
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._quote_mgr: Any | None = None
        # In-memory fallback when Redis is unavailable
        self._mem_snapshots: dict[str, list[dict]] = {}

    def _get_quote_manager(self) -> Any:
        """Lazily initialize RealtimeQuoteManager."""
        if self._quote_mgr is None:
            from src.data.realtime import RealtimeQuoteManager

            self._quote_mgr = RealtimeQuoteManager()
        return self._quote_mgr

    def capture_snapshot(self, symbols: list[str]) -> list[dict]:
        """Capture current auction state for given symbols.

        Uses RealtimeQuoteManager to get: price, volume, bid/ask.
        Stores snapshot with timestamp in Redis for trajectory analysis.

        Args:
            symbols: List of stock codes to capture.

        Returns:
            List of dicts with keys: symbol, auction_price, auction_volume,
            bid_ask_ratio, timestamp.
        """
        if not symbols:
            return []

        try:
            mgr = self._get_quote_manager()
            df = mgr.get_quotes(symbols)
        except Exception as exc:
            logger.warning("Failed to get auction quotes: %s", exc)
            return []

        if df.empty:
            return []

        now = datetime.now()
        ts = now.strftime("%H:%M:%S")
        ts_score = now.timestamp()
        snapshots: list[dict] = []

        for _, row in df.iterrows():
            symbol = str(row.get("symbol", ""))
            price = row.get("price")
            volume = row.get("volume")

            if not symbol or price is None:
                continue

            snapshot = {
                "symbol": symbol,
                "auction_price": float(price) if price else 0.0,
                "auction_volume": int(volume) if volume else 0,
                "bid_ask_ratio": 0.0,  # derived from order book when available
                "timestamp": ts,
            }
            snapshots.append(snapshot)
            self._store_snapshot(symbol, snapshot, ts_score)

        logger.debug("Captured %d auction snapshots at %s", len(snapshots), ts)
        return snapshots

    def analyze_auction(self, symbol: str) -> dict:
        """Analyze auction trajectory from stored snapshots.

        Examines price and volume progression across the auction window
        to identify momentum patterns.

        Args:
            symbol: Stock code to analyze.

        Returns:
            Dict with analysis results including price_trend,
            volume_acceleration, weak_to_strong, etc.
        """
        snapshots = self._load_snapshots(symbol)

        result: dict[str, Any] = {
            "symbol": symbol,
            "price_trend": "stable",
            "volume_acceleration": 0.0,
            "weak_to_strong": False,
            "strong_to_weak": False,
            "final_price": 0.0,
            "final_volume": 0,
            "confidence": 0.0,
        }

        if not snapshots:
            return result

        # Sort by timestamp
        snapshots.sort(key=lambda s: s.get("timestamp", ""))

        # Extract price and volume series
        prices = [s["auction_price"] for s in snapshots if s.get("auction_price")]
        volumes = [s["auction_volume"] for s in snapshots if s.get("auction_volume")]

        if not prices:
            return result

        result["final_price"] = prices[-1]
        result["final_volume"] = volumes[-1] if volumes else 0

        # Confidence based on number of snapshots (more data = higher confidence)
        # Ideal: ~20 snapshots over 10 minutes (one every 30s)
        result["confidence"] = min(1.0, len(snapshots) / 10.0)

        # Price trend: compare first half vs second half averages
        if len(prices) >= 4:
            mid = len(prices) // 2
            first_avg = sum(prices[:mid]) / mid
            second_avg = sum(prices[mid:]) / (len(prices) - mid)

            if first_avg > 0:
                pct_change = (second_avg - first_avg) / first_avg * 100
                if pct_change > 0.3:
                    result["price_trend"] = "rising"
                elif pct_change < -0.3:
                    result["price_trend"] = "falling"

        # Volume acceleration: compare volume growth in last third vs first third
        if len(volumes) >= 3:
            third = len(volumes) // 3
            early_vol = volumes[third - 1] if volumes[third - 1] > 0 else 1
            late_vol = volumes[-1] if volumes[-1] > 0 else 0
            result["volume_acceleration"] = round(late_vol / early_vol, 2)

        # Weak-to-strong detection: price falling in early phase, rising in late
        # Split snapshots at approximate 9:20 boundary
        early_snaps = [s for s in snapshots if s.get("timestamp", "") < "09:20:00"]
        late_snaps = [s for s in snapshots if s.get("timestamp", "") >= "09:20:00"]

        if len(early_snaps) >= 2 and len(late_snaps) >= 2:
            early_prices = [s["auction_price"] for s in early_snaps]
            late_prices = [s["auction_price"] for s in late_snaps]

            early_trend = early_prices[-1] - early_prices[0]
            late_trend = late_prices[-1] - late_prices[0]

            if early_trend < 0 and late_trend > 0:
                result["weak_to_strong"] = True
            elif early_trend > 0 and late_trend < 0:
                result["strong_to_weak"] = True

        return result

    def get_auction_candidates(self, min_volume: int = 100000) -> list[dict]:
        """Return symbols showing strong auction signals.

        Filters stored auction data for symbols with high volume and
        rising price trajectory.

        Args:
            min_volume: Minimum auction volume to qualify as candidate.

        Returns:
            List of analysis dicts for qualifying symbols, sorted by
            volume descending.
        """
        candidates: list[dict] = []
        all_symbols = self._get_tracked_symbols()

        for symbol in all_symbols:
            analysis = self.analyze_auction(symbol)
            if (
                analysis["final_volume"] >= min_volume
                and analysis["price_trend"] == "rising"
                and analysis["confidence"] >= 0.3
            ):
                candidates.append(analysis)

        # Sort by volume descending
        candidates.sort(key=lambda x: x["final_volume"], reverse=True)
        return candidates

    def publish_to_event_bus(self, min_volume: int = 100000) -> int:
        """Publish qualifying auction candidates to events:signal stream.

        Called at ~9:26 CST after the auction window closes. Candidates
        with rising price + sufficient volume are published as events
        for the daemon's event loop to pick up.

        Args:
            min_volume: Minimum auction volume to qualify.

        Returns:
            Number of events published.
        """
        candidates = self.get_auction_candidates(min_volume=min_volume)
        if not candidates:
            return 0

        published = 0
        for c in candidates:
            try:
                from src.event_bus.bus import EventBus

                bus = EventBus()
                bus.publish(
                    stream="events:signal",
                    data={
                        "type": "call_auction",
                        "symbol": c["symbol"],
                        "auction_price": c["final_price"],
                        "auction_volume": c["final_volume"],
                        "volume_acceleration": c["volume_acceleration"],
                        "weak_to_strong": c.get("weak_to_strong", False),
                        "confidence": c["confidence"],
                        "source": "call_auction",
                    },
                )
                published += 1
            except Exception:
                logger.debug("Failed to publish auction event for %s", c["symbol"])

        if published:
            logger.info(
                "Published %d call-auction candidates to events:signal", published
            )
        return published

    # ------------------------------------------------------------------
    # Private: snapshot storage
    # ------------------------------------------------------------------

    def _snapshot_key(self, symbol: str) -> str:
        """Redis key for auction snapshots."""
        today = datetime.now().strftime("%Y%m%d")
        return f"auction:{today}:{symbol}"

    def _store_snapshot(self, symbol: str, snapshot: dict, score: float) -> None:
        """Store a snapshot in Redis sorted set or in-memory fallback."""
        if self._redis is not None:
            try:
                key = self._snapshot_key(symbol)
                self._redis.zadd(key, {json.dumps(snapshot): score})
                # Expire at end of day
                self._redis.expire(key, 43200)  # 12 hours
                return
            except Exception as exc:
                logger.debug("Redis store failed, using memory: %s", exc)

        # In-memory fallback
        if symbol not in self._mem_snapshots:
            self._mem_snapshots[symbol] = []
        self._mem_snapshots[symbol].append(snapshot)

    def _load_snapshots(self, symbol: str) -> list[dict]:
        """Load all snapshots for a symbol from Redis or memory."""
        if self._redis is not None:
            try:
                key = self._snapshot_key(symbol)
                raw_items = self._redis.zrange(key, 0, -1)
                if raw_items:
                    return [json.loads(item) for item in raw_items]
            except Exception as exc:
                logger.debug("Redis load failed, using memory: %s", exc)

        return list(self._mem_snapshots.get(symbol, []))

    def _get_tracked_symbols(self) -> list[str]:
        """Get all symbols with stored auction data."""
        if self._redis is not None:
            try:
                today = datetime.now().strftime("%Y%m%d")
                pattern = f"auction:{today}:*"
                keys = self._redis.keys(pattern)
                # Extract symbol from key "auction:YYYYMMDD:SYMBOL"
                return [
                    k.split(":")[-1]
                    if isinstance(k, str)
                    else k.decode().split(":")[-1]
                    for k in keys
                ]
            except Exception as exc:
                logger.debug("Redis keys failed, using memory: %s", exc)

        return list(self._mem_snapshots.keys())
