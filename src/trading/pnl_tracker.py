"""Real-time P&L tracking for trading decisions pushed to Discord.

Tracks every decision's price movement post-push, computes unrealized
P&L, and alerts when stop-loss or target-price levels are breached.

Redis-backed with 48h TTL per tracked decision.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.pnl_tracker")

_TTL_SECONDS = 48 * 3600  # 48 hours
_REDIS_PREFIX = "pnl:track:"


@dataclass
class TrackedDecision:
    """State for a single tracked trading decision.

    Attributes:
        decision_id: Unique identifier for the decision.
        symbol: 6-digit A-share stock code.
        action: Trading action (buy, sell, add, reduce).
        entry_price: Price at the time the decision was made.
        stop_loss: Stop-loss price level.
        target_price: Target price level.
        current_price: Most recent fetched price.
        pnl_pct: Unrealized P&L as a percentage.
        pnl_abs: Unrealized P&L in absolute price terms.
        high_water: Highest price seen since tracking started.
        low_water: Lowest price seen since tracking started.
        started_at: Unix timestamp when tracking began.
        updated_at: Unix timestamp of last price update.
        breached: Which level was breached ('stop_loss', 'target', or '').
    """

    decision_id: str
    symbol: str
    action: str
    entry_price: float
    stop_loss: float
    target_price: float
    current_price: float = 0.0
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0
    high_water: float = 0.0
    low_water: float = 0.0
    started_at: float = 0.0
    updated_at: float = 0.0
    breached: str = ""


@dataclass
class PnLAlert:
    """Alert generated when a tracked decision breaches a level.

    Attributes:
        decision_id: Which decision triggered the alert.
        symbol: Stock code.
        alert_type: 'stop_loss' or 'target'.
        entry_price: Original entry price.
        trigger_price: The stop-loss or target price that was breached.
        current_price: Current market price.
        pnl_pct: P&L at the time of breach.
    """

    decision_id: str
    symbol: str
    alert_type: str
    entry_price: float
    trigger_price: float
    current_price: float
    pnl_pct: float


class PnLTracker:
    """Redis-backed real-time P&L tracker for trading decisions.

    Fetches current prices via RealtimeQuoteManager, computes P&L,
    and detects stop-loss / target-price breaches.

    Args:
        redis_client: Redis client instance (decode_responses=True).
        quote_manager: Optional RealtimeQuoteManager; lazy-loaded if None.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        quote_manager: Any | None = None,
    ) -> None:
        self._redis = redis_client
        self._quote_manager = quote_manager

    def _get_redis(self) -> Any:
        """Lazy-load Redis client if not provided."""
        if self._redis is None:
            from src.web.dependencies import get_redis

            self._redis = get_redis()
        return self._redis

    def _get_quote_manager(self) -> Any:
        """Lazy-load RealtimeQuoteManager if not provided."""
        if self._quote_manager is None:
            from src.web.dependencies import get_realtime_quote_manager

            self._quote_manager = get_realtime_quote_manager()
        return self._quote_manager

    def start_tracking(
        self,
        decision_id: str,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        target_price: float,
    ) -> TrackedDecision:
        """Begin tracking a trading decision's P&L.

        Creates a Redis key ``pnl:track:{decision_id}`` with a JSON
        payload and 48h TTL.

        Args:
            decision_id: Unique decision identifier.
            symbol: 6-digit stock code.
            action: Trading action (buy/sell/add/reduce).
            entry_price: Entry price at decision time.
            stop_loss: Stop-loss price level.
            target_price: Target price level.

        Returns:
            The newly created TrackedDecision.
        """
        now = time.time()
        track = TrackedDecision(
            decision_id=decision_id,
            symbol=symbol,
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            current_price=entry_price,
            high_water=entry_price,
            low_water=entry_price,
            started_at=now,
            updated_at=now,
        )
        self._save_track(track)
        logger.info(
            "Started P&L tracking: %s %s @ %.2f (SL=%.2f, TP=%.2f)",
            decision_id,
            symbol,
            entry_price,
            stop_loss,
            target_price,
        )
        return track

    def update_prices(self) -> list[TrackedDecision]:
        """Fetch current prices for all tracked decisions and recompute P&L.

        Uses RealtimeQuoteManager.get_single_quote() for each symbol.

        Returns:
            List of all updated TrackedDecision objects.
        """
        tracks = self.get_active_tracks()
        if not tracks:
            return []

        qm = self._get_quote_manager()
        if qm is None:
            logger.warning("No quote manager available — skipping price update")
            return tracks

        now = time.time()
        updated: list[TrackedDecision] = []

        for track in tracks:
            try:
                quote = qm.get_single_quote(track.symbol)
                price = float(quote.get("price", 0))
                if price <= 0:
                    logger.debug("No valid price for %s — skipping", track.symbol)
                    updated.append(track)
                    continue

                track.current_price = price
                track.updated_at = now
                track.high_water = max(track.high_water, price)
                track.low_water = (
                    min(track.low_water, price) if track.low_water > 0 else price
                )

                # Compute P&L based on action direction
                if track.action in ("buy", "add"):
                    track.pnl_abs = price - track.entry_price
                else:
                    track.pnl_abs = track.entry_price - price

                if track.entry_price > 0:
                    track.pnl_pct = (track.pnl_abs / track.entry_price) * 100

                # Check breach
                if track.action in ("buy", "add"):
                    if price <= track.stop_loss and track.stop_loss > 0:
                        track.breached = "stop_loss"
                    elif price >= track.target_price and track.target_price > 0:
                        track.breached = "target"
                else:
                    # Short-side: stop_loss is above entry, target is below
                    if price >= track.stop_loss and track.stop_loss > 0:
                        track.breached = "stop_loss"
                    elif price <= track.target_price and track.target_price > 0:
                        track.breached = "target"

                self._save_track(track)
                updated.append(track)
            except Exception:
                logger.exception("Failed to update price for %s", track.symbol)
                updated.append(track)

        logger.info("Updated prices for %d tracked decisions", len(updated))
        return updated

    def check_alerts(self) -> list[PnLAlert]:
        """Return alerts for decisions that breached stop-loss or target.

        Scans all active tracks and returns a PnLAlert for each that has
        a non-empty ``breached`` field.

        Returns:
            List of PnLAlert objects for breached decisions.
        """
        tracks = self.get_active_tracks()
        alerts: list[PnLAlert] = []

        for track in tracks:
            if not track.breached:
                continue

            trigger_price = (
                track.stop_loss if track.breached == "stop_loss" else track.target_price
            )
            alerts.append(
                PnLAlert(
                    decision_id=track.decision_id,
                    symbol=track.symbol,
                    alert_type=track.breached,
                    entry_price=track.entry_price,
                    trigger_price=trigger_price,
                    current_price=track.current_price,
                    pnl_pct=track.pnl_pct,
                )
            )

        if alerts:
            logger.info("P&L alerts: %d breaches detected", len(alerts))
        return alerts

    def get_active_tracks(self) -> list[TrackedDecision]:
        """Return all actively tracked decisions from Redis.

        Returns:
            List of TrackedDecision objects.
        """
        r = self._get_redis()
        if r is None:
            logger.warning("Redis unavailable — no active tracks")
            return []

        try:
            keys = r.keys(f"{_REDIS_PREFIX}*")
        except Exception:
            logger.exception("Failed to scan Redis for P&L tracks")
            return []

        tracks: list[TrackedDecision] = []
        for key in keys:
            try:
                raw = r.get(key)
                if raw is None:
                    continue
                data = json.loads(raw)
                tracks.append(TrackedDecision(**data))
            except Exception:
                logger.warning("Failed to parse track from key %s", key)

        return tracks

    def remove_track(self, decision_id: str) -> bool:
        """Stop tracking a decision.

        Args:
            decision_id: The decision to stop tracking.

        Returns:
            True if the key was deleted, False otherwise.
        """
        r = self._get_redis()
        if r is None:
            return False

        key = f"{_REDIS_PREFIX}{decision_id}"
        try:
            deleted = r.delete(key)
            if deleted:
                logger.info("Removed P&L track: %s", decision_id)
            return bool(deleted)
        except Exception:
            logger.exception("Failed to remove track %s", decision_id)
            return False

    def check_trend_status(self, symbol: str) -> dict[str, Any]:
        """Analyze trend health using volume-price relationship.

        Returns:
            Dict with keys: status, volume_ratio, signal, recommendation
            status: "trending_up" | "pullback_normal" | "stalling" | "trend_broken"
        """
        try:
            from src.data.fetcher import StockDataFetcher
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager()
            quote = mgr.get_single_quote(symbol)
            if not quote:
                return {"status": "unknown", "signal": "no_data"}

            price = float(quote.get("price", 0))
            pct = float(quote.get("pct_change", 0) or 0)
            vol_ratio = float(quote.get("volume_ratio", 1) or 1)

            # Get recent history for MA check
            fetcher = StockDataFetcher()
            df = fetcher.fetch_daily_ohlcv(symbol)
            if df is None or len(df) < 10:
                return {"status": "unknown", "signal": "insufficient_data"}

            ma5 = df["close"].tail(5).mean()
            ma10 = df["close"].tail(10).mean()

            # Volume-price analysis
            if vol_ratio > 2.0 and pct > 2:
                status = "trending_up"
                signal = "volume_surge_bullish"
                recommendation = "持有，趋势加速中"
            elif vol_ratio > 1.5 and abs(pct) < 1:
                status = "stalling"
                signal = "volume_stall"
                recommendation = "⚠️ 放量滞涨，考虑减仓"
            elif vol_ratio < 0.7 and pct < -1:
                status = "pullback_normal"
                signal = "shrink_pullback"
                recommendation = "缩量回调，正常持有"
            elif price < ma5 and ma5 < ma10:
                status = "trend_broken"
                signal = "ma_death_cross"
                recommendation = "🚨 趋势破坏，建议卖出"
            else:
                status = "neutral"
                signal = "no_clear_signal"
                recommendation = "继续观察"

            return {
                "status": status,
                "signal": signal,
                "recommendation": recommendation,
                "volume_ratio": vol_ratio,
                "pct_change": pct,
                "price": price,
            }
        except Exception as exc:
            return {"status": "error", "signal": str(exc)}

    # ── Internal helpers ─────────────────────────────────────

    def _save_track(self, track: TrackedDecision) -> None:
        """Persist a TrackedDecision to Redis with TTL."""
        r = self._get_redis()
        if r is None:
            logger.warning(
                "Redis unavailable — cannot save track %s", track.decision_id
            )
            return

        key = f"{_REDIS_PREFIX}{track.decision_id}"
        try:
            r.setex(key, _TTL_SECONDS, json.dumps(asdict(track)))
        except Exception:
            logger.exception("Failed to save track %s", track.decision_id)
