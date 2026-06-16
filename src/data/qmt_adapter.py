"""QMT (XtQuant) data adapter — primary real-time data source.

Wraps the xtdata SDK to provide real-time quotes, minute K-lines, tick data,
and daily OHLCV, all normalized to the project's standard DataFrame schema.

Gracefully degrades when XtQuant is not installed (e.g. Docker/CI).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from src.data._qmt_column_maps import KLINE_FIELD_MAP, REALTIME_QUOTE_FIELD_MAP
from src.utils.config import load_config
from src.utils.logger import get_logger

try:
    from xtquant import xtdata

    _HAS_XTDATA = True
except ImportError:
    xtdata = None  # type: ignore[assignment]
    _HAS_XTDATA = False

logger = get_logger("data.qmt_adapter")


class QmtDataAdapter:
    """Adapter for QMT's xtdata SDK, outputting project-standard DataFrames.

    When XtQuant is not installed or the connection fails, ``is_available()``
    returns False and all data methods return None/empty, allowing callers
    to fall back to AKShare/adata seamlessly.

    Args:
        config_name: Config file name for loading QMT settings.
    """

    def __init__(self, config_name: str = "stocks") -> None:
        config = load_config(config_name)
        qmt_cfg = config.get("data_sources", {}).get("qmt", {})
        self._enabled: bool = qmt_cfg.get("enabled", False)
        self._mini_qmt_path: str = qmt_cfg.get("mini_qmt_path", "")
        self._connected: bool = False
        self._subscriptions: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Attempt to connect to the QMT mini terminal.

        Returns:
            True if connected successfully, False otherwise.
        """
        if not _HAS_XTDATA or not self._enabled:
            return False

        try:
            if self._mini_qmt_path:
                xtdata.connect(self._mini_qmt_path)
            self._connected = True
            logger.info("QMT xtdata connected")
            return True
        except Exception as exc:
            logger.warning("QMT xtdata connect failed: %s", exc)
            self._connected = False
            return False

    def is_available(self) -> bool:
        """Check if QMT data source is usable.

        Returns:
            True if xtdata is installed, enabled, and connected.
        """
        if not _HAS_XTDATA or not self._enabled:
            return False
        if not self._connected:
            # Lazy reconnect attempt
            return self.connect()
        return True

    # ------------------------------------------------------------------
    # Symbol conversion
    # ------------------------------------------------------------------

    @staticmethod
    def to_xt_code(symbol: str) -> str:
        """Convert 6-digit stock code to XtQuant format.

        Args:
            symbol: 6-digit stock code (e.g. "600000").

        Returns:
            XtQuant code (e.g. "600000.SH").
        """
        if symbol.startswith("6") or symbol.startswith("9"):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"

    @staticmethod
    def from_xt_code(xt_code: str) -> str:
        """Convert XtQuant code to 6-digit stock code.

        Args:
            xt_code: XtQuant code (e.g. "600000.SH").

        Returns:
            6-digit stock code (e.g. "600000").
        """
        return xt_code.split(".")[0]

    # ------------------------------------------------------------------
    # Realtime quotes
    # ------------------------------------------------------------------

    def get_realtime_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Get real-time quotes matching RealtimeQuoteManager output schema.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            List of quote dicts with keys: symbol, name, price, change,
            pct_change, open, high, low, prev_close, volume, amount.
            Returns empty list if unavailable.
        """
        if not self.is_available():
            return []

        try:
            xt_codes = [self.to_xt_code(s) for s in symbols]
            data = xtdata.get_full_tick(xt_codes)
            if not data:
                return []

            results: list[dict[str, Any]] = []
            for xt_code, tick in data.items():
                symbol = self.from_xt_code(xt_code)
                record: dict[str, Any] = {"symbol": symbol, "name": ""}

                for xt_key, our_key in REALTIME_QUOTE_FIELD_MAP.items():
                    val = tick.get(xt_key)
                    if val is not None:
                        record[our_key] = val

                # Compute change from price and prev_close
                price = record.get("price")
                prev_close = record.get("prev_close")
                if price and prev_close and prev_close > 0:
                    record.setdefault("change", round(price - prev_close, 4))
                    record.setdefault(
                        "pct_change",
                        round((price - prev_close) / prev_close * 100, 4),
                    )

                results.append(record)

            return results
        except Exception as exc:
            logger.warning("QMT get_realtime_quotes failed: %s", exc)
            self._connected = False
            return []

    # ------------------------------------------------------------------
    # Minute K-lines
    # ------------------------------------------------------------------

    def get_minute_bars(
        self,
        symbol: str,
        period: str = "5",
        count: int = -1,
    ) -> pd.DataFrame | None:
        """Get minute K-line data matching existing minute data format.

        Args:
            symbol: 6-digit stock code.
            period: Minute interval: '1', '5', '15', '30', or '60'.
            count: Number of bars to retrieve (-1 for all available).

        Returns:
            DataFrame with date, open, high, low, close, volume columns,
            or None if unavailable.
        """
        if not self.is_available():
            return None

        period_map = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h"}
        xt_period = period_map.get(period)
        if not xt_period:
            return None

        try:
            xt_code = self.to_xt_code(symbol)
            data = xtdata.get_market_data_ex(
                field_list=[],
                stock_list=[xt_code],
                period=xt_period,
                count=count,
            )
            if not data or xt_code not in data:
                return None

            df = data[xt_code]
            if df is None or df.empty:
                return None

            df = df.reset_index()
            df = df.rename(columns=KLINE_FIELD_MAP)

            # Convert timestamp to datetime string
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], unit="ms").dt.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            return df
        except Exception as exc:
            logger.warning("QMT get_minute_bars failed for %s: %s", symbol, exc)
            self._connected = False
            return None

    # ------------------------------------------------------------------
    # Tick data
    # ------------------------------------------------------------------

    def get_tick_data(self, symbol: str, max_ticks: int = 50) -> dict[str, Any] | None:
        """Get tick-level trade data matching existing tick data format.

        Args:
            symbol: 6-digit stock code.
            max_ticks: Maximum number of recent ticks to include.

        Returns:
            Dict with stats (buy/sell/neutral volume aggregates) and
            recent_ticks list, or None if unavailable.
        """
        if not self.is_available():
            return None

        try:
            xt_code = self.to_xt_code(symbol)
            ticks = xtdata.get_full_tick([xt_code])
            if not ticks or xt_code not in ticks:
                return None

            tick = ticks[xt_code]
            ask_prices = tick.get("askPrice", [])
            bid_prices = tick.get("bidPrice", [])
            last_price = tick.get("lastPrice", 0)
            volume = tick.get("volume", 0)

            # Simple classification: compare last price to bid/ask
            buy_volume = 0.0
            sell_volume = 0.0
            if ask_prices and bid_prices and last_price:
                mid = (
                    (ask_prices[0] + bid_prices[0]) / 2
                    if ask_prices[0] and bid_prices[0]
                    else last_price
                )
                if last_price >= mid:
                    buy_volume = float(volume)
                else:
                    sell_volume = float(volume)

            total = buy_volume + sell_volume
            return {
                "stats": {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "neutral_volume": 0.0,
                    "total_volume": total,
                    "buy_ratio": round(buy_volume / total, 4) if total > 0 else 0,
                    "sell_ratio": round(sell_volume / total, 4) if total > 0 else 0,
                },
                "recent_ticks": [],
                "is_historical": False,
            }
        except Exception as exc:
            logger.warning("QMT get_tick_data failed for %s: %s", symbol, exc)
            self._connected = False
            return None

    # ------------------------------------------------------------------
    # Daily OHLCV
    # ------------------------------------------------------------------

    def get_daily_ohlcv(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame | None:
        """Get daily OHLCV from QMT local cache (zero network latency).

        Args:
            symbol: 6-digit stock code.
            start_date: Start date YYYYMMDD.
            end_date: End date YYYYMMDD.

        Returns:
            DataFrame with date, open, high, low, close, volume, amount
            columns, or None if unavailable.
        """
        if not self.is_available():
            return None

        try:
            xt_code = self.to_xt_code(symbol)

            start_ts = start_date or "20240101"
            end_ts = end_date or datetime.now().strftime("%Y%m%d")

            data = xtdata.get_market_data_ex(
                field_list=[],
                stock_list=[xt_code],
                period="1d",
                start_time=start_ts,
                end_time=end_ts,
            )
            if not data or xt_code not in data:
                return None

            df = data[xt_code]
            if df is None or df.empty:
                return None

            df = df.reset_index()
            df = df.rename(columns=KLINE_FIELD_MAP)

            # Convert timestamp to date string
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], unit="ms").dt.strftime(
                    "%Y-%m-%d"
                )

            return df
        except Exception as exc:
            logger.warning("QMT get_daily_ohlcv failed for %s: %s", symbol, exc)
            self._connected = False
            return None

    # ------------------------------------------------------------------
    # Subscription (for WebSocket push in Phase 4)
    # ------------------------------------------------------------------

    def subscribe_quotes(
        self,
        symbols: list[str],
        callback: Callable[[dict[str, Any]], None],
    ) -> bool:
        """Subscribe to real-time quote updates (push-based).

        Args:
            symbols: List of 6-digit stock codes.
            callback: Function called with quote dict on each update.

        Returns:
            True if subscription was established.
        """
        if not self.is_available():
            return False

        try:
            xt_codes = [self.to_xt_code(s) for s in symbols]

            def _on_data(data: dict) -> None:
                for xt_code, tick in data.items():
                    symbol = self.from_xt_code(xt_code)
                    record: dict[str, Any] = {"symbol": symbol}
                    for xt_key, our_key in REALTIME_QUOTE_FIELD_MAP.items():
                        val = tick.get(xt_key)
                        if val is not None:
                            record[our_key] = val

                    price = record.get("price")
                    prev_close = record.get("prev_close")
                    if price and prev_close and prev_close > 0:
                        record.setdefault("change", round(price - prev_close, 4))
                        record.setdefault(
                            "pct_change",
                            round((price - prev_close) / prev_close * 100, 4),
                        )
                    callback(record)

            for xt_code in xt_codes:
                seq = xtdata.subscribe_quote(xt_code, period="tick", callback=_on_data)
                self._subscriptions[xt_code] = seq

            logger.info("QMT subscribed to %d symbols", len(xt_codes))
            return True
        except Exception as exc:
            logger.warning("QMT subscribe_quotes failed: %s", exc)
            return False

    def unsubscribe_all(self) -> None:
        """Unsubscribe from all active quote subscriptions."""
        if not _HAS_XTDATA:
            return
        for xt_code, seq in self._subscriptions.items():
            try:
                xtdata.unsubscribe_quote(seq)
            except Exception:
                pass
        self._subscriptions.clear()

    # ------------------------------------------------------------------
    # Health info
    # ------------------------------------------------------------------

    def get_health_info(self) -> dict[str, Any]:
        """Return health/status information for the QMT adapter.

        Returns:
            Dict with installed, enabled, connected, subscriptions count.
        """
        return {
            "installed": _HAS_XTDATA,
            "enabled": self._enabled,
            "connected": self._connected,
            "active_subscriptions": len(self._subscriptions),
        }
