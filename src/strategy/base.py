"""Abstract base class for A-share trading strategies.

Defines the interface that all concrete strategies must implement,
along with common validation logic for A-share market rules including
T+1 settlement, price limits, and lot-size rounding.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from src.utils.ashare_constants import (
    COMMISSION_RATE,
    LOT_SIZE,
    PRICE_LIMITS,
    STAMP_DUTY_RATE,
)
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Signal constants
SIGNAL_BUY: int = 1
SIGNAL_SELL: int = -1
SIGNAL_HOLD: int = 0

# Board type constants
BOARD_MAIN: str = "main"
BOARD_CHINEXT: str = "chinext"
BOARD_STAR: str = "star"

# Price limits by board live in the canonical constants module and are imported
# above (re-exported here for back-compat; backtest/engine imports PRICE_LIMITS
# from this module).


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Provides config loading, A-share rule validation (T+1, price limits,
    lot-size rounding), and defines the ``generate_signals`` interface
    that concrete strategies must implement.

    Args:
        config_path: Name of the YAML config file (without extension).
            Defaults to ``"strategy"`` which loads ``config/strategy.yaml``.
    """

    def __init__(self, config_path: str = "strategy") -> None:
        self.config: dict[str, Any] = load_config(config_path)
        self.common_config: dict[str, Any] = self.config.get("common", {})
        self.min_lot_size: int = self.common_config.get("min_lot_size", LOT_SIZE)
        self.commission_rate: float = self.common_config.get(
            "commission_rate", COMMISSION_RATE
        )
        self.min_commission: float = self.common_config.get("min_commission", 5.0)
        self.stamp_tax_rate: float = self.common_config.get(
            "stamp_tax_rate", STAMP_DUTY_RATE
        )
        self.stop_loss: float = self.common_config.get("stop_loss", 0.08)
        self.take_profit: float = self.common_config.get("take_profit", 0.15)
        self.position_size: float = self.common_config.get("position_size", 0.3)
        self.max_positions: int = self.common_config.get("max_positions", 3)

        # Track the last buy date for T+1 validation
        self._last_buy_date: pd.Timestamp | None = None

        logger.info(
            "Initialized %s with config '%s'",
            self.__class__.__name__,
            config_path,
        )

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals from OHLCV data.

        Concrete strategies must implement this method.  The returned
        DataFrame must contain the following columns:

        - ``date``: trading date
        - ``signal``: 1 (buy), -1 (sell), or 0 (hold)
        - ``strength``: signal confidence in [0, 1]
        - ``reason``: human-readable description of why the signal fired

        Args:
            df: OHLCV DataFrame with at least ``date``, ``open``, ``high``,
                ``low``, ``close``, and ``volume`` columns.

        Returns:
            A **new** DataFrame (input is never mutated) containing the
            signal columns listed above.
        """

    def get_metadata(self) -> dict[str, Any]:
        """Return strategy metadata for flow visualization and parameter UI.

        Override in subclasses to provide strategy-specific flow steps,
        edges, and configurable parameters.

        Returns:
            Dictionary with keys: ``name``, ``description``,
            ``flow_steps``, ``flow_edges``, ``configurable_params``.
        """
        return {
            "name": self.__class__.__name__,
            "description": "",
            "flow_steps": [],
            "flow_edges": [],
            "configurable_params": [],
        }

    def get_params(self) -> dict[str, Any]:
        """Return current parameter values for parameter preview.

        Override in subclasses to expose tunable parameters.

        Returns:
            Dictionary of parameter name to current value.
        """
        return {}

    def validate_signal(
        self,
        signal: int,
        df: pd.DataFrame,
        idx: int,
        board: str = BOARD_MAIN,
    ) -> bool:
        """Validate a signal against A-share market rules.

        Checks:
        1. **T+1**: A sell signal is blocked if the position was opened
           on the same trading day.
        2. **Price limits**: A signal is blocked when the stock has hit
           its daily price limit (涨跌停).

        Args:
            signal: The proposed signal (``SIGNAL_BUY``, ``SIGNAL_SELL``,
                or ``SIGNAL_HOLD``).
            df: The full OHLCV DataFrame.
            idx: Row index in *df* for the bar being evaluated.
            board: Board type --- ``"main"``, ``"chinext"``, or ``"star"``.

        Returns:
            ``True`` if the signal is valid and may be executed;
            ``False`` otherwise.
        """
        if signal == SIGNAL_HOLD:
            return True

        # --- T+1 check: cannot sell on the same day as a buy ---------
        if signal == SIGNAL_SELL and self._last_buy_date is not None:
            current_date = pd.Timestamp(df.at[idx, "date"])
            if current_date == self._last_buy_date:
                logger.debug(
                    "T+1 rule blocks sell on %s (bought same day)",
                    current_date.date(),
                )
                return False

        # --- Price-limit check ----------------------------------------
        if idx > 0:
            prev_close = df.at[idx - 1, "close"]
            current_close = df.at[idx, "close"]
            if prev_close != 0:
                pct_change = (current_close - prev_close) / prev_close
                if not self._check_price_limit(pct_change, board):
                    logger.debug(
                        "Price limit blocks signal at idx=%d "
                        "(pct_change=%.4f, board=%s)",
                        idx,
                        pct_change,
                        board,
                    )
                    return False

        # --- Track last buy date for future T+1 checks ----------------
        if signal == SIGNAL_BUY:
            self._last_buy_date = pd.Timestamp(df.at[idx, "date"])

        return True

    def _check_price_limit(self, pct_change: float, board: str = BOARD_MAIN) -> bool:
        """Check whether a percentage change is within the board's limit.

        Args:
            pct_change: The price change as a decimal (e.g. 0.05 for +5%).
            board: Board type --- ``"main"``, ``"chinext"``, or ``"star"``.

        Returns:
            ``True`` if the change is **within** the allowed limit
            (i.e. the stock has NOT hit the price limit and trading
            is still possible); ``False`` if the stock has hit its limit.
        """
        limit = PRICE_LIMITS.get(board, 0.10)
        # If the stock has hit exactly the limit or beyond, it is at the
        # price ceiling/floor and new orders will likely be blocked.
        if abs(pct_change) >= limit:
            return False
        return True

    def _round_to_lot(self, shares: float) -> int:
        """Round a number of shares down to the nearest lot (100 shares).

        In A-share markets, the minimum tradable unit is 1 lot = 100 shares
        (1手 = 100股). Fractional lots are not allowed.

        Args:
            shares: The raw (unrounded) number of shares.

        Returns:
            The largest multiple of ``min_lot_size`` that does not exceed
            *shares*.  Returns ``0`` when *shares* < ``min_lot_size``.
        """
        if shares < self.min_lot_size:
            return 0
        return int(shares // self.min_lot_size) * self.min_lot_size

    def _build_signal_row(
        self,
        date: Any,
        signal: int,
        strength: float,
        reason: str,
    ) -> dict[str, Any]:
        """Build a single signal-row dictionary.

        Helper used by concrete strategies to create uniform output rows.

        Args:
            date: The trading date for this signal.
            signal: ``1`` (buy), ``-1`` (sell), or ``0`` (hold).
            strength: Signal confidence in ``[0, 1]``.
            reason: Human-readable description (Chinese).

        Returns:
            Dictionary with keys ``date``, ``signal``, ``strength``,
            ``reason``.
        """
        return {
            "date": date,
            "signal": signal,
            "strength": min(max(strength, 0.0), 1.0),
            "reason": reason,
        }
