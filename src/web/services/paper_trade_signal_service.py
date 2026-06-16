"""Service for checking strategy signals on paper trading positions.

Implements FR-PT002 from PRD v3.0.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from src.strategy.trend_following import TrendFollowingStrategy
from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.momentum import MomentumStrategy
from src.strategy.base import SIGNAL_BUY, SIGNAL_SELL
from src.web.services.stock_service import StockService
from src.utils.logger import get_logger

logger = get_logger("web.paper_trade_signal_service")

# In-memory cache TTL for realtime data (seconds)
_REALTIME_CACHE_TTL = 300

STRATEGY_MAP: dict[str, type] = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "momentum": MomentumStrategy,
}

STRATEGY_NAMES: dict[str, str] = {
    "trend_following": "趋势跟踪",
    "mean_reversion": "均值回归",
    "momentum": "动量策略",
}


class PaperTradeSignalService:
    """Service for checking latest strategy signals."""

    def __init__(self, stock_service: StockService | None = None) -> None:
        self._stock_service = stock_service or StockService()
        self._realtime_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def check_signals(
        self,
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Check strategy signals for paper trade positions.

        Args:
            positions: List of position dicts with symbol and strategy_key.

        Returns:
            List of signal dicts with symbol, strategy, signal, strength, reason.
        """
        results: list[dict[str, Any]] = []

        for pos in positions:
            symbol = pos.get("symbol", "")
            strategy_key = pos.get("strategy_key", "trend_following")

            if not symbol or strategy_key not in STRATEGY_MAP:
                continue

            try:
                signal = self._get_latest_signal(symbol, strategy_key)
                if signal:
                    results.append(signal)
            except Exception as exc:
                logger.error(
                    "Signal check failed for %s/%s: %s",
                    symbol,
                    strategy_key,
                    exc,
                )

        return results

    def get_latest_signals(self, symbol: str) -> list[dict[str, Any]]:
        """Get latest signals from all strategies for a symbol.

        Args:
            symbol: 6-digit stock code.

        Returns:
            List of signal dicts, one per strategy.
        """
        results: list[dict[str, Any]] = []

        df = self._stock_service.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return results

        for key, cls in STRATEGY_MAP.items():
            try:
                strategy = cls()
                signals_df = strategy.generate_signals(df)

                if signals_df.empty:
                    continue

                # Get last non-hold signal or the very last signal
                last_idx = len(signals_df) - 1
                sig_val = int(signals_df.at[last_idx, "signal"])
                strength = (
                    float(signals_df.at[last_idx, "strength"])
                    if "strength" in signals_df.columns
                    else 0.0
                )
                reason = (
                    str(signals_df.at[last_idx, "reason"])
                    if "reason" in signals_df.columns
                    else ""
                )

                signal_label = "hold"
                if sig_val == SIGNAL_BUY:
                    signal_label = "buy"
                elif sig_val == SIGNAL_SELL:
                    signal_label = "sell"

                # For hold signals, enrich with stock-specific indicator context
                if signal_label == "hold" and (not reason or reason == "0"):
                    reason, strength = self._enrich_hold_signal(df, key)

                entry = {
                    "symbol": symbol,
                    "strategy_key": key,
                    "strategy_name": STRATEGY_NAMES.get(key, key),
                    "signal": signal_label,
                    "signal_value": sig_val,
                    "strength": round(strength, 4),
                    "reason": reason,
                }
                self._confirm_with_realtime(entry, symbol)
                results.append(entry)
            except Exception as exc:
                logger.error(
                    "Signal generation failed for %s/%s: %s",
                    symbol,
                    key,
                    exc,
                )

        return results

    @staticmethod
    def _enrich_hold_signal(
        df: pd.DataFrame,
        strategy_key: str,
    ) -> tuple[str, float]:
        """Compute a stock-specific reason and directional strength for hold signals.

        Returns:
            (reason, strength) where strength encodes directional bias [0, 1].
        """
        if df.empty:
            return ("", 0.0)

        last = df.iloc[-1]

        if strategy_key == "trend_following":
            ma5 = last.get("MA_5")
            ma20 = last.get("MA_20")
            close = last.get("close", 0)
            if pd.notna(ma5) and pd.notna(ma20) and close > 0:
                spread_pct = (ma5 - ma20) / close * 100
                if spread_pct > 0.5:
                    strength = min(abs(spread_pct) / 5.0, 1.0)
                    return (f"多头排列, MA5高于MA20 {spread_pct:.1f}%", strength)
                elif spread_pct < -0.5:
                    strength = min(abs(spread_pct) / 5.0, 1.0)
                    return (f"空头排列, MA5低于MA20 {abs(spread_pct):.1f}%", strength)
                else:
                    return ("均线粘合, 等待方向选择", 0.1)
            return ("指标计算中", 0.0)

        if strategy_key == "mean_reversion":
            rsi = last.get("RSI")
            bb_upper = last.get("BB_upper")
            bb_lower = last.get("BB_lower")
            close = last.get("close", 0)
            parts = []
            strength = 0.3
            if pd.notna(rsi):
                if rsi > 70:
                    parts.append(f"RSI={rsi:.0f} 超买区")
                    strength = min(rsi / 100, 1.0)
                elif rsi < 30:
                    parts.append(f"RSI={rsi:.0f} 超卖区")
                    strength = min((100 - rsi) / 100, 1.0)
                else:
                    parts.append(f"RSI={rsi:.0f} 中性区")
                    strength = 0.2
            if pd.notna(bb_upper) and pd.notna(bb_lower) and close > 0:
                bb_pos = (
                    (close - bb_lower) / (bb_upper - bb_lower) * 100
                    if bb_upper != bb_lower
                    else 50
                )
                parts.append(f"布林带位置{bb_pos:.0f}%")
            return (", ".join(parts) if parts else "指标计算中", strength)

        if strategy_key == "momentum":
            close = last.get("close", 0)
            rsi = last.get("RSI")
            # Compute ROC from last two rows
            if len(df) >= 13:
                prev_close = df.iloc[-13].get("close", 0)
                if prev_close > 0:
                    roc = (close - prev_close) / prev_close * 100
                    parts = [f"动量ROC={roc:+.1f}%"]
                    if pd.notna(rsi):
                        parts.append(f"RSI={rsi:.0f}")
                    strength = min(abs(roc) / 10.0, 1.0)
                    return (", ".join(parts), strength)
            if pd.notna(rsi):
                return (f"RSI={rsi:.0f}", 0.2)
            return ("指标计算中", 0.0)

        return ("", 0.0)

    def _get_realtime_data(self, symbol: str) -> dict[str, Any]:
        """Fetch intraday trades and fund flow with a short cache.

        Returns:
            Dict with ``trades`` and ``fund_flow`` keys.
        """
        now = time.time()
        cached = self._realtime_cache.get(symbol)
        if cached is not None:
            ts, data = cached
            if now - ts < _REALTIME_CACHE_TTL:
                return data

        trades: dict[str, Any] = {}
        fund_flow: list[dict[str, Any]] = []
        try:
            trades = self._stock_service.get_intraday_trades_with_ticks(symbol)
        except Exception as exc:
            logger.debug("Intraday trades unavailable for %s: %s", symbol, exc)
        try:
            ff_raw = self._stock_service.fetcher.fetch_intraday_fund_flow(symbol)
            if hasattr(ff_raw, "to_dict"):
                fund_flow = ff_raw.to_dict(orient="records") if not ff_raw.empty else []
            elif isinstance(ff_raw, list):
                fund_flow = ff_raw
        except Exception as exc:
            logger.debug("Fund flow unavailable for %s: %s", symbol, exc)

        result: dict[str, Any] = {"trades": trades, "fund_flow": fund_flow}
        self._realtime_cache[symbol] = (now, result)
        return result

    def _confirm_with_realtime(
        self,
        signal: dict[str, Any],
        symbol: str,
    ) -> None:
        """Adjust signal strength using intraday trades and fund flow data.

        Modifies *signal* in-place: adjusts ``strength``, appends warnings to
        ``reason``, and adds a ``realtime_confirmation`` sub-dict.
        """
        sig_label = signal.get("signal", "hold")
        if sig_label == "hold":
            return

        try:
            rt = self._get_realtime_data(symbol)
        except Exception:
            return

        trades = rt.get("trades", {})
        fund_flow = rt.get("fund_flow", [])

        stats = trades.get("stats", {}) if isinstance(trades, dict) else {}
        buy_ratio = float(stats.get("buy_ratio", 0))
        sell_ratio = float(stats.get("sell_ratio", 0))

        main_net: float = 0
        if fund_flow:
            row = fund_flow[0] if isinstance(fund_flow, list) else {}
            main_net = float(row.get("main_net", row.get("主力净流入", 0)) or 0)

        data_time = stats.get("update_time", "")

        strength = float(signal.get("strength", 0))
        reason_parts: list[str] = []

        if sig_label == "buy":
            if buy_ratio > 0.55 and main_net > 0:
                strength = min(strength * 1.2, 1.0)
            else:
                if sell_ratio > 0.55:
                    strength *= 0.8
                    reason_parts.append("⚠卖盘偏强")
                if main_net < 0:
                    strength *= 0.85
                    reason_parts.append("⚠主力资金净流出")
        elif sig_label == "sell":
            if sell_ratio > 0.55 and main_net < 0:
                strength = min(strength * 1.2, 1.0)
            else:
                if buy_ratio > 0.55:
                    strength *= 0.8
                    reason_parts.append("⚠买盘偏强")

        signal["strength"] = round(strength, 4)
        if reason_parts:
            existing = signal.get("reason", "")
            signal["reason"] = (
                f"{existing} {' '.join(reason_parts)}".strip()
                if existing
                else " ".join(reason_parts)
            )

        signal["realtime_confirmation"] = {
            "buy_ratio": round(buy_ratio, 4),
            "sell_ratio": round(sell_ratio, 4),
            "main_net": main_net,
            "data_time": data_time,
        }

    def _get_latest_signal(
        self,
        symbol: str,
        strategy_key: str,
    ) -> dict[str, Any] | None:
        """Get the latest signal for a single symbol/strategy pair.

        Returns None if no actionable signal (only returns BUY/SELL).
        """
        df = self._stock_service.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return None

        strategy = STRATEGY_MAP[strategy_key]()
        signals_df = strategy.generate_signals(df)

        if signals_df.empty:
            return None

        last_idx = len(signals_df) - 1
        sig_val = int(signals_df.at[last_idx, "signal"])

        # Only return actionable signals
        if sig_val not in (SIGNAL_BUY, SIGNAL_SELL):
            return None

        strength = (
            float(signals_df.at[last_idx, "strength"])
            if "strength" in signals_df.columns
            else 0.0
        )
        reason = (
            str(signals_df.at[last_idx, "reason"])
            if "reason" in signals_df.columns
            else ""
        )

        signal_label = "buy" if sig_val == SIGNAL_BUY else "sell"

        return {
            "symbol": symbol,
            "strategy_key": strategy_key,
            "strategy_name": STRATEGY_NAMES.get(strategy_key, strategy_key),
            "signal": signal_label,
            "signal_value": sig_val,
            "strength": round(strength, 4),
            "reason": reason,
        }
