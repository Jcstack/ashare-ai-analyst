"""Technical indicators calculator for A-share stock analysis.

Provides a configurable set of classic technical indicators including
moving averages, MACD, RSI, KDJ, Bollinger Bands, and volume-based
indicators. Configuration is loaded from config/analysis.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import ta
import yaml


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "analysis.yaml"


class TechnicalIndicators:
    """Calculate and attach technical indicators to OHLCV DataFrames.

    Parameters
    ----------
    config_path : Path | str | None
        Path to the YAML configuration file.  When *None* the default
        ``config/analysis.yaml`` relative to the project root is used.
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        with open(config_path, "r", encoding="utf-8") as fh:
            full_config: dict[str, Any] = yaml.safe_load(fh)
        self.config: dict[str, Any] = full_config.get("indicators", {})

    # ------------------------------------------------------------------
    # Moving averages
    # ------------------------------------------------------------------

    def add_moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add simple (MA) and exponential (EMA) moving averages.

        Columns added follow the pattern ``MA_<period>`` or ``EMA_<period>``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with at least a ``close`` column.

        Returns
        -------
        pd.DataFrame
            The input DataFrame with new moving-average columns appended.
        """
        df = df.copy()
        for entry in self.config.get("moving_averages", []):
            period: int = entry["period"]
            ma_type: str = entry["type"].upper()
            if ma_type == "MA":
                df[f"MA_{period}"] = ta.trend.sma_indicator(
                    close=df["close"], window=period
                )
            elif ma_type == "EMA":
                df[f"EMA_{period}"] = ta.trend.ema_indicator(
                    close=df["close"], window=period
                )
        return df

    # ------------------------------------------------------------------
    # MACD
    # ------------------------------------------------------------------

    def add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add MACD line, signal line, and histogram.

        Columns added: ``MACD``, ``MACD_signal``, ``MACD_hist``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with at least a ``close`` column.

        Returns
        -------
        pd.DataFrame
            The input DataFrame with MACD columns appended.
        """
        df = df.copy()
        cfg = self.config.get("macd", {})
        fast: int = cfg.get("fast_period", 12)
        slow: int = cfg.get("slow_period", 26)
        signal: int = cfg.get("signal_period", 9)

        macd_indicator = ta.trend.MACD(
            close=df["close"],
            window_fast=fast,
            window_slow=slow,
            window_sign=signal,
        )
        df["MACD"] = macd_indicator.macd()
        df["MACD_signal"] = macd_indicator.macd_signal()
        df["MACD_hist"] = macd_indicator.macd_diff()
        return df

    # ------------------------------------------------------------------
    # RSI
    # ------------------------------------------------------------------

    def add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add the Relative Strength Index.

        Column added: ``RSI``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with at least a ``close`` column.

        Returns
        -------
        pd.DataFrame
            The input DataFrame with the RSI column appended.
        """
        df = df.copy()
        cfg = self.config.get("rsi", {})
        period: int = cfg.get("period", 14)
        df["RSI"] = ta.momentum.rsi(close=df["close"], window=period)
        return df

    # ------------------------------------------------------------------
    # KDJ  (not available in the `ta` library -- implemented manually)
    # ------------------------------------------------------------------

    def add_kdj(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add the KDJ indicator (K, D, J lines).

        The KDJ oscillator is widely used in A-share markets.  It is
        derived from the stochastic oscillator with an additional *J*
        line computed as ``3K - 2D``.

        Columns added: ``KDJ_K``, ``KDJ_D``, ``KDJ_J``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with ``high``, ``low``, and ``close`` columns.

        Returns
        -------
        pd.DataFrame
            The input DataFrame with KDJ columns appended.
        """
        df = df.copy()
        cfg = self.config.get("kdj", {})
        k_period: int = cfg.get("k_period", 9)
        d_period: int = cfg.get("d_period", 3)
        j_smooth: int = cfg.get("j_smooth", 3)

        low_min = df["low"].rolling(window=k_period, min_periods=1).min()
        high_max = df["high"].rolling(window=k_period, min_periods=1).max()

        # Raw Stochastic Value (RSV)
        rsv = ((df["close"] - low_min) / (high_max - low_min)) * 100
        rsv = rsv.fillna(50.0)  # default neutral when range is zero

        # K line: EMA-style smoothing of RSV
        k_values = np.empty(len(df))
        k_values[0] = 50.0  # initial seed
        for i in range(1, len(df)):
            k_values[i] = (
                k_values[i - 1] * (d_period - 1) / d_period + rsv.iloc[i] / d_period
            )

        # D line: EMA-style smoothing of K
        d_values = np.empty(len(df))
        d_values[0] = 50.0
        for i in range(1, len(df)):
            d_values[i] = (
                d_values[i - 1] * (j_smooth - 1) / j_smooth + k_values[i] / j_smooth
            )

        # J line
        j_values = 3.0 * k_values - 2.0 * d_values

        df["KDJ_K"] = k_values
        df["KDJ_D"] = d_values
        df["KDJ_J"] = j_values
        return df

    # ------------------------------------------------------------------
    # Bollinger Bands
    # ------------------------------------------------------------------

    def add_bollinger(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Bollinger Bands (upper, middle, lower).

        Columns added: ``BB_upper``, ``BB_middle``, ``BB_lower``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with at least a ``close`` column.

        Returns
        -------
        pd.DataFrame
            The input DataFrame with Bollinger Band columns appended.
        """
        df = df.copy()
        cfg = self.config.get("bollinger", {})
        period: int = cfg.get("period", 20)
        std_dev: float = cfg.get("std_dev", 2.0)

        bb = ta.volatility.BollingerBands(
            close=df["close"], window=period, window_dev=std_dev
        )
        df["BB_upper"] = bb.bollinger_hband()
        df["BB_middle"] = bb.bollinger_mavg()
        df["BB_lower"] = bb.bollinger_lband()
        return df

    # ------------------------------------------------------------------
    # Volume indicators
    # ------------------------------------------------------------------

    def add_volume_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume-based indicators (OBV, VWAP).

        Columns added (depending on config): ``OBV``, ``VWAP``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with ``close``, ``volume`` columns.  ``high`` and
            ``low`` are also required when VWAP is enabled.

        Returns
        -------
        pd.DataFrame
            The input DataFrame with volume indicator columns appended.
        """
        df = df.copy()
        cfg = self.config.get("volume", {})

        if cfg.get("obv", True):
            df["OBV"] = ta.volume.on_balance_volume(
                close=df["close"], volume=df["volume"]
            )

        if cfg.get("vwap", True):
            df["VWAP"] = ta.volume.volume_weighted_average_price(
                high=df["high"],
                low=df["low"],
                close=df["close"],
                volume=df["volume"],
            )
        return df

    # ------------------------------------------------------------------
    # Convenience: apply everything
    # ------------------------------------------------------------------

    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all configured technical indicators at once.

        This is a convenience wrapper that sequentially calls every
        ``add_*`` method.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with OHLCV columns (``open``, ``high``, ``low``,
            ``close``, ``volume``).

        Returns
        -------
        pd.DataFrame
            The input DataFrame with all indicator columns appended.
        """
        df = self.add_moving_averages(df)
        df = self.add_macd(df)
        df = self.add_rsi(df)
        df = self.add_kdj(df)
        df = self.add_bollinger(df)
        df = self.add_volume_indicators(df)
        return df
