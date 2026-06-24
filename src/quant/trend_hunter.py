"""Early-stage trend detection scanner for A-share stocks.

Finds stocks in the accumulation-to-markup transition BEFORE they hit
limit-up.  Unlike the existing market_scanner which scans limit-up stocks
(already +10%, unbuyable), this identifies stocks where institutional
investors are just starting to accumulate.

Core idea: filter the full A-share universe for volume inflection +
MA alignment + momentum + sector strength, then score and rank.

Usage::

    from src.quant.trend_hunter import TrendHunter

    hunter = TrendHunter()
    candidates = hunter.scan(top_n=15)
    for c in candidates:
        print(f"{c.symbol} {c.name}  score={c.score}  signals={c.signals}")
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("quant.trend_hunter")

# ---------------------------------------------------------------------------
# Main board prefixes (600/601/603/605/000/001/002/003)
# ---------------------------------------------------------------------------
_MAIN_BOARD_SH = ("600", "601", "603", "605")
_MAIN_BOARD_SZ = ("000", "001", "002", "003")

# ST / *ST / SST name patterns
_ST_PATTERN = re.compile(r"(ST|st|\*ST|\*st|SST|sst)")

# Cache TTL (seconds)
_CACHE_TTL = 300  # 5 minutes

# Max candidates to deep-analyse (daily OHLCV fetch is expensive)
_MAX_DEEP_CANDIDATES = 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TrendCandidate:
    """A stock showing early-stage trend signals."""

    symbol: str  # 6-digit code
    name: str
    score: float
    pct_change: float
    volume_ratio: float
    price: float
    signals: list[str] = field(default_factory=list)
    sector: str = ""
    near_breakout: bool = False
    has_catalyst: bool = False


# ---------------------------------------------------------------------------
# Scoring helpers (pure functions, no side effects)
# ---------------------------------------------------------------------------


def _score_volume_inflection(
    avg_vol_last_3: float,
    avg_vol_prev_5: float,
) -> tuple[int, str | None]:
    """Score shrink-to-expand volume transition (0-20 pts)."""
    if avg_vol_prev_5 <= 0:
        return 0, None
    ratio = avg_vol_last_3 / avg_vol_prev_5
    if ratio > 2.0:
        return 20, f"放量突破: 近3日量/前5日量={ratio:.1f}x"
    if ratio > 1.5:
        return 15, f"温和放量: 近3日量/前5日量={ratio:.1f}x"
    if ratio > 1.2:
        return 10, f"量能回升: 近3日量/前5日量={ratio:.1f}x"
    return 0, None


def _score_price_breakout(
    price: float,
    ma5: float,
    ma10: float,
    ma20: float,
) -> tuple[int, str | None]:
    """Score MA alignment and breakout proximity (0-20 pts)."""
    if any(np.isnan(v) or v <= 0 for v in (price, ma5, ma10, ma20)):
        return 0, None

    if price > ma20 and ma5 > ma10 > ma20:
        return 20, "多头排列: 价格>MA20, MA5>MA10>MA20"
    if price > ma20:
        return 15, "站上MA20"
    if price > ma10:
        return 10, "站上MA10"
    if ma5 <= price <= ma20:
        return 5, "价格在MA5-MA20之间, 接近突破"
    return 0, None


def _score_momentum(
    macd_hist: float,
    macd_hist_prev: float,
    rsi: float,
) -> tuple[int, str | None]:
    """Score MACD histogram direction and RSI zone (0-20 pts)."""
    score = 0
    parts: list[str] = []

    # MACD histogram turning positive
    if not np.isnan(macd_hist) and not np.isnan(macd_hist_prev):
        if macd_hist > 0 and macd_hist_prev <= 0:
            score += 10
            parts.append("MACD柱翻红")
        elif macd_hist > macd_hist_prev > 0:
            score += 7
            parts.append("MACD柱扩大")

    # RSI zone
    if not np.isnan(rsi):
        if 50 <= rsi <= 70:
            score += 10
            parts.append(f"RSI={rsi:.0f}(健康区间)")
        elif rsi > 70:
            score += 5
            parts.append(f"RSI={rsi:.0f}(偏高)")

    signal = ", ".join(parts) if parts else None
    return min(score, 20), signal


def _score_sector_strength(sector_pct: float | None) -> tuple[int, str | None]:
    """Score sector/concept board strength (0-20 pts)."""
    if sector_pct is None:
        return 0, None
    if sector_pct > 3.0:
        return 20, f"板块强势: +{sector_pct:.1f}%"
    if sector_pct > 2.0:
        return 15, f"板块偏强: +{sector_pct:.1f}%"
    if sector_pct > 1.0:
        return 10, f"板块上涨: +{sector_pct:.1f}%"
    return 0, None


def _score_not_overextended(pct_change: float) -> tuple[int, str | None]:
    """Score momentum + strategy type (0-20 pts)."""
    if 1.0 <= pct_change <= 3.0:
        return 20, f"趋势早期 +{pct_change:.1f}%(最佳介入)"
    if 3.0 < pct_change <= 5.0:
        return 15, f"趋势加速 +{pct_change:.1f}%"
    if 5.0 < pct_change < 7.0:
        return 12, f"强势拉升 +{pct_change:.1f}%"
    if 7.0 <= pct_change < 9.5:
        return 10, f"接近涨停 +{pct_change:.1f}%(打板机会)"
    if pct_change >= 9.5:
        return 8, f"涨停板 +{pct_change:.1f}%(封单状态需确认)"
    if 0.5 <= pct_change < 1.0:
        return 5, f"微涨 +{pct_change:.1f}%(动能不足)"
    return 0, None


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------


def _is_main_board(symbol: str) -> bool:
    """Check if a symbol is on the main board (SH/SZ)."""
    return symbol.startswith(_MAIN_BOARD_SH) or symbol.startswith(_MAIN_BOARD_SZ)


class TrendHunter:
    """Early-stage trend detection scanner for the full A-share market.

    Scans the entire A-share universe via EastMoney batch API, filters for
    volume inflection + moderate gain, then deep-analyses the top candidates
    using daily OHLCV + technical indicators.

    Results are cached for 5 minutes to avoid redundant API calls.

    Args:
        max_workers: Thread pool size for parallel OHLCV fetching.
    """

    def __init__(self, max_workers: int = 6) -> None:
        self._max_workers = max_workers
        self._cache: tuple[float, list[TrendCandidate]] | None = None

    def scan(self, top_n: int = 15) -> list[TrendCandidate]:
        """Scan full market for early-stage trend signals.

        Args:
            top_n: Number of top candidates to return.

        Returns:
            List of ``TrendCandidate`` sorted by score descending.
        """
        # Return cached results if fresh
        if self._cache is not None:
            ts, cached = self._cache
            if time.time() - ts < _CACHE_TTL:
                logger.info("Returning cached trend scan (%d candidates)", len(cached))
                return cached[:top_n]

        try:
            candidates = self._execute_scan(top_n)
        except Exception:
            logger.exception("Trend scan failed")
            candidates = []

        self._cache = (time.time(), candidates)
        return candidates[:top_n]

    def _execute_scan(self, top_n: int) -> list[TrendCandidate]:
        """Internal scan implementation.

        Args:
            top_n: Maximum results to return.

        Returns:
            Scored and sorted list of TrendCandidate.
        """
        # ----- Step 1: Batch realtime quotes ----------------------------------
        from src.data.eastmoney_client import get_eastmoney_client

        client = get_eastmoney_client()
        all_stocks = client.fetch_spot()

        # Fallback: when direct EastMoney API fails (geo-blocked),
        # use AKShare which goes through akshare-proxy-patch.
        if not all_stocks:
            all_stocks = self._fetch_spot_via_akshare()

        logger.info("Fetched %d stocks from EastMoney", len(all_stocks))

        # ----- Step 1b: Sector data (industry boards) -------------------------
        sector_pct_map = self._fetch_sector_map(client)

        # ----- Step 2: Filter candidates --------------------------------------
        pre_filtered = self._pre_filter(all_stocks)
        logger.info(
            "Pre-filter: %d stocks pass volume + price criteria",
            len(pre_filtered),
        )

        # Sort by volume_ratio descending and take top _MAX_DEEP_CANDIDATES
        pre_filtered.sort(key=lambda s: s.get("volume_ratio", 0), reverse=True)
        deep_pool = pre_filtered[:_MAX_DEEP_CANDIDATES]

        # ----- Step 3 & 4: Deep analysis + scoring ----------------------------
        results = self._deep_analyse(deep_pool, sector_pct_map)

        # ----- Step 5: Sort by score ------------------------------------------
        results.sort(key=lambda c: c.score, reverse=True)
        logger.info(
            "Trend scan complete: %d candidates scored, top=%s",
            len(results),
            results[0].symbol if results else "none",
        )
        return results[:top_n]

    def _pre_filter(self, stocks: list[dict]) -> list[dict]:
        """Apply fast pre-filters to the full universe.

        Args:
            stocks: Raw stock dicts from ``EastMoneyClient.fetch_spot()``.

        Returns:
            Filtered list of stock dicts.
        """
        filtered: list[dict] = []
        for s in stocks:
            symbol = s.get("symbol", "")
            name = s.get("name", "")
            pct = s.get("change_pct", 0) or 0
            vol_ratio = s.get("volume_ratio", 0) or 0
            price = s.get("price", 0) or 0

            # Main board only
            if not _is_main_board(symbol):
                continue

            # Skip ST stocks
            if _ST_PATTERN.search(name):
                continue

            # Skip halted / zero-price stocks
            if price <= 0:
                continue

            # Volume ratio threshold
            if vol_ratio < 1.5:
                continue

            # Noise filter: skip flat/slightly negative (< 0.5%)
            # No upper bound — 打板/首板 are valid strategies
            if pct < 0.5:
                continue

            filtered.append(s)
        return filtered

    @staticmethod
    def _fetch_spot_via_akshare() -> list[dict]:
        """Fallback: fetch full market snapshot via AKShare (proxy-patched).

        Returns normalised dicts compatible with EastMoneyClient.fetch_spot().
        """
        try:
            from src.data.eastmoney_proxy import activate_proxy_patch

            activate_proxy_patch()

            import akshare as ak

            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return []

            stocks: list[dict] = []
            for _, row in df.iterrows():
                stocks.append(
                    {
                        "symbol": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "price": float(row.get("最新价", 0) or 0),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "volume": float(row.get("成交量", 0) or 0),
                        "amount": float(row.get("成交额", 0) or 0),
                        "volume_ratio": float(row.get("量比", 1) or 1),
                        "turnover_rate": float(row.get("换手率", 0) or 0),
                        "amplitude": float(row.get("振幅", 0) or 0),
                        "high": float(row.get("最高", 0) or 0),
                        "low": float(row.get("最低", 0) or 0),
                        "open": float(row.get("今开", 0) or 0),
                        "prev_close": float(row.get("昨收", 0) or 0),
                        "pe_ratio": float(row.get("市盈率-动态", 0) or 0),
                        "market_cap": float(row.get("总市值", 0) or 0),
                        "sector": "",
                    }
                )
            logger.info("AKShare fallback: %d stocks fetched", len(stocks))
            return stocks
        except Exception as exc:
            logger.warning("AKShare fallback failed: %s", exc)
            return []

    def _fetch_sector_map(self, client: object) -> dict[str, float]:
        """Build a sector name -> pct_change lookup from industry boards.

        Args:
            client: EastMoneyClient instance.

        Returns:
            Dict mapping sector name to today's pct_change.
        """
        sector_map: dict[str, float] = {}
        try:
            # Use industry boards as the primary sector reference
            boards = client.fetch_industry_boards()  # type: ignore[attr-defined]
            for b in boards:
                name = b.get("name", "")
                pct = b.get("pct_change")
                if name and pct is not None:
                    sector_map[name] = pct
        except Exception:
            logger.warning("Failed to fetch industry boards for sector scoring")
        return sector_map

    def _deep_analyse(
        self,
        pool: list[dict],
        sector_pct_map: dict[str, float],
    ) -> list[TrendCandidate]:
        """Fetch daily OHLCV + indicators for each candidate and score.

        Args:
            pool: Pre-filtered stock dicts.
            sector_pct_map: Sector name -> pct_change map.

        Returns:
            List of scored TrendCandidate objects.
        """
        from src.analysis.indicators import TechnicalIndicators
        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        indicators = TechnicalIndicators()
        results: list[TrendCandidate] = []

        def _analyse_one(stock: dict) -> TrendCandidate | None:
            symbol = stock["symbol"]
            try:
                df = fetcher.fetch_daily_ohlcv(symbol)
            except Exception:
                logger.debug("OHLCV fetch failed for %s, skipping", symbol)
                return None

            if df is None or df.empty or len(df) < 20:
                return None

            # Add technical indicators (returns a copy, original untouched)
            df = indicators.add_moving_averages(df)
            df = indicators.add_macd(df)
            df = indicators.add_rsi(df)

            latest = df.iloc[-1]

            # Extract indicator values with safe fallbacks
            ma5 = _safe_indicator(latest, "MA_5")
            ma10 = _safe_indicator(latest, "MA_10")
            ma20 = _safe_indicator(latest, "MA_20")
            macd_hist = _safe_indicator(latest, "MACD_hist")
            rsi = _safe_indicator(latest, "RSI")
            price = float(latest.get("close", 0))

            # Previous day MACD histogram for crossover detection
            macd_hist_prev = _safe_indicator(df.iloc[-2], "MACD_hist")

            # Volume inflection: last 3 days vs previous 5 days
            if len(df) >= 8:
                avg_vol_last_3 = float(df["volume"].iloc[-3:].mean())
                avg_vol_prev_5 = float(df["volume"].iloc[-8:-3].mean())
            else:
                avg_vol_last_3 = float(df["volume"].iloc[-3:].mean())
                avg_vol_prev_5 = float(df["volume"].iloc[: max(1, len(df) - 3)].mean())

            # Sector lookup
            sector = stock.get("sector", "")
            sector_pct = sector_pct_map.get(sector)

            # ----- Score each dimension -----
            s1, sig1 = _score_volume_inflection(avg_vol_last_3, avg_vol_prev_5)
            s2, sig2 = _score_price_breakout(price, ma5, ma10, ma20)
            s3, sig3 = _score_momentum(macd_hist, macd_hist_prev, rsi)
            s4, sig4 = _score_sector_strength(sector_pct)

            pct_change = float(stock.get("change_pct", 0) or 0)
            s5, sig5 = _score_not_overextended(pct_change)

            total = s1 + s2 + s3 + s4 + s5
            signals = [s for s in (sig1, sig2, sig3, sig4, sig5) if s is not None]

            # Near breakout: price within 3% above MA20
            near_breakout = False
            if ma20 > 0 and not np.isnan(ma20):
                dist_to_ma20 = (price - ma20) / ma20
                near_breakout = -0.02 <= dist_to_ma20 <= 0.03

            return TrendCandidate(
                symbol=symbol,
                name=stock.get("name", ""),
                score=total,
                pct_change=pct_change,
                volume_ratio=float(stock.get("volume_ratio", 0) or 0),
                price=float(stock.get("price", 0) or 0),
                signals=signals,
                sector=sector,
                near_breakout=near_breakout,
                has_catalyst=False,  # placeholder for future news integration
            )

        # Parallel OHLCV fetching
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(_analyse_one, stock): stock for stock in pool}
            for future in as_completed(futures):
                try:
                    candidate = future.result()
                    if candidate is not None and candidate.score > 0:
                        results.append(candidate)
                except Exception:
                    stock = futures[future]
                    logger.debug(
                        "Deep analysis failed for %s",
                        stock.get("symbol", "?"),
                    )

        return results


def _safe_indicator(row: pd.Series, col: str) -> float:
    """Extract an indicator value from a DataFrame row, returning NaN on miss.

    Args:
        row: A single row (``pd.Series``) from the OHLCV DataFrame.
        col: Column name to extract.

    Returns:
        Float value, or ``np.nan`` if the column is missing or null.
    """
    if col not in row.index:
        return np.nan
    val = row[col]
    if pd.isna(val):
        return np.nan
    return float(val)
