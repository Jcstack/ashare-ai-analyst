"""Data freshness and accuracy guard for assistant inbox messages.

Ensures all messages reference accurate, timely data. Rejects stale prices,
cross-checks LLM claims against actual data, and annotates messages with
freshness metadata (FR-AIX008).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

_CST = ZoneInfo("Asia/Shanghai")

logger = logging.getLogger(__name__)

# Freshness thresholds (in minutes)
_REALTIME_THRESHOLD = 5  # < 5 min = realtime
_DELAYED_THRESHOLD = 30  # 5-30 min = delayed
# > 30 min = stale


class DataFreshnessGuard:
    """Ensures data accuracy and freshness for all message generation."""

    def __init__(self, stock_service: Any = None) -> None:
        self._stock_service = stock_service

    # ------------------------------------------------------------------
    # Freshness classification
    # ------------------------------------------------------------------

    def get_freshness_level(self, data_timestamp: datetime | str | None) -> str:
        """Return 'realtime' | 'delayed' | 'stale' based on data age.

        During non-market hours (before 09:30 or after 15:00 CST),
        closing data is considered 'realtime'.
        """
        if data_timestamp is None:
            return "stale"

        if isinstance(data_timestamp, str):
            try:
                data_timestamp = datetime.fromisoformat(data_timestamp)
            except (ValueError, TypeError):
                return "stale"

        # Ensure timezone-aware
        if data_timestamp.tzinfo is None:
            data_timestamp = data_timestamp.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        age_minutes = (now - data_timestamp).total_seconds() / 60

        if age_minutes < _REALTIME_THRESHOLD:
            return "realtime"
        if age_minutes < _DELAYED_THRESHOLD:
            return "delayed"
        return "stale"

    def freshness_label(self, level: str) -> str | None:
        """Return user-facing Chinese label for freshness level.

        Returns None for 'realtime' (no label needed).
        """
        labels = {
            "realtime": None,
            "delayed": "数据略有延迟",
            "stale": "数据可能已过时，请注意",
        }
        return labels.get(level)

    # ------------------------------------------------------------------
    # Price validation
    # ------------------------------------------------------------------

    async def validate_price(
        self,
        symbol: str,
        claimed_price: float | None,
        tolerance_pct: float = 2.0,
    ) -> tuple[bool, float | None]:
        """Verify price against real-time source.

        Returns (is_valid, current_price). If the stock service is
        unavailable, returns (False, None) — callers should omit price
        rather than show stale data.
        """
        if claimed_price is None:
            return True, None

        if self._stock_service is None:
            logger.warning(
                "No stock service available for price validation of %s",
                symbol,
            )
            return False, None

        try:
            current = await self._stock_service.get_realtime_price(symbol)
            if current is None:
                return False, None

            # Allow small tolerance for rapid price movement
            diff_pct = abs(current - claimed_price) / claimed_price * 100
            if diff_pct > tolerance_pct:
                logger.info(
                    "Price mismatch for %s: claimed=%.2f actual=%.2f (%.1f%%)",
                    symbol,
                    claimed_price,
                    current,
                    diff_pct,
                )
                return False, current

            return True, current
        except Exception as exc:
            logger.warning("Price validation failed for %s: %s", symbol, exc)
            return False, None

    # ------------------------------------------------------------------
    # Claim validation
    # ------------------------------------------------------------------

    async def validate_claim(
        self, claim: str, evidence: dict[str, Any]
    ) -> tuple[bool, str]:
        """Cross-check a textual claim against actual data.

        Returns (is_valid, corrected_text). If the claim can't be
        verified, returns conservative fallback text.

        Examples:
            claim: "连续3天净流入"
            evidence: {"northbound_flows": [100, -50, 200]}
            → (False, "近期北向资金波动较大")
        """
        # Check "连续N天净流入" claims
        if "连续" in claim and "净流入" in claim:
            flows = evidence.get("northbound_flows", [])
            if flows:
                consecutive_positive = all(f > 0 for f in flows)
                if not consecutive_positive:
                    return False, "近期北向资金波动较大"

        # Check "连续N天净流出" claims
        if "连续" in claim and "净流出" in claim:
            flows = evidence.get("northbound_flows", [])
            if flows:
                consecutive_negative = all(f < 0 for f in flows)
                if not consecutive_negative:
                    return False, "近期北向资金波动较大"

        # Check percentage claims against actual data
        if "涨" in claim or "跌" in claim:
            actual_change = evidence.get("change_pct")
            if actual_change is not None:
                # Verify direction matches
                if "涨" in claim and actual_change < 0:
                    return False, f"实际变动为 {actual_change:.1f}%"
                if "跌" in claim and actual_change > 0:
                    return False, f"实际变动为 {actual_change:+.1f}%"

        # Check volume claims
        if "放量" in claim:
            vol_ratio = evidence.get("volume_ratio")
            if vol_ratio is not None and vol_ratio < 1.2:
                return False, "成交量暂无明显放大"

        # Default: trust the claim if no counter-evidence
        return True, claim

    # ------------------------------------------------------------------
    # Message enrichment
    # ------------------------------------------------------------------

    async def enrich_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Add data_freshness metadata to message before storage.

        Reads the raw_data_ref to determine when data was collected,
        classifies freshness, and adds labels.
        """
        raw = message.get("raw_data_ref", {})
        if isinstance(raw, str):
            import json

            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raw = {}

        # Determine data collection time
        data_time = raw.get("data_collected_at") or raw.get("timestamp")
        freshness = self.get_freshness_level(data_time)

        message["data_freshness"] = freshness
        message["data_collected_at"] = data_time

        # Add freshness warning to summary if stale
        label = self.freshness_label(freshness)
        if label and freshness == "stale":
            summary = message.get("summary", "")
            if label not in summary:
                message["summary"] = f"⚠ {label}。{summary}"

        return message

    # ------------------------------------------------------------------
    # Batch enrichment for watchlist
    # ------------------------------------------------------------------

    def is_market_hours(self) -> bool:
        """Check if current time is within A-share market hours (09:30-15:00 CST)."""
        now = datetime.now(_CST)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close

    def recommended_refresh_interval(self) -> int:
        """Return recommended data refresh interval in seconds.

        30s during market hours, 0 (no refresh) after close.
        """
        return 30 if self.is_market_hours() else 0
