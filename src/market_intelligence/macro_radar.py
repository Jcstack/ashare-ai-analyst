"""Macro Radar — generates macro-level MarketSignal from global markets and InfoStore.

Two scanning dimensions:
1. Global market data scan: monitors commodity/index/currency threshold breaches
2. Macro intel scan: keyword-based (not stock-code) matching of geopolitical/policy news

Output: MarketSignal(type=S8_MACRO_DRIVEN) published to SignalBus.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from src.utils.config import load_config
from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    RiskLevel,
    SignalType,
)

logger = logging.getLogger(__name__)


class MacroRadarService:
    """Macro radar — scans global markets and intel for macro-level signals."""

    def __init__(
        self,
        global_fetcher: Any,
        info_store: Any,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._global_fetcher = global_fetcher
        self._info_store = info_store
        self._config = config or self._load_config()
        self._keyword_patterns = self._compile_keywords()
        self._cooldown_cache: dict[str, float] = {}
        self._cooldown_minutes = (
            self._config.get("trigger_rules", {}).get("cooldown_minutes", 60)
        )
        logger.info("MacroRadarService initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("macro_radar")
        except FileNotFoundError:
            logger.warning("config/macro_radar.yaml not found; using defaults")
            return {}

    def _compile_keywords(self) -> dict[str, re.Pattern[str]]:
        """Compile macro_keywords into regex patterns per category."""
        patterns: dict[str, re.Pattern[str]] = {}
        keywords_cfg = self._config.get("macro_keywords", {})
        for category, words in keywords_cfg.items():
            if words:
                escaped = [re.escape(w) for w in words]
                patterns[category] = re.compile(
                    "|".join(escaped), re.IGNORECASE
                )
        return patterns

    def _is_cooled_down(self, key: str) -> bool:
        """Check if a signal category is in cooldown."""
        last = self._cooldown_cache.get(key)
        if last is None:
            return True
        return (time.monotonic() - last) >= (self._cooldown_minutes * 60)

    def _set_cooldown(self, key: str) -> None:
        self._cooldown_cache[key] = time.monotonic()

    # ------------------------------------------------------------------
    # Global market scan
    # ------------------------------------------------------------------

    def scan_global_markets(
        self, phase: MarketPhase = MarketPhase.CLOSED
    ) -> list[MarketSignal]:
        """Scan commodity/index threshold breaches and generate sector-level signals."""
        signals: list[MarketSignal] = []

        try:
            snapshot = self._global_fetcher.fetch_global_snapshot()
        except Exception:
            logger.warning("Failed to fetch global snapshot", exc_info=True)
            return signals

        # Build a lookup: yf_symbol -> market data
        all_data: dict[str, dict[str, Any]] = {}
        for category in ("indices", "commodities", "currencies"):
            for item in snapshot.get(category, []):
                sym = item.get("symbol", "")
                if sym:
                    all_data[sym] = item

        # --- Commodity threshold scan ---
        commodity_map = self._config.get("commodity_sector_map", {})
        for commodity_key, cfg in commodity_map.items():
            yf_sym = cfg.get("yf_symbol", "")
            data = all_data.get(yf_sym)
            if not data or data.get("pct_change") is None:
                continue

            pct = abs(data["pct_change"])
            threshold = cfg.get("threshold_pct", 3.0)
            if pct < threshold:
                continue

            cooldown_key = f"commodity:{commodity_key}"
            if not self._is_cooled_down(cooldown_key):
                continue

            direction = "上涨" if data["pct_change"] > 0 else "下跌"
            display = cfg.get("display", commodity_key)
            sectors = cfg.get("sectors", [])
            stocks = cfg.get("representative_stocks", [])
            inverse = cfg.get("inverse_sectors", [])

            # Build impact description
            if data["pct_change"] > 0 and inverse:
                impact_note = f"利好{','.join(sectors)}; 利空{','.join(inverse)}"
            else:
                impact_note = f"影响板块: {','.join(sectors)}"

            summary_short = f"{display}{direction}{data['pct_change']:+.1f}%"[:50]

            signal = MarketSignal(
                signal_id=str(uuid.uuid4()),
                signal_type=SignalType.S8_MACRO_DRIVEN,
                timestamp=datetime.now(UTC),
                assets=stocks,
                phase=phase,
                confidence_score=min(80.0, 50.0 + pct * 5),
                risk_level=(
                    RiskLevel.ELEVATED if pct >= threshold * 1.5
                    else RiskLevel.MODERATE
                ),
                sources=[],
                producer="macro_radar",
                summary_short=summary_short,
                summary_detailed=(
                    f"{display}{direction}{data['pct_change']:+.1f}% "
                    f"(阈值{threshold}%). {impact_note}"
                ),
            )
            signals.append(signal)
            self._set_cooldown(cooldown_key)

        # --- Index sentiment scan ---
        index_map = self._config.get("index_sentiment_map", {})
        for idx_key, cfg in index_map.items():
            yf_sym = cfg.get("yf_symbol", "")
            data = all_data.get(yf_sym)
            if not data:
                continue

            # VIX special handling
            if idx_key == "vix":
                extreme = cfg.get("extreme_threshold", 25.0)
                price = data.get("price")
                if price is not None and price >= extreme:
                    cooldown_key = "index:vix_extreme"
                    if self._is_cooled_down(cooldown_key):
                        signal = MarketSignal(
                            signal_id=str(uuid.uuid4()),
                            signal_type=SignalType.S8_MACRO_DRIVEN,
                            timestamp=datetime.now(UTC),
                            assets=[],
                            phase=phase,
                            confidence_score=min(90.0, 60.0 + (price - 20) * 2),
                            risk_level=RiskLevel.EXTREME,
                            sources=[],
                            producer="macro_radar",
                            summary_short=f"VIX恐慌指数={price:.1f}"[:50],
                            summary_detailed=(
                                f"VIX={price:.1f} 超过极端阈值{extreme}，"
                                f"全球市场恐慌情绪升温，A股或承压"
                            ),
                        )
                        signals.append(signal)
                        self._set_cooldown(cooldown_key)
                continue

            pct = data.get("pct_change")
            if pct is None:
                continue
            threshold = cfg.get("threshold_pct", 2.0)
            if abs(pct) < threshold:
                continue

            cooldown_key = f"index:{idx_key}"
            if not self._is_cooled_down(cooldown_key):
                continue

            display = cfg.get("display", idx_key)
            direction = "上涨" if pct > 0 else "下跌"
            impact = cfg.get("impact", "")
            impact_sectors = cfg.get("impact_sectors", [])

            summary_short = f"{display}{direction}{pct:+.1f}%"[:50]
            detail_parts = [f"{display}{direction}{pct:+.1f}% (阈值{threshold}%)"]
            if impact:
                detail_parts.append(f"影响: {impact}")
            if impact_sectors:
                detail_parts.append(f"相关板块: {','.join(impact_sectors)}")

            signal = MarketSignal(
                signal_id=str(uuid.uuid4()),
                signal_type=SignalType.S8_MACRO_DRIVEN,
                timestamp=datetime.now(UTC),
                assets=[],
                phase=phase,
                confidence_score=min(75.0, 50.0 + abs(pct) * 3),
                risk_level=(
                    RiskLevel.ELEVATED if abs(pct) >= threshold * 1.5
                    else RiskLevel.MODERATE
                ),
                sources=[],
                producer="macro_radar",
                summary_short=summary_short,
                summary_detailed=". ".join(detail_parts),
            )
            signals.append(signal)
            self._set_cooldown(cooldown_key)

        return signals

    # ------------------------------------------------------------------
    # Macro intel scan
    # ------------------------------------------------------------------

    def scan_macro_intel(
        self, phase: MarketPhase = MarketPhase.CLOSED
    ) -> list[MarketSignal]:
        """Scan InfoStore for macro events using keyword matching (not stock codes)."""
        signals: list[MarketSignal] = []
        if not self._keyword_patterns:
            return signals

        trigger_rules = self._config.get("trigger_rules", {})
        min_matches = trigger_rules.get("min_keyword_matches", 1)

        # Query recent macro/global/policy items from InfoStore
        try:
            items = self._info_store.get_feed(
                category=None,
                days=1,
                limit=200,
                sort_by="time",
            )
        except Exception:
            logger.warning("Failed to query InfoStore for macro intel", exc_info=True)
            return signals

        # Filter to macro-relevant categories
        macro_categories = {"macro", "global", "policy"}
        macro_items = [
            it for it in items
            if it.get("category", "") in macro_categories
        ]

        # Match keywords per category
        matched_events: dict[str, list[dict[str, Any]]] = {}
        for item in macro_items:
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            for category, pattern in self._keyword_patterns.items():
                matches = pattern.findall(text)
                if len(matches) >= min_matches:
                    matched_events.setdefault(category, []).append(item)

        # Generate signals per macro category
        category_labels = {
            "geopolitical": "地缘政治",
            "monetary_policy": "货币政策",
            "fiscal_policy": "财政政策",
            "commodity_shock": "大宗商品异动",
            "systemic_risk": "系统性风险",
        }

        for category, matched_items in matched_events.items():
            cooldown_key = f"macro_intel:{category}"
            if not self._is_cooled_down(cooldown_key):
                continue

            label = category_labels.get(category, category)
            # Use the most recent item's title as summary
            top_item = matched_items[0]
            title = top_item.get("title", "")[:40]

            risk_level = (
                RiskLevel.EXTREME if category == "systemic_risk"
                else RiskLevel.ELEVATED if category == "geopolitical"
                else RiskLevel.MODERATE
            )
            confidence = min(
                80.0, 40.0 + len(matched_items) * 10
            )

            summary_short = f"[{label}] {title}"[:50]
            detail_titles = [
                it.get("title", "")[:60] for it in matched_items[:5]
            ]

            signal = MarketSignal(
                signal_id=str(uuid.uuid4()),
                signal_type=SignalType.S8_MACRO_DRIVEN,
                timestamp=datetime.now(UTC),
                assets=[],
                phase=phase,
                confidence_score=confidence,
                risk_level=risk_level,
                sources=[],
                producer="macro_radar",
                summary_short=summary_short,
                summary_detailed=(
                    f"{label}事件 ({len(matched_items)}条相关情报): "
                    + "; ".join(detail_titles)
                ),
            )
            signals.append(signal)
            self._set_cooldown(cooldown_key)

        return signals

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scan_all(
        self, phase: MarketPhase = MarketPhase.CLOSED
    ) -> dict[str, int]:
        """Run all macro scans and return signal counts per category."""
        results: dict[str, int] = {"global_market": 0, "macro_intel": 0}

        try:
            market_signals = self.scan_global_markets(phase)
            results["global_market"] = len(market_signals)
        except Exception:
            logger.exception("Global market scan failed")
            market_signals = []

        try:
            intel_signals = self.scan_macro_intel(phase)
            results["macro_intel"] = len(intel_signals)
        except Exception:
            logger.exception("Macro intel scan failed")
            intel_signals = []

        all_signals = market_signals + intel_signals
        results["total"] = len(all_signals)

        logger.info(
            "MacroRadar scan complete: %d global + %d intel = %d total signals",
            results["global_market"],
            results["macro_intel"],
            results["total"],
        )
        return results

    def scan_all_with_signals(
        self, phase: MarketPhase = MarketPhase.CLOSED
    ) -> list[MarketSignal]:
        """Run all macro scans and return the actual signal objects."""
        signals: list[MarketSignal] = []

        try:
            signals.extend(self.scan_global_markets(phase))
        except Exception:
            logger.exception("Global market scan failed")

        try:
            signals.extend(self.scan_macro_intel(phase))
        except Exception:
            logger.exception("Macro intel scan failed")

        return signals
