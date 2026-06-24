"""Multi-factor stock screening engine.

Applies style-specific filters and weighted scoring to produce ranked
StockCandidate lists from A-share market snapshots.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import time
from datetime import datetime, timedelta
from math import ceil, exp
from typing import Any

from src.recommendation.models import StockCandidate

logger = logging.getLogger(__name__)

_EXCHANGE_PREFIX_RE = re.compile(r"^(?:sh|sz|bj)(\d{6})$", re.IGNORECASE)


def _strip_exchange_prefix(symbol: str) -> str:
    """Strip sh/sz/bj exchange prefix, returning bare 6-digit code."""
    m = _EXCHANGE_PREFIX_RE.match(symbol)
    return m.group(1) if m else symbol


class StockScreener:
    """Screen A-share stocks using configurable style-based filters and scoring."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        redis_client: Any = None,
        fusion_engine: Any | None = None,
    ) -> None:
        self._styles = config.get("styles", {})
        self._screening = config.get("screening", {})
        self._max_candidates = self._screening.get("max_candidates_per_style", 20)
        self._min_score = self._screening.get("min_score", 0.6)
        self._excluded_prefixes = self._build_excluded_prefixes(
            self._screening.get("exclude_exchanges", [])
        )
        # Trading profile for T+1 / intraday drift risk (I-090)
        self._trading_profile = config.get("trading_profile", {})
        # Overnight risk calculator (I-090 Phase 2) — lazy init
        self._overnight_risk: Any | None = None
        # Market snapshot cache: (timestamp, data)
        self._snapshot_cache: tuple[float, list[dict]] | None = None
        self._cache_ttl = 300  # 5 minutes
        # Listing dates cache: (timestamp, dict)
        self._listing_cache: tuple[float, dict[str, str]] | None = None
        self._listing_cache_ttl = 86400  # 24 hours
        # Sector stats cache: shares TTL with snapshot
        self._sector_stats_cache: tuple[float, dict[str, dict]] | None = None
        # Redis client for persistent snapshot cache (optional)
        self._redis = redis_client
        # Qlib signal fusion engine (optional, Phase 4)
        self._fusion_engine = fusion_engine
        self._qlib_weight = self._screening.get("qlib_weight", 0.15)

    # Exchange name → symbol prefix mapping
    _EXCHANGE_PREFIXES: dict[str, tuple[str, ...]] = {
        "bse": ("83", "87", "43", "92", "8"),  # 北交所 (含920xxx新代码段)
        "star": ("688", "689"),  # 科创板
        "chinext": ("300", "301"),  # 创业板
    }

    @staticmethod
    def _build_excluded_prefixes(exchanges: list[str]) -> tuple[str, ...]:
        """Convert exchange names to a tuple of symbol prefixes for filtering."""
        prefixes: list[str] = []
        for ex in exchanges:
            ex_lower = ex.lower().strip()
            mapped = StockScreener._EXCHANGE_PREFIXES.get(ex_lower)
            if mapped:
                prefixes.extend(mapped)
            else:
                logger.warning("Unknown exchange in exclude_exchanges: %s", ex)
        return tuple(prefixes)

    def screen(
        self,
        style: str,
        market_data: list[dict] | None = None,
        *,
        blacklist: set[str] | None = None,
    ) -> list[StockCandidate]:
        """Screen stocks for a given investment style.

        Args:
            style: Investment style key (e.g. "value", "momentum").
            market_data: Optional pre-fetched market data. If None, fetches live.
            blacklist: Optional set of symbol codes to exclude.

        Returns:
            Ranked list of StockCandidate, capped at max_candidates_per_style.
        """
        style_config = self._styles.get(style)
        if not style_config:
            logger.warning("Unknown style: %s", style)
            return []

        if market_data is None:
            market_data = self._fetch_market_snapshot()

        if not market_data:
            logger.warning("No market data available for screening")
            return []

        # Step 0: Apply universal exclusion rules (ST, halted, new IPO, blacklist)
        pre_exclusion = len(market_data)
        market_data = self._apply_exclusions(market_data, blacklist=blacklist or set())
        logger.info(
            "Style '%s': %d/%d stocks survived exclusions",
            style,
            len(market_data),
            pre_exclusion,
        )

        # Step 1: Apply hard filters
        filtered = self._apply_filters(style_config, market_data)
        logger.info(
            "Style '%s': %d/%d stocks passed filters",
            style,
            len(filtered),
            len(market_data),
        )

        if not filtered:
            return []

        # Step 2: Score and rank
        candidates = self._score_candidates(style, style_config, filtered)

        # Step 3: Filter by min_score and cap
        pre_filter_count = len(candidates)
        if candidates:
            top_score = max(c.score for c in candidates)
            avg_score = sum(c.score for c in candidates) / len(candidates)
            logger.info(
                "Style '%s': score distribution — top=%.3f, avg=%.3f, min_threshold=%.2f",
                style,
                top_score,
                avg_score,
                self._min_score,
            )
        candidates = [c for c in candidates if c.score >= self._min_score]
        if not candidates and pre_filter_count > 0:
            logger.warning(
                "Style '%s': all %d candidates eliminated by min_score=%.2f, "
                "consider lowering threshold",
                style,
                pre_filter_count,
                self._min_score,
            )
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Step 3.5: Apply intraday drift penalty (I-090 — T+1 risk)
        candidates = self._apply_intraday_drift_penalty(candidates)

        # Step 4: Apply per-sector cap to prevent single-sector dominance
        max_per_sector = self._screening.get("max_per_sector", 3)
        candidates = self._apply_sector_cap(candidates, max_per_sector)

        candidates = candidates[: self._max_candidates]

        logger.info(
            "Style '%s': %d candidates after scoring (min_score=%.2f)",
            style,
            len(candidates),
            self._min_score,
        )
        return candidates

    def _apply_exclusions(
        self,
        stocks: list[dict],
        *,
        blacklist: set[str] | None = None,
    ) -> list[dict]:
        """Apply universal exclusion rules per FR-REC004.

        Excludes: ST/*ST stocks, halted stocks (price=0 or no trading),
        blacklisted symbols, recent IPOs (< 60 days), Beijing Stock Exchange.
        """
        blacklist = blacklist or set()
        listing_dates = self._fetch_listing_dates()

        result = []
        for stock in stocks:
            name = stock.get("name", stock.get("名称", ""))
            symbol = stock.get("symbol", stock.get("代码", ""))
            price = float(stock.get("price", stock.get("最新价", 0)) or 0)
            raw_vol = stock.get("volume", stock.get("成交量", 0))
            volume = float(raw_vol) if raw_vol is not None else None

            # Strip exchange prefix (sh/sz/bj) — Sina/cached data may include it
            bare = _strip_exchange_prefix(symbol)

            # Exclude user-blacklisted symbols
            if symbol in blacklist or bare in blacklist:
                continue

            # Exclude ST / *ST stocks
            if "ST" in name.upper():
                continue

            # Exclude halted stocks (zero price or zero volume)
            # When volume is None (cached/Sina data), skip volume check
            if price <= 0:
                continue
            if volume is not None and volume <= 0:
                continue

            # Exclude stocks from configured exchanges (e.g. bse, star, chinext)
            if self._excluded_prefixes and bare.startswith(self._excluded_prefixes):
                continue

            # Exclude stocks with name markers indicating issues
            if any(tag in name for tag in ("退", "退市", "B股")):
                continue

            # Exclude recent IPOs (listed < 60 days)
            if self._is_recent_ipo(symbol, listing_dates):
                continue

            result.append(stock)
        return result

    @staticmethod
    def _is_recent_ipo(
        symbol: str, listing_dates: dict[str, str], days: int = 60
    ) -> bool:
        """Check if a stock was listed less than N days ago."""
        date_str = listing_dates.get(symbol)
        if not date_str:
            return False
        try:
            listing_date = datetime.strptime(date_str, "%Y%m%d")
            return (datetime.now() - listing_date) < timedelta(days=days)
        except (ValueError, TypeError):
            return False

    def _fetch_listing_dates(self) -> dict[str, str]:
        """Fetch listing dates for all A-share stocks with 24h cache."""
        now = time.time()
        if self._listing_cache is not None:
            ts, data = self._listing_cache
            if now - ts < self._listing_cache_ttl:
                return data

        try:
            import akshare as ak

            df = ak.stock_info_a_code_name()
            dates: dict[str, str] = {}
            for _, row in df.iterrows():
                code = str(row.get("code", ""))
                date_val = str(row.get("ipoDate", row.get("上市日期", "")))
                if code and date_val:
                    # Normalize date format — strip hyphens if present
                    dates[code] = date_val.replace("-", "")
            self._listing_cache = (now, dates)
            logger.info("Fetched listing dates: %d stocks", len(dates))
            return dates
        except Exception as exc:
            logger.warning("Failed to fetch listing dates: %s", exc)
            if self._listing_cache is not None:
                return self._listing_cache[1]
            return {}

    @staticmethod
    def _apply_sector_cap(
        candidates: list[StockCandidate], max_per_sector: int
    ) -> list[StockCandidate]:
        """Cap the number of candidates per sector to ensure diversity.

        Candidates must be pre-sorted by score descending. Within each sector,
        only the top `max_per_sector` are kept. Excess candidates from
        over-represented sectors are dropped entirely — this is intentional
        to prevent single-sector dominance (e.g. all-bank recommendations).
        """
        if max_per_sector <= 0:
            return candidates

        sector_counts: dict[str, int] = {}
        result: list[StockCandidate] = []

        for c in candidates:
            sector = c.sector or "unknown"
            count = sector_counts.get(sector, 0)
            if count < max_per_sector:
                result.append(c)
                sector_counts[sector] = count + 1

        return result

    def _apply_intraday_drift_penalty(
        self, candidates: list[StockCandidate]
    ) -> list[StockCandidate]:
        """Penalize candidates with excessive intraday gains (I-090).

        For T+1 markets, chasing stocks that already surged today creates
        overnight risk — the buyer cannot sell until tomorrow. This method:
        1. Hard-excludes stocks at limit-up (configurable via filter_limit_up).
        2. Applies a score penalty for stocks above max_intraday_chasing threshold.
        3. Tags affected candidates with drift_penalty factor for LLM context.
        """
        max_chasing = self._trading_profile.get("max_intraday_chasing", 5.0)
        filter_limit_up = self._trading_profile.get("filter_limit_up", True)
        limit_up_config = self._trading_profile.get("limit_up_pct", {})

        if not filter_limit_up and max_chasing >= 20.0:
            return candidates  # No filtering configured

        result: list[StockCandidate] = []
        excluded = 0

        for c in candidates:
            change = c.change_pct
            limit_pct = self._get_limit_up_pct(c.symbol, limit_up_config)

            # Check if at limit-up (within 0.5% tolerance for rounding)
            at_limit_up = change >= (limit_pct - 0.5)

            if filter_limit_up and at_limit_up:
                excluded += 1
                logger.debug(
                    "Excluded limit-up stock: %s (%s) change=%.2f%% limit=%.1f%%",
                    c.symbol,
                    c.name,
                    change,
                    limit_pct,
                )
                continue

            # Penalize stocks above chasing threshold
            if change > max_chasing:
                # Progressive penalty: 5% over → 0.85x, 8% over → 0.7x
                overshoot = change - max_chasing
                penalty = max(0.5, 1.0 - overshoot * 0.05)
                old_score = c.score
                c.score = round(c.score * penalty, 4)
                c.factors["drift_penalty"] = round(1.0 - penalty, 4)
                c.factors["intraday_change"] = round(change, 2)
                logger.debug(
                    "Drift penalty: %s (%s) change=%.2f%% score %.4f→%.4f (×%.2f)",
                    c.symbol,
                    c.name,
                    change,
                    old_score,
                    c.score,
                    penalty,
                )

            result.append(c)

        if excluded:
            logger.info(
                "Intraday drift filter: excluded %d limit-up stocks, "
                "%d candidates remain",
                excluded,
                len(result),
            )

        # Enrich with overnight risk data (I-090 Phase 2)
        horizon = self._trading_profile.get("horizon", "short")
        if horizon in ("ultra_short", "short") and result:
            self._enrich_overnight_risk(result)

        # Re-sort after penalty adjustments
        result.sort(key=lambda c: c.score, reverse=True)
        return result

    def _enrich_overnight_risk(self, candidates: list[StockCandidate]) -> None:
        """Enrich candidates with overnight risk factors (I-090 Phase 2).

        Adds overnight_risk factor (0-1, higher=riskier) and optional
        score penalty for high-risk stocks.
        """
        try:
            if self._overnight_risk is None:
                from src.recommendation.overnight_risk import OvernightRiskCalculator

                self._overnight_risk = OvernightRiskCalculator()

            symbols = [c.symbol for c in candidates[:15]]  # Top 15 only (perf)
            profiles = self._overnight_risk.calculate_batch(
                symbols,
                days=60,
                rally_threshold=self._trading_profile.get("max_intraday_chasing", 5.0),
            )

            for c in candidates:
                profile = profiles.get(c.symbol)
                if profile:
                    c.factors["overnight_risk"] = profile.risk_score
                    c.factors["gap_down_ratio"] = profile.gap_down_ratio
                    c.factors["post_rally_drawdown"] = profile.post_rally_drawdown_prob
                    # Apply score penalty for high overnight risk
                    if profile.risk_score > 0.7:
                        penalty = 1.0 - (profile.risk_score - 0.7) * 0.5
                        old_score = c.score
                        c.score = round(c.score * max(0.6, penalty), 4)
                        logger.debug(
                            "Overnight risk penalty: %s risk=%.2f score %.4f→%.4f",
                            c.symbol,
                            profile.risk_score,
                            old_score,
                            c.score,
                        )
        except Exception as exc:
            logger.debug("Overnight risk enrichment failed: %s", exc)

    @staticmethod
    def _get_limit_up_pct(symbol: str, limit_up_config: dict[str, float]) -> float:
        """Determine limit-up percentage based on stock board type."""
        bare = _strip_exchange_prefix(symbol)
        if bare.startswith(("300", "301")):
            return limit_up_config.get("chinext", 20.0)
        if bare.startswith(("688", "689")):
            return limit_up_config.get("star", 20.0)
        return limit_up_config.get("main", 10.0)

    def _precompute_sector_stats(
        self, stocks: list[dict]
    ) -> dict[str, dict[str, float]]:
        """Aggregate per-sector statistics from market snapshot.

        Computes median PE/PB, average change %, average market cap, and stock
        count for each sector. Cached with the same 5-min TTL as the snapshot.
        """
        now = time.time()
        if self._sector_stats_cache is not None:
            ts, data = self._sector_stats_cache
            if now - ts < self._cache_ttl:
                return data

        sector_data: dict[str, dict[str, list[float]]] = {}
        for s in stocks:
            sector = s.get("sector", s.get("所处行业", ""))
            if not sector:
                continue
            if sector not in sector_data:
                sector_data[sector] = {
                    "pe_vals": [],
                    "pb_vals": [],
                    "change_vals": [],
                    "mcap_vals": [],
                }
            pe = _safe_float(s.get("pe_ratio", s.get("市盈率-动态")))
            pb = _safe_float(s.get("pb_ratio", s.get("市净率")))
            chg = _safe_float(s.get("change_pct", s.get("涨跌幅"))) or 0.0
            mcap = _safe_float(s.get("market_cap", s.get("总市值")))

            if pe is not None and pe > 0:
                sector_data[sector]["pe_vals"].append(pe)
            if pb is not None and pb > 0:
                sector_data[sector]["pb_vals"].append(pb)
            sector_data[sector]["change_vals"].append(chg)
            if mcap is not None and mcap > 0:
                sector_data[sector]["mcap_vals"].append(mcap)

        result: dict[str, dict[str, float]] = {}
        for sector, vals in sector_data.items():
            result[sector] = {
                "median_pe": (
                    statistics.median(vals["pe_vals"]) if vals["pe_vals"] else 15.0
                ),
                "median_pb": (
                    statistics.median(vals["pb_vals"]) if vals["pb_vals"] else 2.0
                ),
                "avg_change_pct": (
                    statistics.mean(vals["change_vals"]) if vals["change_vals"] else 0.0
                ),
                "avg_market_cap": (
                    statistics.mean(vals["mcap_vals"]) if vals["mcap_vals"] else 1e10
                ),
                "stock_count": len(vals["change_vals"]),
            }

        self._sector_stats_cache = (now, result)
        logger.info("Precomputed sector stats: %d sectors", len(result))
        return result

    def _apply_filters(self, style_config: dict, stocks: list[dict]) -> list[dict]:
        """Apply hard filters from style configuration."""
        filters = style_config.get("filters", {})
        if not filters:
            return stocks

        result = []
        for stock in stocks:
            if self._passes_filters(filters, stock):
                result.append(stock)
        return result

    @staticmethod
    def _passes_filters(filters: dict, stock: dict) -> bool:
        """Check if a stock passes all filter criteria.

        Fields that are ``None`` (missing from the data source, e.g. Sina)
        are skipped rather than treated as 0 — this prevents Sina-sourced
        stocks from being universally rejected by momentum/swing filters.
        """
        pe = stock.get("pe_ratio")
        pb = stock.get("pb_ratio")
        change_pct = stock.get("change_pct", 0)
        turnover = stock.get("turnover_rate")
        volume_ratio = stock.get("volume_ratio")

        if "pe_max" in filters and pe is not None:
            if pe <= 0 or pe > filters["pe_max"]:
                return False

        if "pb_max" in filters and pb is not None:
            if pb <= 0 or pb > filters["pb_max"]:
                return False

        if "change_pct_min" in filters:
            if change_pct < filters["change_pct_min"]:
                return False

        if "change_pct_max" in filters:
            if change_pct > filters["change_pct_max"]:
                return False

        if "turnover_min" in filters and turnover is not None:
            if turnover < filters["turnover_min"]:
                return False

        if "volume_ratio_min" in filters and volume_ratio is not None:
            if volume_ratio < filters["volume_ratio_min"]:
                return False

        return True

    def _score_candidates(
        self, style: str, style_config: dict, stocks: list[dict]
    ) -> list[StockCandidate]:
        """Score and convert filtered stocks to StockCandidate instances."""
        weights = style_config.get("weights", {})
        candidates = []

        # Precompute sector stats once for the entire batch
        sector_stats = self._precompute_sector_stats(stocks)

        for stock in stocks:
            factors = self._compute_factors(style, stock, sector_stats=sector_stats)
            # Weighted composite score
            total_weight = 0.0
            weighted_sum = 0.0
            for factor_name, weight in weights.items():
                factor_val = factors.get(factor_name, 0.5)
                weighted_sum += factor_val * weight
                total_weight += weight

            score = weighted_sum / total_weight if total_weight > 0 else 0.0

            # Cap score for low-quality data: when data_quality < 0.2
            # (only price/change_pct available), limit max score to 0.7
            # to prevent Sina-only stocks from dominating top ranks.
            dq = factors.get("data_quality", 0.5)
            if dq < 0.2:
                score = min(score, 0.7)

            candidates.append(
                StockCandidate(
                    symbol=stock.get("symbol", stock.get("代码", "")),
                    name=stock.get("name", stock.get("名称", "")),
                    price=float(stock.get("price", stock.get("最新价", 0)) or 0),
                    change_pct=float(
                        stock.get("change_pct", stock.get("涨跌幅", 0)) or 0
                    ),
                    volume=float(stock.get("volume", stock.get("成交量", 0)) or 0),
                    turnover_rate=float(
                        stock.get("turnover_rate", stock.get("换手率", 0)) or 0
                    ),
                    pe_ratio=_safe_float(
                        stock.get("pe_ratio", stock.get("市盈率-动态"))
                    ),
                    pb_ratio=_safe_float(stock.get("pb_ratio", stock.get("市净率"))),
                    market_cap=_safe_float(
                        stock.get("market_cap", stock.get("总市值"))
                    ),
                    sector=stock.get("sector", stock.get("所处行业", "")),
                    score=round(score, 4),
                    factors=factors,
                )
            )

        return candidates

    def _compute_factors(
        self,
        style: str,
        stock: dict,
        *,
        sector_stats: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, float]:
        """Compute individual factor scores for a stock.

        Each factor is normalized to [0, 1] range. When ``sector_stats`` is
        provided, placeholder factors are replaced with sector-relative values
        to eliminate absolute-PE bias (e.g. banks always winning on low PE).
        """
        factors: dict[str, float] = {}

        pe = _safe_float(stock.get("pe_ratio", stock.get("市盈率-动态")))
        pb = _safe_float(stock.get("pb_ratio", stock.get("市净率")))
        change_pct = float(stock.get("change_pct", stock.get("涨跌幅", 0)) or 0)
        raw_turnover = stock.get("turnover_rate", stock.get("换手率"))
        turnover = float(raw_turnover) if raw_turnover is not None else None
        raw_volume_ratio = stock.get("volume_ratio")
        volume_ratio = float(raw_volume_ratio) if raw_volume_ratio is not None else None
        market_cap = _safe_float(stock.get("market_cap", stock.get("总市值")))

        # Sector context — fallback to neutral defaults
        sector = stock.get("sector", stock.get("所处行业", ""))
        ss = (sector_stats or {}).get(sector, {})
        median_pe = ss.get("median_pe", 15.0)
        median_pb = ss.get("median_pb", 2.0)
        avg_sector_chg = ss.get("avg_change_pct", 0.0)
        avg_sector_mcap = ss.get("avg_market_cap", 1e10)

        # --- PE score — relative to sector median, not absolute ---
        if pe is not None and pe > 0:
            factors["pe_score"] = max(0, min(1, 1 - pe / 40))
            # pe_relative: how cheap vs sector median (discount → high score)
            pe_ratio_to_median = pe / median_pe if median_pe > 0 else 1.0
            factors["pe_relative"] = max(0, min(1, 1.2 - pe_ratio_to_median * 0.7))
        else:
            factors["pe_score"] = 0.3
            factors["pe_relative"] = 0.3

        # --- PB score ---
        if pb is not None and pb > 0:
            factors["pb_score"] = max(0, min(1, 1 - pb / 5))
        else:
            factors["pb_score"] = 0.3

        # --- Dividend / yield proxy ---
        if pe is not None and pe > 0:
            factors["dividend"] = max(0, min(1, 3 / pe))
            factors["yield"] = factors["dividend"]
        else:
            factors["dividend"] = 0.3
            factors["yield"] = 0.3

        # --- Momentum factors ---
        factors["price_momentum"] = max(0, min(1, 0.5 + change_pct / 20))
        factors["momentum"] = factors["price_momentum"]

        # --- Volume-based factors ---
        # When data source lacks these fields (e.g. Sina), use below-neutral
        # defaults (0.35) so missing data slightly penalizes rather than
        # appearing "average" — prevents score collapse when all stocks lack data.
        _MISSING_VOL_DEFAULT = 0.35
        if volume_ratio is not None:
            factors["volume_momentum"] = max(0, min(1, volume_ratio / 5))
        else:
            factors["volume_momentum"] = _MISSING_VOL_DEFAULT
        if turnover is not None:
            factors["turnover"] = max(0, min(1, turnover / 15))
        else:
            factors["turnover"] = _MISSING_VOL_DEFAULT
        if volume_ratio is not None and turnover is not None:
            factors["volume_pattern"] = max(0, min(1, (volume_ratio * turnover) / 30))
        else:
            factors["volume_pattern"] = _MISSING_VOL_DEFAULT

        # --- Trend ---
        factors["trend"] = max(0, min(1, 0.5 + change_pct / 14))

        # --- Stability ---
        factors["stability"] = max(0, min(1, 1 - abs(change_pct) / 10))

        # --- Volatility ---
        factors["volatility"] = max(0, min(1, abs(change_pct) / 8))
        factors["support_distance"] = 0.5

        # --- Sector-relative factors (replace former 0.5 placeholders) ---

        # revenue_growth → sector heat: how active is this sector overall
        factors["revenue_growth"] = max(0, min(1, 0.5 + avg_sector_chg / 10))

        # profit_growth → individual alpha vs sector average
        alpha = change_pct - avg_sector_chg
        factors["profit_growth"] = max(0, min(1, 0.5 + alpha / 16))

        # growth → average of sector heat and individual alpha
        factors["growth"] = (factors["revenue_growth"] + factors["profit_growth"]) / 2

        # payout_stability → valuation stability relative to sector median
        pe_dev = abs(pe / median_pe - 1) if (pe and pe > 0 and median_pe > 0) else 0.5
        pb_dev = abs(pb / median_pb - 1) if (pb and pb > 0 and median_pb > 0) else 0.5
        factors["payout_stability"] = max(0, min(1, 1 - (pe_dev + pb_dev) / 2))

        # sector_momentum → real sector average change (not individual)
        factors["sector_momentum"] = max(0, min(1, 0.5 + avg_sector_chg / 10))

        # relative_strength → individual alpha vs sector
        factors["relative_strength"] = max(0, min(1, 0.5 + alpha / 16))

        # mcap_diversity → bell curve around sector mean (prevent all-same-size)
        if market_cap and market_cap > 0 and avg_sector_mcap > 0:
            log_ratio = abs(market_cap / avg_sector_mcap - 1)
            factors["mcap_diversity"] = max(0, min(1, exp(-(log_ratio**2) / 0.5)))
        else:
            factors["mcap_diversity"] = _MISSING_VOL_DEFAULT

        if volume_ratio is not None:
            factors["flow_score"] = max(0, min(1, volume_ratio / 3))
        else:
            factors["flow_score"] = _MISSING_VOL_DEFAULT

        # --- Data quality factor ---
        # Counts how many of 5 key fundamental fields are available.
        # Penalizes stocks from partial data sources (e.g. Sina lacks PE/PB/
        # sector/turnover/volume_ratio). When all stocks have same quality,
        # this factor is uniform and doesn't affect ranking — but when mixed
        # sources, stocks with better data get a meaningful boost.
        _KEY_FIELDS = [pe, pb, turnover, volume_ratio, market_cap]
        available = sum(1 for f in _KEY_FIELDS if f is not None)
        has_sector = bool(sector and sector.strip())
        if has_sector:
            available += 1
        factors["data_quality"] = round(available / 6, 4)  # 6 fields total

        # --- Qlib quantitative factor (Phase 4) ---
        qlib_val = self._qlib_factor(stock.get("symbol", stock.get("代码", "")))
        if qlib_val is not None:
            factors["qlib_score"] = qlib_val

        return {k: round(v, 4) for k, v in factors.items()}

    def _qlib_factor(self, symbol: str) -> float | None:
        """Return Qlib prediction score as a scoring factor, or None.

        Queries the SignalFusionEngine for the Qlib actuary signal.
        Returns a value in [0, 1] range, or None if Qlib is unavailable.
        """
        if self._fusion_engine is None or not symbol:
            return None
        try:
            signal = self._fusion_engine.get_qlib_signal(symbol)
            if signal and signal.get("available") and signal.get("score") is not None:
                return max(0.0, min(1.0, signal["score"]))
        except Exception as exc:
            logger.debug("Qlib factor for %s unavailable: %s", symbol, exc)
        return None

    @staticmethod
    def apply_sector_preferences(
        candidates: list[StockCandidate],
        preferred_sectors: list[str],
        cross_sector_ratio: float = 0.2,
    ) -> list[StockCandidate]:
        """Apply sector preference boost with anti-filter-bubble diversity.

        Reserves a fraction of slots for non-preferred sectors (cross-sector discovery)
        to prevent filter bubbles. Tags cross-sector items with a factor marker.

        Args:
            candidates: Scored candidates from screening.
            preferred_sectors: User's preferred sector names.
            cross_sector_ratio: Minimum ratio of slots for non-preferred sectors.

        Returns:
            Reordered candidates with sector diversity applied.
        """
        if not preferred_sectors or not candidates:
            return candidates

        preferred_set = set(preferred_sectors)
        preferred = [c for c in candidates if c.sector in preferred_set]
        non_preferred = [c for c in candidates if c.sector not in preferred_set]

        # Sort each group by score descending
        preferred.sort(key=lambda c: c.score, reverse=True)
        non_preferred.sort(key=lambda c: c.score, reverse=True)

        total = len(candidates)
        cross_slots = max(1, ceil(total * cross_sector_ratio))
        preferred_slots = total - cross_slots

        # Tag non-preferred candidates with cross-sector discovery marker
        for c in non_preferred:
            c.factors["cross_sector_discovery"] = 1.0

        result = preferred[:preferred_slots] + non_preferred[:cross_slots]
        # Fill remaining slots if either group was too small
        remaining = total - len(result)
        if remaining > 0:
            used = {id(c) for c in result}
            extras = [c for c in candidates if id(c) not in used]
            extras.sort(key=lambda c: c.score, reverse=True)
            result.extend(extras[:remaining])

        return result

    def _fetch_market_snapshot(self) -> list[dict]:
        """Fetch A-share market snapshot with multi-source fallback.

        Fallback chain:
        1. EastMoney (push2) via ``stock_zh_a_spot_em`` — full fields
        2. Sina via ``stock_zh_a_spot`` — partial fields (no PE/PB/sector)
        3. Redis cache (``rec:market_snapshot``) — last successful fetch
        4. In-memory stale cache — absolute last resort

        On any successful fetch, the result is cached to both memory and Redis.
        """
        now = time.time()
        if self._snapshot_cache is not None:
            ts, data = self._snapshot_cache
            if now - ts < self._cache_ttl:
                return data

        # --- Source 1: EastMoney (push2.eastmoney.com) ---
        data = self._fetch_snapshot_eastmoney()
        if data:
            self._snapshot_cache = (now, data)
            self._cache_to_redis(data)
            return data

        # --- Source 2: Sina ---
        data = self._fetch_snapshot_sina()
        if data:
            logger.info("Using Sina fallback: %d stocks (partial fields)", len(data))
            self._snapshot_cache = (now, data)
            self._cache_to_redis(data)
            return data

        # --- Source 3: Redis persistent cache ---
        data = self._load_redis_cache()
        if data:
            logger.info("Using Redis cached snapshot: %d stocks", len(data))
            self._snapshot_cache = (now, data)
            return data

        # --- Source 4: stale in-memory cache ---
        if self._snapshot_cache is not None:
            logger.warning("All sources failed, using stale in-memory cache")
            return self._snapshot_cache[1]

        logger.error("All snapshot sources exhausted — no data available")
        return []

    def _fetch_snapshot_eastmoney(self) -> list[dict]:
        """Fetch from EastMoney (push2) via direct curl_cffi client.

        Uses :class:`~src.data.eastmoney_client.EastMoneyClient` which calls
        the push2 API directly with Chrome TLS impersonation and concurrent
        page fetching.  Includes ``f100=行业`` (sector) which akshare's
        ``stock_zh_a_spot_em()`` does not return.
        """
        try:
            from src.data.eastmoney_client import get_eastmoney_client

            client = get_eastmoney_client()
            data = client.fetch_spot()
            if data:
                logger.info(
                    "Fetched EastMoney snapshot via curl_cffi client: %d stocks",
                    len(data),
                )
            return data
        except Exception as exc:
            logger.warning("EastMoney client snapshot failed: %s — trying akshare", exc)

        # Fallback: akshare via em_api_call proxy-patch gateway
        try:
            import akshare as ak

            from src.data.eastmoney_proxy import em_api_call

            df = em_api_call(ak.stock_zh_a_spot_em)
            records = df.to_dict("records")
            normalised = []
            for row in records:
                normalised.append(
                    {
                        "symbol": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "price": _safe_float(row.get("最新价")) or 0,
                        "change_pct": _safe_float(row.get("涨跌幅")) or 0,
                        "volume": _safe_float(row.get("成交量")) or 0,
                        "turnover_rate": _safe_float(row.get("换手率")) or 0,
                        "pe_ratio": _safe_float(row.get("市盈率-动态")),
                        "pb_ratio": _safe_float(row.get("市净率")),
                        "market_cap": _safe_float(row.get("总市值")),
                        "sector": str(row.get("所处行业", "")),
                        "volume_ratio": _safe_float(row.get("量比")) or 1.0,
                    }
                )
            logger.info(
                "Fetched EastMoney snapshot via akshare: %d stocks", len(normalised)
            )
            return normalised
        except Exception as exc2:
            logger.warning("EastMoney akshare fallback also failed: %s", exc2)
            return []

    @staticmethod
    def _fetch_snapshot_sina() -> list[dict]:
        """Fetch from Sina via ``stock_zh_a_spot`` — partial fields.

        Sina lacks PE/PB/sector/turnover/volume_ratio, so those are set to
        ``None``. Filters and scoring handle ``None`` gracefully.
        """
        try:
            import akshare as ak

            # Bypass VPN/proxy for Sina (works from Docker + host)
            old_proxies = os.environ.get("NO_PROXY", "")
            os.environ["NO_PROXY"] = "*"
            try:
                df = ak.stock_zh_a_spot()
            finally:
                if old_proxies:
                    os.environ["NO_PROXY"] = old_proxies
                else:
                    os.environ.pop("NO_PROXY", None)

            records = df.to_dict("records")
            normalized = []
            for row in records:
                normalized.append(
                    {
                        "symbol": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "price": _safe_float(row.get("最新价")) or 0,
                        "change_pct": _safe_float(row.get("涨跌幅")) or 0,
                        "volume": _safe_float(row.get("成交量")),
                        "turnover_rate": None,
                        "pe_ratio": None,
                        "pb_ratio": None,
                        "market_cap": None,
                        "sector": "",
                        "volume_ratio": None,
                    }
                )
            logger.info("Fetched Sina snapshot: %d stocks", len(normalized))
            return normalized
        except Exception as exc:
            logger.warning("Sina snapshot failed: %s", exc)
            return []

    def _cache_to_redis(self, data: list[dict]) -> None:
        """Persist snapshot to Redis with 24h TTL."""
        if not self._redis:
            return
        try:
            self._redis.set(
                "rec:market_snapshot",
                json.dumps(data, ensure_ascii=False),
                ex=86400,
            )
            logger.debug("Cached market snapshot to Redis: %d stocks", len(data))
        except Exception as exc:
            logger.warning("Failed to cache snapshot to Redis: %s", exc)

    def _load_redis_cache(self) -> list[dict]:
        """Load snapshot from Redis persistent cache."""
        if not self._redis:
            return []
        try:
            raw = self._redis.get("rec:market_snapshot")
            if raw:
                data = json.loads(raw)
                logger.info("Loaded Redis cached snapshot: %d stocks", len(data))
                return data
        except Exception as exc:
            logger.warning("Failed to load Redis snapshot cache: %s", exc)
        return []


def _safe_float(val: Any) -> float | None:
    """Convert value to float, returning None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f == f else None  # NaN check
    except (ValueError, TypeError):
        return None
