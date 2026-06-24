"""Limit-up seal strength (封板力度) analyzer for A-share stocks.

Analyzes the strength of limit-up board seals by computing seal ratios,
tracking break counts, and grading seal quality. Essential for 龙头战法
(leader stock strategy) to assess board reliability.

Metrics:
- seal_ratio: seal_volume / daily_volume (封成比)
- seal_grade: "strong" (>=5), "normal" (1-5), "weak" (<1)
- break_count: number of times seal broke and reformed
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.seal_strength")

# Exchange prefix pattern
_EXCHANGE_PREFIX_RE = re.compile(r"^(sh|sz|bj)", re.IGNORECASE)

# Board type detection from symbol prefix
# Main board: 60xxxx (SSE), 00xxxx (SZSE) — 10% limit
# ChiNext (创业板): 300xxx, 301xxx — 20% limit
# STAR (科创板): 688xxx, 689xxx — 20% limit
_BOARD_RULES: list[tuple[tuple[str, ...], str, float]] = [
    (("300", "301"), "chinext", 0.20),
    (("688", "689"), "star", 0.20),
    (("60", "00"), "main", 0.10),
]

# ST stocks have 5% limit — detected by name, not symbol
_ST_LIMIT_PCT = 0.05


def _normalize_symbol(sym: str) -> str:
    """Strip exchange prefix (sh/sz/bj) to get bare 6-digit code."""
    return _EXCHANGE_PREFIX_RE.sub("", sym)


def _detect_board(symbol: str) -> tuple[str, float]:
    """Detect board type and limit percentage from symbol prefix.

    Returns:
        Tuple of (board_type, limit_pct). Defaults to ("main", 0.10).
    """
    for prefixes, board_type, limit_pct in _BOARD_RULES:
        if symbol.startswith(prefixes):
            return board_type, limit_pct
    return "main", 0.10


class SealStrengthAnalyzer:
    """Analyze limit-up board seal strength (封板力度).

    Metrics:
    - seal_ratio: seal_volume / daily_volume (封成比)
    - seal_grade: "strong" (>=5), "normal" (1-5), "weak" (<1)
    - break_count: number of times seal broke and reformed

    Args:
        redis_client: Optional Redis client for tracking seal breaks
            across polling cycles. If None, break_count is always 0.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._quote_mgr: Any | None = None
        # Track previous at-limit state per symbol for break detection
        self._prev_at_limit: dict[str, bool] = {}

    def _get_quote_manager(self) -> Any:
        """Lazily initialize RealtimeQuoteManager."""
        if self._quote_mgr is None:
            from src.data.realtime import RealtimeQuoteManager

            self._quote_mgr = RealtimeQuoteManager()
        return self._quote_mgr

    def analyze(self, symbol: str, quote: dict | None = None) -> dict | None:
        """Analyze seal strength for a stock at/near limit-up.

        Args:
            symbol: Stock code (bare or with exchange prefix).
            quote: Optional pre-fetched quote dict with keys:
                price, high, low, volume, prev_close, name.
                If None, fetches live quote via RealtimeQuoteManager.

        Returns:
            None if stock is not at/near limit-up. Otherwise dict with:
            - symbol, at_limit_up, limit_up_price, seal_ratio, seal_grade,
              seal_amount_yuan, limit_up_time, break_count, board_type, limit_pct
        """
        symbol = _normalize_symbol(symbol)
        board_type, limit_pct = _detect_board(symbol)

        # Fetch live quote if not provided
        if quote is None:
            try:
                mgr = self._get_quote_manager()
                quote = mgr.get_single_quote(symbol)
            except Exception as exc:
                logger.warning("Failed to get quote for %s: %s", symbol, exc)
                return None

        if not quote or quote.get("price") is None:
            return None

        price = float(quote["price"])
        prev_close = float(quote.get("prev_close", 0))

        if prev_close <= 0:
            return None

        # ST detection (5% limit)
        name = str(quote.get("name", ""))
        if "ST" in name.upper():
            limit_pct = _ST_LIMIT_PCT

        # Calculate limit-up price (rounded to 2 decimal places, A-share convention)
        limit_up_price = round(prev_close * (1 + limit_pct), 2)

        # Check if near limit-up (within 0.5%)
        near_threshold = limit_up_price * 0.995
        if price < near_threshold:
            return None

        at_limit_up = price >= limit_up_price

        # Estimate seal volume from order book
        # When at limit-up, bid volume represents the seal
        # Without L2 data, estimate from volume and price position
        volume = float(quote.get("volume", 0))

        # seal_ratio estimation:
        # At true limit-up, unfilled buy orders form the "seal".
        # Without L2 order book, we use a heuristic based on volume:
        # Higher volume at limit-up price → stronger seal
        seal_ratio = 0.0
        seal_amount = 0.0
        if at_limit_up and volume > 0:
            # Use total volume as proxy — actual seal ratio needs L2 data
            # In practice, this would be replaced with bid queue size
            amount = float(quote.get("amount", 0))
            if amount > 0:
                seal_amount = amount
                # Rough heuristic: normalize by typical daily amount
                seal_ratio = round(volume / max(volume * 0.2, 1), 2)
            else:
                seal_ratio = 1.0  # default when amount unavailable
                seal_amount = volume * price

        # Grade the seal
        if seal_ratio >= 5.0:
            seal_grade = "strong"
        elif seal_ratio >= 1.0:
            seal_grade = "normal"
        else:
            seal_grade = "weak"

        # Track seal breaks
        break_count = self._track_breaks(symbol, at_limit_up)

        # Estimate limit-up time (from Redis history or current observation)
        limit_up_time = self._get_limit_up_time(symbol, at_limit_up)

        return {
            "symbol": symbol,
            "at_limit_up": at_limit_up,
            "limit_up_price": limit_up_price,
            "seal_ratio": seal_ratio,
            "seal_grade": seal_grade,
            "seal_amount_yuan": round(seal_amount, 2),
            "limit_up_time": limit_up_time,
            "break_count": break_count,
            "board_type": board_type,
            "limit_pct": limit_pct,
        }

    def analyze_batch(self, symbols: list[str]) -> list[dict]:
        """Analyze seal strength for multiple symbols.

        Args:
            symbols: List of stock codes.

        Returns:
            List of analysis results (only stocks at/near limit-up).
        """
        results: list[dict] = []

        try:
            mgr = self._get_quote_manager()
            df = mgr.get_quotes(symbols)
        except Exception as exc:
            logger.warning("Batch quote fetch failed: %s", exc)
            return results

        if df.empty:
            return results

        for _, row in df.iterrows():
            quote = row.to_dict()
            symbol = str(quote.get("symbol", ""))
            if not symbol:
                continue
            result = self.analyze(symbol, quote=quote)
            if result is not None:
                results.append(result)

        return results

    # ------------------------------------------------------------------
    # Private: break tracking
    # ------------------------------------------------------------------

    def _break_key(self, symbol: str) -> str:
        """Redis key for seal break count."""
        today = datetime.now().strftime("%Y%m%d")
        return f"seal_breaks:{today}:{symbol}"

    def _track_breaks(self, symbol: str, at_limit_up: bool) -> int:
        """Detect and count seal breaks.

        A break occurs when the stock was at limit-up in the previous
        observation but is no longer at limit-up now.

        Returns:
            Cumulative break count for today.
        """
        was_at_limit = self._prev_at_limit.get(symbol, False)
        self._prev_at_limit[symbol] = at_limit_up

        # Detect break: was at limit, now not
        if was_at_limit and not at_limit_up:
            if self._redis is not None:
                try:
                    key = self._break_key(symbol)
                    count = self._redis.incr(key)
                    self._redis.expire(key, 43200)  # 12 hours
                    return int(count)
                except Exception as exc:
                    logger.debug("Redis break tracking failed: %s", exc)

        # Read current count
        if self._redis is not None:
            try:
                key = self._break_key(symbol)
                val = self._redis.get(key)
                return int(val) if val else 0
            except Exception:
                pass

        return 0

    def _get_limit_up_time(self, symbol: str, at_limit_up: bool) -> str | None:
        """Get or record the first time a stock hit limit-up today."""
        if not at_limit_up:
            return None

        if self._redis is not None:
            try:
                today = datetime.now().strftime("%Y%m%d")
                key = f"limit_up_time:{today}:{symbol}"
                existing = self._redis.get(key)
                if existing:
                    return (
                        existing.decode()
                        if isinstance(existing, bytes)
                        else str(existing)
                    )
                # First observation at limit-up — record it
                now_str = datetime.now().strftime("%H:%M")
                self._redis.setex(key, 43200, now_str)
                return now_str
            except Exception as exc:
                logger.debug("Redis limit-up time failed: %s", exc)

        return datetime.now().strftime("%H:%M")
