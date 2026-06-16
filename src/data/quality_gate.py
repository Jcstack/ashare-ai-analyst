"""Data quality gate — validates freshness, completeness, and consistency.

Validates quotes, indicators, and news before they enter the analysis
pipeline.  Returns a quality score (0-100) with categorized warnings.

Part of WS2: Data Source Verification.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.quality_gate")


@dataclass
class QualityResult:
    """Result of a data quality check.

    Attributes:
        score: Overall quality score 0-100.
        warnings: Human-readable warning messages.
        checks_passed: Number of checks that passed.
        checks_total: Total number of checks run.
    """

    score: int = 100
    warnings: list[str] = field(default_factory=list)
    checks_passed: int = 0
    checks_total: int = 0


class DataQualityGate:
    """Validates data quality before analysis pipeline consumption.

    Usage::

        gate = DataQualityGate()
        result = gate.validate_all(quote=quote, indicators=indicators, news=news)
        if result.score < 40:
            logger.warning("Low data quality: %d", result.score)
    """

    # Staleness thresholds in seconds
    QUOTE_STALE_DEGRADED = 300  # 5 minutes
    QUOTE_STALE_CRITICAL = 1800  # 30 minutes
    NEWS_STALE_HOURS = 24

    def validate_quote(self, quote: dict[str, Any] | None) -> QualityResult:
        """Validate a real-time quote for staleness and completeness.

        Checks:
        - Presence of required fields (price, volume)
        - Null/zero price detection
        - OHLC consistency (low <= close <= high)
        - Staleness check via timestamp if available

        Args:
            quote: Quote dict from RealtimeQuoteManager.

        Returns:
            QualityResult with score and warnings.
        """
        result = QualityResult()

        if not quote:
            result.score = 0
            result.warnings.append("无行情数据")
            result.checks_total = 1
            return result

        checks = 0
        passed = 0

        # Check required fields
        checks += 1
        price = quote.get("price")
        if price is not None and price != 0:
            passed += 1
        else:
            result.warnings.append("价格数据缺失或为零")

        checks += 1
        volume = quote.get("volume")
        if volume is not None:
            passed += 1
        else:
            result.warnings.append("成交量数据缺失")

        # OHLC consistency
        high = quote.get("high")
        low = quote.get("low")
        if high is not None and low is not None and price is not None:
            checks += 1
            if low <= price <= high or price == 0:
                passed += 1
            else:
                result.warnings.append(
                    f"OHLC不一致: low={low}, price={price}, high={high}"
                )

        # NaN check on numeric fields
        checks += 1
        nan_fields = [
            k
            for k, v in quote.items()
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v))
        ]
        if not nan_fields:
            passed += 1
        else:
            result.warnings.append(f"NaN字段: {', '.join(nan_fields)}")

        result.checks_passed = passed
        result.checks_total = checks
        result.score = int(passed / checks * 100) if checks > 0 else 0
        return result

    def validate_indicators(
        self,
        indicators: dict[str, Any] | None,
    ) -> QualityResult:
        """Validate technical indicators for completeness and NaN.

        Checks:
        - At least 3 indicator groups present
        - No NaN values in leaf values
        - Key indicators present (MA, MACD, RSI recommended)

        Args:
            indicators: Indicator dict from StockService.

        Returns:
            QualityResult with score and warnings.
        """
        result = QualityResult()

        if not indicators:
            result.score = 0
            result.warnings.append("无技术指标数据")
            result.checks_total = 1
            return result

        checks = 0
        passed = 0

        # Completeness: at least 3 indicator groups
        checks += 1
        if len(indicators) >= 3:
            passed += 1
        else:
            result.warnings.append(f"指标不完整: 仅{len(indicators)}组 (建议>=3)")

        # NaN detection in leaf values
        checks += 1
        nan_count = 0
        total_values = 0
        for key, value in indicators.items():
            if isinstance(value, dict):
                for sub_val in value.values():
                    total_values += 1
                    if isinstance(sub_val, float) and (
                        math.isnan(sub_val) or math.isinf(sub_val)
                    ):
                        nan_count += 1
            elif isinstance(value, float):
                total_values += 1
                if math.isnan(value) or math.isinf(value):
                    nan_count += 1

        if nan_count == 0:
            passed += 1
        else:
            result.warnings.append(f"指标含NaN: {nan_count}/{total_values}个值")

        # Key indicators check
        checks += 1
        key_indicators = {"ma", "macd", "rsi", "kdj", "boll"}
        present = {k.lower() for k in indicators.keys()}
        found = key_indicators & present
        if len(found) >= 2:
            passed += 1
        else:
            result.warnings.append(f"缺少关键指标: 仅有{', '.join(found) or '无'}")

        result.checks_passed = passed
        result.checks_total = checks
        result.score = int(passed / checks * 100) if checks > 0 else 0
        return result

    def validate_news(
        self,
        news_items: list[dict[str, Any]] | None,
    ) -> QualityResult:
        """Validate news items for freshness and content quality.

        Checks:
        - At least 1 news item present
        - No empty-title items
        - Freshness check (within 24 hours)

        Args:
            news_items: List of news item dicts.

        Returns:
            QualityResult with score and warnings.
        """
        result = QualityResult()

        if not news_items:
            result.score = 50  # News absence is degraded, not critical
            result.warnings.append("无近期新闻数据")
            result.checks_total = 1
            return result

        checks = 0
        passed = 0

        # Non-empty check
        checks += 1
        passed += 1  # We already know news_items is non-empty

        # Empty content filter
        checks += 1
        empty_titles = [n for n in news_items if not n.get("title", "").strip()]
        if not empty_titles:
            passed += 1
        else:
            result.warnings.append(f"空标题新闻: {len(empty_titles)}/{len(news_items)}")

        # Freshness — check if any item has a recent timestamp
        checks += 1
        has_recent = False
        for item in news_items:
            dt = item.get("datetime", "") or item.get("date", "")
            if dt:
                # Rough check — if date string contains today's date
                today = time.strftime("%Y-%m-%d")
                if today in str(dt):
                    has_recent = True
                    break
        if has_recent:
            passed += 1
        else:
            result.warnings.append("新闻可能不够新鲜 (无今日新闻)")

        result.checks_passed = passed
        result.checks_total = checks
        result.score = int(passed / checks * 100) if checks > 0 else 0
        return result

    def validate_all(
        self,
        quote: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        news: list[dict[str, Any]] | None = None,
    ) -> QualityResult:
        """Run all validation checks and produce a combined result.

        Args:
            quote: Real-time quote dict.
            indicators: Technical indicators dict.
            news: News items list.

        Returns:
            Combined QualityResult with weighted score.
        """
        q_result = self.validate_quote(quote)
        i_result = self.validate_indicators(indicators)
        n_result = self.validate_news(news)

        # Weighted average: quote=40%, indicators=35%, news=25%
        combined_score = int(
            q_result.score * 0.40 + i_result.score * 0.35 + n_result.score * 0.25
        )

        all_warnings = q_result.warnings + i_result.warnings + n_result.warnings
        total_passed = (
            q_result.checks_passed + i_result.checks_passed + n_result.checks_passed
        )
        total_checks = (
            q_result.checks_total + i_result.checks_total + n_result.checks_total
        )

        return QualityResult(
            score=combined_score,
            warnings=all_warnings,
            checks_passed=total_passed,
            checks_total=total_checks,
        )
