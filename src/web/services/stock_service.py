"""Service layer wrapping data fetcher, indicators, and visualizer.

Provides a unified interface for web routes to access stock data,
technical analysis results, and chart HTML fragments.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from src.data.fetcher import DataCollectionError, StockDataFetcher
from src.data.preprocessor import DataPreprocessor
from src.analysis.indicators import TechnicalIndicators
from src.analysis.patterns import PatternRecognizer
from src.analysis.visualizer import ChartVisualizer
from src.utils.config import load_config
from src.utils.logger import get_logger

# Maximum seconds to wait for a single fallback data fetch (Tencent/Sina).
_FALLBACK_TIMEOUT = 30


logger = get_logger("web.stock_service")


class StockService:
    """Orchestrates data fetching, analysis, and chart generation.

    Wraps the core business modules so that web routes only need to
    call simple, high-level methods.
    """

    def __init__(self, watchlist_service=None, qmt_adapter=None) -> None:
        self._fetcher = StockDataFetcher()
        self._preprocessor = DataPreprocessor()
        self._indicators = TechnicalIndicators()
        self._patterns = PatternRecognizer()
        self._visualizer = ChartVisualizer()
        self._stocks_config = load_config("stocks")
        self._watchlist_service = watchlist_service
        self._qmt = qmt_adapter
        # Cache last successful tick data per symbol for non-trading-hours fallback
        self._tick_cache: dict[str, dict[str, Any]] = {}
        self._tick_with_ticks_cache: dict[str, dict[str, Any]] = {}
        # 60s in-memory cache for indicator summaries (audit recommendation #2)
        self._indicator_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._indicator_cache_ttl: float = 60.0

    @property
    def fetcher(self) -> StockDataFetcher:
        """Expose the data fetcher for direct market data access."""
        return self._fetcher

    def get_watchlist(self) -> list[dict[str, str]]:
        """Return the watchlist from WatchlistService (SQLite).

        Falls back to stocks.yaml config if WatchlistService is unavailable.

        Returns:
            List of dicts with keys: symbol, name, board.
        """
        if self._watchlist_service is not None:
            return self._watchlist_service.list_all()
        return self._stocks_config.get("watchlist", [])

    def get_stock_data(self, symbol: str) -> pd.DataFrame | None:
        """Fetch and clean OHLCV data for a single symbol.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Cleaned DataFrame or None if fetching fails.
        """
        try:
            raw_df = self._fetcher.fetch_daily_ohlcv(symbol)
            cleaned = self._preprocessor.clean_ohlcv(raw_df)
            return cleaned
        except DataCollectionError:
            logger.error("Failed to fetch data for %s", symbol)
            return None
        except Exception as exc:
            logger.error("Unexpected error fetching %s: %s", symbol, exc)
            return None

    def get_stock_with_indicators(self, symbol: str) -> pd.DataFrame | None:
        """Fetch data and compute all technical indicators.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with OHLCV + indicator columns, or None.
        """
        df = self.get_stock_data(symbol)
        if df is None or df.empty:
            return None
        return self._indicators.add_all(df)

    def get_stock_with_patterns(self, symbol: str) -> pd.DataFrame | None:
        """Fetch data and detect candlestick patterns.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with OHLCV + pattern columns, or None.
        """
        df = self.get_stock_data(symbol)
        if df is None or df.empty:
            return None
        return self._patterns.generate_signals(df)

    def get_latest_price_info(self, symbol: str) -> dict[str, Any] | None:
        """Get the latest price, change, and volume for a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with keys: close, change, pct_change, volume, date.
            Returns None if data unavailable.
        """
        df = self.get_stock_data(symbol)
        if df is None or df.empty:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        change = last["close"] - prev["close"]
        pct = (change / prev["close"]) * 100 if prev["close"] != 0 else 0

        return {
            "close": float(last["close"]),
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "change": float(change),
            "pct_change": float(pct),
            "volume": int(last["volume"]) if "volume" in last.index else 0,
            "date": str(last.get("date", "")),
        }

    def get_support_resistance(self, symbol: str) -> list[dict[str, Any]]:
        """Find support and resistance levels for a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            List of level dicts with keys: level, type, touches.
        """
        df = self.get_stock_data(symbol)
        if df is None or df.empty:
            return []
        return self._patterns.find_support_resistance(df)

    def generate_candlestick_chart_html(
        self,
        symbol: str,
        indicators: list[str] | None = None,
        div_id: str = "chart-container",
    ) -> str:
        """Generate a Plotly candlestick chart as an embeddable HTML div.

        Args:
            symbol: 6-digit stock code.
            indicators: Overlay column names (e.g. ["MA_5", "MA_20"]).
            div_id: HTML id for the chart container div.

        Returns:
            HTML string of the Plotly chart, or an error message div.
        """
        df = self.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return '<div class="alert alert-error">无法加载图表数据</div>'

        stock_name = self._find_stock_name(symbol)
        title = f"{stock_name} ({symbol}) K线图"

        fig = self._visualizer.plot_candlestick(df, title=title, indicators=indicators)
        fig.update_layout(
            height=500,
            margin=dict(l=40, r=20, t=50, b=30),
        )

        return fig.to_html(
            full_html=False,
            include_plotlyjs="cdn",
            div_id=div_id,
        )

    def generate_indicators_chart_html(
        self,
        symbol: str,
        groups: list[str] | None = None,
        div_id: str = "indicators-container",
    ) -> str:
        """Generate a Plotly indicators subplot chart as HTML.

        Args:
            symbol: 6-digit stock code.
            groups: Indicator group names (e.g. ["macd", "rsi"]).
            div_id: HTML id for the chart container div.

        Returns:
            HTML string of the Plotly indicators chart.
        """
        df = self.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return '<div class="alert alert-error">无法加载指标数据</div>'

        fig = self._visualizer.plot_indicators(df, indicators=groups)
        fig.update_layout(
            margin=dict(l=40, r=20, t=30, b=30),
        )

        return fig.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id=div_id,
        )

    def get_indicators_summary(self, symbol: str) -> dict[str, Any]:
        """Get a summary of the latest indicator values.

        Results are cached for 60s to reduce redundant computation.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with the last row's indicator values.
        """
        import time as _time

        # Check 60s cache
        if symbol in self._indicator_cache:
            cached_at, cached_data = self._indicator_cache[symbol]
            if _time.monotonic() - cached_at < self._indicator_cache_ttl:
                return cached_data

        df = self.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return {}

        last = df.iloc[-1]
        summary: dict[str, Any] = {}

        # Moving averages
        for col in df.columns:
            if col.startswith("MA_") or col.startswith("EMA_"):
                summary[col] = (
                    round(float(last[col]), 2) if pd.notna(last[col]) else None
                )

        # MACD
        for col in ["MACD", "MACD_signal", "MACD_hist"]:
            if col in df.columns:
                summary[col] = (
                    round(float(last[col]), 4) if pd.notna(last[col]) else None
                )

        # RSI
        if "RSI" in df.columns:
            summary["RSI"] = (
                round(float(last["RSI"]), 2) if pd.notna(last["RSI"]) else None
            )

        # KDJ
        for col in ["KDJ_K", "KDJ_D", "KDJ_J"]:
            if col in df.columns:
                summary[col] = (
                    round(float(last[col]), 2) if pd.notna(last[col]) else None
                )

        # Bollinger
        for col in ["BB_upper", "BB_middle", "BB_lower"]:
            if col in df.columns:
                summary[col] = (
                    round(float(last[col]), 2) if pd.notna(last[col]) else None
                )

        # Store in 60s cache
        self._indicator_cache[symbol] = (_time.monotonic(), summary)
        return summary

    def get_stock_data_by_period(
        self, symbol: str, period: str = "daily"
    ) -> pd.DataFrame | None:
        """Fetch OHLCV data for a single symbol at a given period.

        Args:
            symbol: 6-digit stock code.
            period: One of 'daily', 'weekly', 'monthly', '1', '5', '15',
                '30', '60', or 'timeline'.

        Returns:
            Cleaned DataFrame or None if fetching fails.
        """
        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call

        minute_periods = {"1", "5", "15", "30", "60"}
        weekly_monthly = {"weekly", "monthly"}

        if period in minute_periods:
            return self._fetch_minute_data(symbol, period)
        if period == "timeline":
            return self._fetch_intraday_timeline(symbol)
        if period in weekly_monthly:
            em_col_map = {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
            # Primary: EastMoney
            try:
                df = em_api_call(
                    ak.stock_zh_a_hist, symbol=symbol, period=period, adjust="qfq"
                )
                if df is not None and not df.empty:
                    df = df.rename(columns=em_col_map)
                    return df
            except Exception:
                logger.warning(
                    "EastMoney %s failed for %s, trying Tencent fallback",
                    period,
                    symbol,
                )
            # Fallback: Tencent (only supports daily, so aggregate manually)
            # If Tencent also fails, return None
            try:
                df = self.get_stock_data(symbol)
                if df is None or df.empty:
                    return None
                return self._resample_daily(df, period)
            except Exception:
                logger.error("Failed to fetch %s data for %s", period, symbol)
                return None
        # Default: daily
        return self.get_stock_data(symbol)

    def _fetch_minute_data(self, symbol: str, period: str = "5") -> pd.DataFrame | None:
        """Fetch minute-level OHLCV data.

        Source chain: QMT → EastMoney → Sina.

        Args:
            symbol: 6-digit stock code.
            period: Minute interval: '1', '5', '15', '30', or '60'.

        Returns:
            DataFrame with date, open, high, low, close, volume, or None.
        """
        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call
        from src.data.fetcher import _bypass_proxy

        em_col_map = {
            "时间": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }

        # QMT primary source
        if self._qmt and self._qmt.is_available():
            df = self._qmt.get_minute_bars(symbol, period)
            if df is not None and not df.empty:
                return df

        # EastMoney secondary
        try:
            df = em_api_call(ak.stock_zh_a_hist_min_em, symbol=symbol, period=period)
            if df is not None and not df.empty:
                df = df.rename(columns=em_col_map)
                return df
        except Exception as exc:
            logger.warning(
                "EastMoney %s-min failed for %s: %s, trying Sina fallback",
                period,
                symbol,
                exc,
            )

        # Sina tertiary (with timeout — can block indefinitely)
        try:
            sina_symbol = self._fetcher._to_tx_symbol(symbol)

            def _fetch_sina():
                with _bypass_proxy():
                    return ak.stock_zh_a_minute(
                        symbol=sina_symbol, period=period, adjust="qfq"
                    )

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_fetch_sina)
                df = future.result(timeout=_FALLBACK_TIMEOUT)
            if df is None or df.empty:
                return None
            df = df.rename(columns={"day": "date"})
            return df
        except FuturesTimeoutError:
            logger.warning(
                "Sina %s-min timed out for %s (%ds)", period, symbol, _FALLBACK_TIMEOUT
            )
            return None
        except Exception as exc:
            logger.error("Sina %s-min also failed for %s: %s", period, symbol, exc)
            return None

    def _fetch_intraday_timeline(self, symbol: str) -> pd.DataFrame | None:
        """Fetch today's intraday timeline (1-min resolution).

        Source chain: QMT → EastMoney → Sina.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with date, open, high, low, close, volume, or None.
        """
        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call
        from src.data.fetcher import _bypass_proxy

        em_col_map = {
            "时间": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }

        # QMT primary source
        if self._qmt and self._qmt.is_available():
            df = self._qmt.get_minute_bars(symbol, "1")
            if df is not None and not df.empty:
                return df

        # EastMoney secondary
        try:
            df = em_api_call(ak.stock_zh_a_hist_pre_min_em, symbol=symbol)
            if df is not None and not df.empty:
                df = df.rename(columns=em_col_map)
                return df
        except Exception as exc:
            logger.warning(
                "EastMoney timeline failed for %s: %s, trying Sina fallback",
                symbol,
                exc,
            )

        # Fallback: Sina 1-min data (with timeout — can block indefinitely)
        try:
            sina_symbol = self._fetcher._to_tx_symbol(symbol)

            def _fetch_sina():
                with _bypass_proxy():
                    return ak.stock_zh_a_minute(
                        symbol=sina_symbol, period="1", adjust="qfq"
                    )

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_fetch_sina)
                df = future.result(timeout=_FALLBACK_TIMEOUT)
            if df is None or df.empty:
                return None
            df = df.rename(columns={"day": "date"})
            df["date"] = df["date"].astype(str)
            # Filter to the most recent trading day's data (works on weekends/holidays)
            latest_date = df["date"].str[:10].max()
            df = df[df["date"].str.startswith(latest_date)]
            if df.empty:
                return None
            return df.reset_index(drop=True)
        except FuturesTimeoutError:
            logger.warning(
                "Sina timeline timed out for %s (%ds)", symbol, _FALLBACK_TIMEOUT
            )
            return None
        except Exception as exc:
            logger.error("Sina timeline also failed for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _resample_daily(df: pd.DataFrame, period: str) -> pd.DataFrame:
        """Resample daily OHLCV to weekly or monthly.

        Args:
            df: Daily DataFrame with date, open, high, low, close, volume.
            period: 'weekly' or 'monthly'.

        Returns:
            Resampled DataFrame.
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        rule = "W" if period == "weekly" else "ME"
        resampled = (
            df.resample(rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open"])
        )
        resampled = resampled.reset_index()
        resampled["date"] = resampled["date"].dt.strftime("%Y-%m-%d")
        return resampled

    def get_intraday_trades_with_ticks(
        self, symbol: str, max_ticks: int = 50
    ) -> dict[str, Any]:
        """Fetch intraday tick data and return both aggregated stats and recent ticks.

        Source chain: QMT → EastMoney → Tencent.
        Falls back to cached data from the most recent trading session when
        live data is unavailable.

        Args:
            symbol: 6-digit stock code.
            max_ticks: Maximum number of recent tick records to include.

        Returns:
            Dict with ``stats`` (buy/sell/neutral aggregates),
            ``recent_ticks`` (list of individual tick records, newest first),
            and ``is_historical`` flag.
        """
        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call
        from src.data.fetcher import _bypass_proxy

        empty_stats: dict[str, Any] = {
            "buy_volume": 0,
            "sell_volume": 0,
            "neutral_volume": 0,
            "total_volume": 0,
            "buy_ratio": 0,
            "sell_ratio": 0,
        }

        # QMT primary source
        if self._qmt and self._qmt.is_available():
            qmt_result = self._qmt.get_tick_data(symbol, max_ticks)
            if qmt_result is not None:
                self._tick_with_ticks_cache[symbol] = qmt_result
                return qmt_result

        df = None

        # EastMoney secondary (with timeout — can hang after market close)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(em_api_call, ak.stock_intraday_em, symbol=symbol)
                df = future.result(timeout=10)
        except FuturesTimeoutError:
            logger.warning(
                "EastMoney intraday trades timed out for %s (10s), trying Tencent",
                symbol,
            )
        except Exception as exc:
            logger.warning(
                "EastMoney intraday trades failed for %s: %s, trying Tencent",
                symbol,
                exc,
            )

        # Fallback: Tencent tick data (with timeout — this call can block 400s+)
        if df is None or df.empty:
            try:
                tx_symbol = self._fetcher._to_tx_symbol(symbol)

                def _fetch_tencent():
                    with _bypass_proxy():
                        return ak.stock_zh_a_tick_tx_js(symbol=tx_symbol)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_fetch_tencent)
                    df = future.result(timeout=_FALLBACK_TIMEOUT)
            except FuturesTimeoutError:
                logger.warning(
                    "Tencent tick data timed out for %s (%ds ceiling)",
                    symbol,
                    _FALLBACK_TIMEOUT,
                )
            except Exception as exc:
                logger.error("Tencent tick data also failed for %s: %s", symbol, exc)

        if df is not None and not df.empty:
            stats = self._aggregate_tick_df(df) or empty_stats
            ticks = self._extract_recent_ticks(df, max_ticks)
            result = {"stats": stats, "recent_ticks": ticks, "is_historical": False}
            self._tick_with_ticks_cache[symbol] = result
            return result

        # Return cached data from last trading session
        cached = self._tick_with_ticks_cache.get(symbol)
        if cached:
            return {**cached, "is_historical": True}

        return {"stats": empty_stats, "recent_ticks": [], "is_historical": False}

    @staticmethod
    def _extract_recent_ticks(
        df: pd.DataFrame, max_ticks: int = 50
    ) -> list[dict[str, Any]]:
        """Extract the most recent tick records from a tick DataFrame.

        Handles both EastMoney (stock_intraday_em) and Tencent
        (stock_zh_a_tick_tx_js) column formats.

        Returns a list of dicts with keys: time, price, volume, change, direction.
        """
        # Identify columns
        time_col = None
        for col in df.columns:
            if col in ("成交时间", "time", "成交时间(time)", "时间"):
                time_col = col
                break

        price_col = None
        for col in df.columns:
            if col in ("成交价格", "price", "成交价"):
                price_col = col
                break

        vol_col = None
        for col in df.columns:
            if col in ("成交量", "volume", "现量", "手数"):
                vol_col = col
                break

        nature_col = None
        for col in df.columns:
            if "性质" in str(col) or "direction" in str(col).lower():
                nature_col = col
                break

        change_col = None
        for col in df.columns:
            if col in ("价格变动", "change"):
                change_col = col
                break

        if not all([time_col, price_col, vol_col]):
            return []

        recent = df.tail(max_ticks).iloc[::-1]
        ticks: list[dict[str, Any]] = []
        for _, row in recent.iterrows():
            direction = "neutral"
            if nature_col and pd.notna(row.get(nature_col)):
                raw = str(row[nature_col])
                if "买" in raw:
                    direction = "buy"
                elif "卖" in raw:
                    direction = "sell"

            change_val = None
            if change_col and pd.notna(row.get(change_col)):
                try:
                    change_val = float(row[change_col])
                except (ValueError, TypeError):
                    pass

            try:
                ticks.append(
                    {
                        "time": str(row[time_col]),
                        "price": float(row[price_col]),
                        "volume": int(float(row[vol_col])),
                        "change": change_val,
                        "direction": direction,
                    }
                )
            except (ValueError, TypeError):
                continue

        return ticks

    def get_intraday_trades(self, symbol: str) -> dict[str, Any] | None:
        """Fetch intraday tick data and aggregate buy/sell volume.

        Source chain: QMT → EastMoney → Tencent.

        Falls back to cached data from the most recent trading session when
        live data is unavailable (non-trading hours, network errors).

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with buy_volume, sell_volume, neutral_volume, total_volume,
            buy_ratio, sell_ratio, is_historical, or None on failure.
        """
        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call
        from src.data.fetcher import _bypass_proxy

        # QMT primary source
        if self._qmt and self._qmt.is_available():
            qmt_result = self._qmt.get_tick_data(symbol)
            if qmt_result is not None:
                stats = qmt_result.get("stats", {})
                stats["is_historical"] = False
                self._tick_cache[symbol] = stats
                return stats

        df = None

        # EastMoney secondary
        try:
            df = em_api_call(ak.stock_intraday_em, symbol=symbol)
            if df is not None and not df.empty:
                result = self._aggregate_tick_df(df)
                if result:
                    result["is_historical"] = False
                    self._tick_cache[symbol] = result
                    return result
        except Exception as exc:
            logger.warning(
                "EastMoney intraday trades failed for %s: %s, trying Tencent",
                symbol,
                exc,
            )

        # Fallback: Tencent tick data (with timeout — can block 400s+)
        try:
            tx_symbol = self._fetcher._to_tx_symbol(symbol)

            def _fetch_tencent():
                with _bypass_proxy():
                    return ak.stock_zh_a_tick_tx_js(symbol=tx_symbol)

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_fetch_tencent)
                df = future.result(timeout=_FALLBACK_TIMEOUT)
            if df is not None and not df.empty:
                result = self._aggregate_tick_df(df)
                if result:
                    result["is_historical"] = False
                    self._tick_cache[symbol] = result
                    return result
        except FuturesTimeoutError:
            logger.warning(
                "Tencent tick data timed out for %s (%ds ceiling)",
                symbol,
                _FALLBACK_TIMEOUT,
            )
        except Exception as exc:
            logger.error("Tencent tick data also failed for %s: %s", symbol, exc)

        # Return cached data from last trading session
        cached = self._tick_cache.get(symbol)
        if cached:
            historical = {**cached, "is_historical": True}
            return historical

        return None

    @staticmethod
    def _aggregate_tick_df(df: pd.DataFrame) -> dict[str, Any] | None:
        """Aggregate a tick DataFrame into buy/sell/neutral volume stats.

        Handles both EastMoney (stock_intraday_em) and Tencent
        (stock_zh_a_tick_tx_js) column formats.
        """
        # Identify the nature column (买卖盘性质)
        nature_col = None
        for col in df.columns:
            if "性质" in str(col) or "direction" in str(col).lower():
                nature_col = col
                break

        vol_col = None
        for col in df.columns:
            if col in ("成交量", "volume", "现量", "手数"):
                vol_col = col
                break

        if nature_col is None or vol_col is None:
            return None

        df[vol_col] = pd.to_numeric(df[vol_col], errors="coerce").fillna(0)

        buy_volume = float(
            df.loc[df[nature_col].str.contains("买", na=False), vol_col].sum()
        )
        sell_volume = float(
            df.loc[df[nature_col].str.contains("卖", na=False), vol_col].sum()
        )
        neutral_volume = float(
            df.loc[~df[nature_col].str.contains("买|卖", na=False), vol_col].sum()
        )
        total = buy_volume + sell_volume + neutral_volume

        return {
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "neutral_volume": neutral_volume,
            "total_volume": total,
            "buy_ratio": round(buy_volume / total, 4) if total > 0 else 0,
            "sell_ratio": round(sell_volume / total, 4) if total > 0 else 0,
        }

    def get_price_change(self, symbol: str, from_date: str, days: int) -> float | None:
        """Compute percentage price change from a date over N trading days.

        Args:
            symbol: 6-digit stock code.
            from_date: ISO date string (YYYY-MM-DD) of the prediction date.
            days: Number of trading days after from_date.

        Returns:
            Percentage change as a float (e.g. 0.05 for +5%), or None
            if data is unavailable.
        """
        df = self.get_stock_data(symbol)
        if df is None or df.empty:
            return None

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        # Find the row on or just after from_date
        mask = df["date"] >= from_date
        if not mask.any():
            return None

        start_idx = mask.idxmax()
        start_row = df.loc[start_idx]

        # Find the row `days` trading days later
        end_idx = start_idx + days
        if end_idx >= len(df):
            return None

        end_row = df.iloc[end_idx]
        start_close = float(start_row["close"])
        end_close = float(end_row["close"])

        if start_close == 0:
            return None

        return round((end_close - start_close) / start_close, 4)

    def get_stock_sector_info(self, symbol: str) -> dict[str, Any]:
        """Fetch the stock's industry and concept board information.

        Delegates to ``ConceptBoardService.fetch_stock_concepts`` which uses
        East Money CoreConception API for the reverse lookup (stock → concepts)
        and joins with the concept list for live metrics.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with keys: industry, concepts (list of concept dicts with
            name, code, pct_change), concept_names (flat list of names).
        """
        from src.data.concept_board import ConceptBoardService

        result: dict[str, Any] = {"industry": "", "concepts": [], "concept_names": []}

        try:
            svc = ConceptBoardService()
            sc = svc.fetch_stock_concepts(symbol)
            # Enrich with real limit-up/down counts (cross-matched with pools)
            svc.enrich_with_limit_counts(sc.concepts)
            result["industry"] = sc.industry
            result["concepts"] = [
                {
                    "code": c.code,
                    "name": c.name,
                    "pct_change": c.pct_change,
                    "up_count": c.up_count,
                    "down_count": c.down_count,
                    "zt_count": c.zt_count,
                    "dt_count": c.dt_count,
                }
                for c in sc.concepts
            ]
            result["concept_names"] = [c.name for c in sc.concepts]
        except Exception as exc:
            logger.warning("Failed to fetch sector info for %s: %s", symbol, exc)

        return result

    def get_stock_detail(self, symbol: str) -> dict[str, str] | None:
        """Look up basic stock info (symbol, name, board) from memory.

        Checks the watchlist first, then falls back to StockRegistry.
        Pure in-memory lookup — no network calls.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with keys ``symbol``, ``name``, ``board``; or None if not found.
        """
        # 1. Check watchlist
        if self._watchlist_service is not None:
            for entry in self._watchlist_service.list_all():
                if entry.get("symbol") == symbol:
                    return {
                        "symbol": symbol,
                        "name": entry.get("name", symbol),
                        "board": entry.get("board", ""),
                    }

        # 2. Check config-based watchlist
        for entry in self._stocks_config.get("watchlist", []):
            if entry["symbol"] == symbol:
                return {
                    "symbol": symbol,
                    "name": entry.get("name", symbol),
                    "board": entry.get("board", ""),
                }

        # 3. Fallback: StockRegistry (full A-share list, cached in memory)
        try:
            from src.web.dependencies import get_stock_registry

            registry = get_stock_registry()
            info = registry.get_stock_info(symbol)
            if info:
                return info
        except Exception:
            pass

        return None

    def _find_stock_name(self, symbol: str) -> str:
        """Look up the Chinese stock name from watchlist or registry.

        Falls back to StockRegistry if not found in the local watchlist.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Chinese stock name, or the symbol itself if not found.
        """
        for entry in self._stocks_config.get("watchlist", []):
            if entry["symbol"] == symbol:
                return entry.get("name", symbol)
        # Fallback: look up from the full A-share registry
        try:
            from src.web.dependencies import get_stock_registry

            registry = get_stock_registry()
            info = registry.get_stock_info(symbol)
            if info:
                return info["name"]
        except Exception:
            pass
        return symbol
