"""Backtest engine for A-share strategy evaluation.

Simulates trading with realistic A-share market rules including T+1
settlement, commission, stamp tax, and lot-size constraints.

Implements FR-B001 from the PRD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.strategy.base import (
    BOARD_MAIN,
    PRICE_LIMITS,
    SIGNAL_BUY,
    SIGNAL_SELL,
    BaseStrategy,
)
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestResult:
    """Container for backtest output data.

    Attributes:
        trades: List of trade dictionaries, each containing keys:
            ``date``, ``action``, ``price``, ``shares``, ``commission``,
            ``value``, ``reason``.
        equity_curve: Daily portfolio values (cash + holdings) aligned
            with the input DataFrame rows.
        daily_returns: Daily percentage returns derived from the equity
            curve.
        initial_capital: Starting capital in RMB.
        final_capital: Ending portfolio value in RMB.
        signals: Full signal list from the strategy with date, signal,
            strength, reason, and close_price.
        round_trips: Paired buy/sell round-trip records with reasons.
        dates: ISO date strings aligned with the equity curve.
    """

    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    initial_capital: float = 0.0
    final_capital: float = 0.0
    signals: list[dict[str, Any]] = field(default_factory=list)
    round_trips: list[dict[str, Any]] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)


class BacktestEngine:
    """Event-driven backtest engine for A-share strategies.

    Walks through historical OHLCV data bar-by-bar, executes trading
    signals produced by a :class:`BaseStrategy`, and records all trades,
    equity values, and returns.  Enforces A-share market rules:

    * **T+1**: positions opened today cannot be sold until the next
      trading day.
    * **Lot size**: orders are rounded down to the nearest 100 shares.
    * **Commission**: ``max(amount * rate, min_commission)`` on both
      buy and sell sides.
    * **Stamp tax**: applied on sell-side only.
    * **Stop-loss / take-profit**: checked every bar against the
      average entry price.

    Args:
        config_path: Name of the YAML config file (without extension).
            Defaults to ``"strategy"`` which loads
            ``config/strategy.yaml``.
    """

    def __init__(self, config_path: str = "strategy") -> None:
        config = load_config(config_path)
        common = config.get("common", {})

        self.initial_capital: float = common.get("initial_capital", 1_000_000)
        self.commission_rate: float = common.get("commission_rate", 0.0003)
        self.min_commission: float = common.get("min_commission", 5.0)
        self.stamp_tax_rate: float = common.get("stamp_tax_rate", 0.001)
        self.min_lot_size: int = int(common.get("min_lot_size", 100))
        self.stop_loss: float = common.get("stop_loss", 0.08)
        self.take_profit: float = common.get("take_profit", 0.15)
        self.position_size: float = common.get("position_size", 0.3)

        logger.info(
            "BacktestEngine initialized: capital=%.0f, commission=%.4f, "
            "stamp_tax=%.4f, stop_loss=%.2f, take_profit=%.2f",
            self.initial_capital,
            self.commission_rate,
            self.stamp_tax_rate,
            self.stop_loss,
            self.take_profit,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        strategy: BaseStrategy,
        board: str = BOARD_MAIN,
    ) -> BacktestResult:
        """Run a full backtest over historical data.

        Args:
            df: OHLCV DataFrame with columns ``date``, ``open``,
                ``high``, ``low``, ``close``, ``volume``.
            strategy: A concrete :class:`BaseStrategy` that produces
                trading signals.
            board: Board type for price-limit rules --- ``"main"``,
                ``"chinext"``, or ``"star"``.

        Returns:
            A :class:`BacktestResult` containing trades, equity curve,
            daily returns, and capital figures.

        Raises:
            ValueError: If *df* is empty or missing required columns.
        """
        self._validate_input(df)

        signals_df = strategy.generate_signals(df)
        signals_df = self._align_signals(df, signals_df)

        # Capture full signal list for transparency (FR-SV002/SV003)
        all_signals: list[dict[str, Any]] = []
        for idx in range(len(signals_df)):
            sig_row: dict[str, Any] = {
                "date": str(df.at[idx, "date"])[:10] if "date" in df.columns else "",
                "signal": int(signals_df.at[idx, "signal"]),
                "strength": float(signals_df.at[idx, "strength"])
                if "strength" in signals_df.columns
                and not pd.isna(signals_df.at[idx, "strength"])
                else 0.0,
                "reason": str(signals_df.at[idx, "reason"])
                if "reason" in signals_df.columns
                and not pd.isna(signals_df.at[idx, "reason"])
                else "",
                "close_price": float(df.at[idx, "close"]),
            }
            all_signals.append(sig_row)

        cash: float = self.initial_capital
        shares_held: int = 0
        entry_price: float = 0.0
        buy_date: pd.Timestamp | None = None

        trades: list[dict[str, Any]] = []
        equity_curve: list[float] = []

        for idx in range(len(df)):
            close_price: float = float(df.at[idx, "close"])
            signal: int = int(signals_df.at[idx, "signal"])
            current_date = pd.Timestamp(df.at[idx, "date"])

            # --- Stop-loss / take-profit check (before signal) --------
            if shares_held > 0 and entry_price > 0:
                pnl_pct = (close_price - entry_price) / entry_price

                can_sell_risk = self._can_sell(
                    buy_date, current_date, close_price, df, idx, board
                )

                if can_sell_risk and pnl_pct <= -self.stop_loss:
                    logger.info(
                        "Stop-loss triggered at %s: pnl=%.2f%%",
                        current_date.date(),
                        pnl_pct * 100,
                    )
                    signal = SIGNAL_SELL

                elif can_sell_risk and pnl_pct >= self.take_profit:
                    logger.info(
                        "Take-profit triggered at %s: pnl=%.2f%%",
                        current_date.date(),
                        pnl_pct * 100,
                    )
                    signal = SIGNAL_SELL

            # --- Execute signal ---------------------------------------
            if signal == SIGNAL_BUY and shares_held == 0:
                order_shares = self._calculate_order_shares(cash, close_price)
                if order_shares > 0:
                    buy_value = order_shares * close_price
                    commission = self._calculate_commission(buy_value, is_sell=False)
                    cash -= buy_value + commission
                    shares_held = order_shares
                    entry_price = close_price
                    buy_date = current_date

                    # Capture reason from signal row
                    buy_reason = ""
                    if "reason" in signals_df.columns and not pd.isna(
                        signals_df.at[idx, "reason"]
                    ):
                        buy_reason = str(signals_df.at[idx, "reason"])

                    trades.append(
                        {
                            "date": current_date,
                            "action": "buy",
                            "price": close_price,
                            "shares": order_shares,
                            "commission": commission,
                            "value": buy_value,
                            "reason": buy_reason,
                        }
                    )
                    logger.debug(
                        "BUY %d shares @ %.2f, commission=%.2f",
                        order_shares,
                        close_price,
                        commission,
                    )

            elif signal == SIGNAL_SELL and shares_held > 0:
                if self._can_sell(buy_date, current_date, close_price, df, idx, board):
                    sell_value = shares_held * close_price
                    commission = self._calculate_commission(sell_value, is_sell=True)
                    cash += sell_value - commission

                    # Capture sell reason
                    sell_reason = ""
                    if "reason" in signals_df.columns and not pd.isna(
                        signals_df.at[idx, "reason"]
                    ):
                        sell_reason = str(signals_df.at[idx, "reason"])

                    trades.append(
                        {
                            "date": current_date,
                            "action": "sell",
                            "price": close_price,
                            "shares": shares_held,
                            "commission": commission,
                            "value": sell_value,
                            "reason": sell_reason,
                        }
                    )
                    logger.debug(
                        "SELL %d shares @ %.2f, commission=%.2f",
                        shares_held,
                        close_price,
                        commission,
                    )
                    shares_held = 0
                    entry_price = 0.0
                    buy_date = None
                else:
                    logger.debug(
                        "Sell blocked at %s (T+1 or price-limit rule)",
                        current_date.date(),
                    )

            # --- Record daily equity ----------------------------------
            portfolio_value = cash + shares_held * close_price
            equity_curve.append(portfolio_value)

        # --- Compute daily returns ------------------------------------
        daily_returns = self._compute_daily_returns(equity_curve)

        final_capital = equity_curve[-1] if equity_curve else self.initial_capital

        # --- Build dates list -----------------------------------------
        dates: list[str] = []
        for idx in range(len(df)):
            d = df.at[idx, "date"]
            dates.append(str(d)[:10])

        # --- Build round-trips with reasons ---------------------------
        round_trips = self._build_round_trips(trades)

        logger.info(
            "Backtest complete: %d trades, final capital=%.2f",
            len(trades),
            final_capital,
        )

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            signals=all_signals,
            round_trips=round_trips,
            dates=dates,
        )

    # ------------------------------------------------------------------
    # Commission and lot helpers
    # ------------------------------------------------------------------

    def _calculate_commission(self, amount: float, is_sell: bool) -> float:
        """Calculate trading commission and applicable taxes.

        Commission is charged on both buy and sell sides.  Stamp tax is
        charged on the sell side only.

        Args:
            amount: The total transaction value in RMB.
            is_sell: ``True`` for sell orders, ``False`` for buy orders.

        Returns:
            Total cost (commission + stamp tax if selling).
        """
        commission = max(amount * self.commission_rate, self.min_commission)
        if is_sell:
            commission += amount * self.stamp_tax_rate
        return commission

    def _round_to_lot(self, shares: float) -> int:
        """Round shares down to the nearest lot (100 shares).

        Args:
            shares: The raw (unrounded) number of shares.

        Returns:
            The largest multiple of ``min_lot_size`` that does not
            exceed *shares*.  Returns ``0`` if *shares* is less than
            one lot.
        """
        if shares < self.min_lot_size:
            return 0
        return int(shares // self.min_lot_size) * self.min_lot_size

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_input(self, df: pd.DataFrame) -> None:
        """Validate that the input DataFrame has the required columns.

        Args:
            df: The OHLCV DataFrame to validate.

        Raises:
            ValueError: If *df* is empty or missing required columns.
        """
        if df.empty:
            raise ValueError("Input DataFrame is empty.")
        required_columns = {"date", "open", "high", "low", "close", "volume"}
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"Input DataFrame is missing columns: {missing}")

    def _align_signals(
        self, df: pd.DataFrame, signals_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Align and validate the signals DataFrame against OHLCV data.

        Ensures the signals DataFrame has a ``signal`` column and the
        same number of rows as the price data.  Resets the index so
        integer-based indexing (``df.at[idx, ...]``) works correctly.

        Args:
            df: The OHLCV DataFrame.
            signals_df: The signals DataFrame from the strategy.

        Returns:
            A copy of *signals_df* with a reset index and guaranteed
            ``signal`` column.

        Raises:
            ValueError: If ``signal`` column is missing or row counts
                do not match.
        """
        if "signal" not in signals_df.columns:
            raise ValueError("Signals DataFrame must contain a 'signal' column.")
        if len(signals_df) != len(df):
            raise ValueError(
                f"Signal length ({len(signals_df)}) does not match "
                f"data length ({len(df)})."
            )
        return signals_df.reset_index(drop=True)

    def _calculate_order_shares(self, cash: float, price: float) -> int:
        """Calculate order size respecting position sizing and lot rules.

        The engine allocates ``position_size`` fraction of available
        cash, then rounds down to the nearest 100-share lot.

        Args:
            cash: Available cash in RMB.
            price: Price per share in RMB.

        Returns:
            Number of shares to buy (always a multiple of 100, or 0).
        """
        if price <= 0:
            return 0
        target_value = cash * self.position_size
        raw_shares = target_value / price
        return self._round_to_lot(raw_shares)

    def _can_sell(
        self,
        buy_date: pd.Timestamp | None,
        current_date: pd.Timestamp,
        close_price: float,
        df: pd.DataFrame,
        idx: int,
        board: str,
    ) -> bool:
        """Check whether a sell order is allowed under A-share rules.

        Validates both the T+1 settlement rule and the daily price
        limit for the given board.

        Args:
            buy_date: The date the current position was opened, or
                ``None`` if no position is held.
            current_date: The current bar's trading date.
            close_price: The current bar's closing price.
            df: The full OHLCV DataFrame.
            idx: Row index for the current bar.
            board: Board type (``"main"``, ``"chinext"``, ``"star"``).

        Returns:
            ``True`` if selling is permitted; ``False`` otherwise.
        """
        # T+1: cannot sell on the same day as a buy
        if buy_date is not None and current_date == buy_date:
            return False

        # Price-limit check
        if idx > 0:
            prev_close = float(df.at[idx - 1, "close"])
            if prev_close != 0:
                pct_change = (close_price - prev_close) / prev_close
                limit = PRICE_LIMITS.get(board, 0.10)
                if abs(pct_change) >= limit:
                    return False

        return True

    @staticmethod
    def _build_round_trips(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pair buy/sell trades into round-trip records with reasons.

        Args:
            trades: Flat list of trade dictionaries from the engine.

        Returns:
            List of round-trip dicts with buy/sell dates, prices,
            shares, pnl, holding_days, and reasons.
        """
        round_trips: list[dict[str, Any]] = []
        pending_buy: dict[str, Any] | None = None

        for trade in trades:
            if trade["action"] == "buy":
                pending_buy = trade
            elif trade["action"] == "sell" and pending_buy is not None:
                buy_date = pd.Timestamp(pending_buy["date"])
                sell_date = pd.Timestamp(trade["date"])
                holding_days = (sell_date - buy_date).days

                buy_value = pending_buy["price"] * pending_buy["shares"]
                sell_value = trade["price"] * trade["shares"]
                pnl = (
                    sell_value
                    - buy_value
                    - pending_buy["commission"]
                    - trade["commission"]
                )
                pnl_pct = (pnl / buy_value * 100) if buy_value > 0 else 0.0

                round_trips.append(
                    {
                        "buy_date": str(buy_date)[:10],
                        "sell_date": str(sell_date)[:10],
                        "buy_price": pending_buy["price"],
                        "sell_price": trade["price"],
                        "shares": pending_buy["shares"],
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "holding_days": holding_days,
                        "buy_reason": pending_buy.get("reason", ""),
                        "sell_reason": trade.get("reason", ""),
                    }
                )
                pending_buy = None

        return round_trips

    @staticmethod
    def _compute_daily_returns(equity_curve: list[float]) -> list[float]:
        """Compute percentage daily returns from an equity curve.

        The first day's return is always 0.0 (no prior reference).

        Args:
            equity_curve: List of daily portfolio values.

        Returns:
            List of daily returns (same length as *equity_curve*).
        """
        if len(equity_curve) <= 1:
            return [0.0] * len(equity_curve)
        returns = [0.0]
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            if prev != 0:
                returns.append((equity_curve[i] - prev) / prev)
            else:
                returns.append(0.0)
        return returns
