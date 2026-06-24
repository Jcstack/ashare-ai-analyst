"""Data preprocessing module for A-share stock data.

Implements FR-D002: Clean raw data, handle missing values,
remove suspended trading days, align dates, compute derived metrics.
Raw data in data/raw/ is NEVER modified; results go to data/processed/.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import get_data_dir
from src.utils.logger import get_logger

# Maximum consecutive NaN values allowed in price columns before dropping.
_MAX_CONSECUTIVE_NAN: int = 5

# OHLCV price columns eligible for forward-fill imputation.
_PRICE_COLS: list[str] = ["open", "high", "low", "close"]


class DataPreprocessor:
    """Clean, align, and enrich raw A-share OHLCV data.

    This class implements the full FR-D002 preprocessing pipeline:
      - AC-D002-1: Remove suspended trading days (volume == 0 or NaN).
      - AC-D002-2: Handle missing values (ffill prices, drop long gaps).
      - AC-D002-3: Align multiple symbols to common trading dates.
      - AC-D002-4: Compute derived return metrics.
      - AC-D002-5: Persist processed data to data/processed/ as parquet.
      - AC-D002-6: Normalize column dtypes.

    All public methods return **copies** of DataFrames; input data is never
    mutated.
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # AC-D002-1 / AC-D002-2 / AC-D002-6: clean_ohlcv
    # ------------------------------------------------------------------

    def clean_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean a single OHLCV DataFrame.

        Processing steps (in order):
            1. Remove suspended days where ``volume`` is 0 or NaN.
            2. Forward-fill price columns; drop rows that belong to a
               streak of more than ``_MAX_CONSECUTIVE_NAN`` missing prices.
            3. Normalize dtypes: ``date`` -> datetime64, prices -> float64,
               ``volume`` -> int64.

        Args:
            df: Raw OHLCV DataFrame. Must contain at least the columns
                ``date``, ``open``, ``high``, ``low``, ``close``, and
                ``volume``.

        Returns:
            A cleaned copy of *df*. The original is never modified.
        """
        result = df.copy()
        initial_len = len(result)

        # Ensure volume column exists (some sources return 'amount' instead)
        if "volume" not in result.columns:
            if "amount" in result.columns:
                result = result.rename(columns={"amount": "volume"})
            else:
                result["volume"] = 0

        # --- Step 1: Remove suspended days (停牌) -----------------------
        suspended_mask = result["volume"].isna() | (result["volume"] == 0)
        n_suspended = int(suspended_mask.sum())
        if n_suspended > 0:
            self._logger.warning(
                "Removed %d suspended-trading rows (volume == 0 or NaN)",
                n_suspended,
            )
            result = result.loc[~suspended_mask].copy()

        # --- Step 2: Handle missing values ------------------------------
        # Identify rows that are part of a consecutive NaN streak longer
        # than the allowed threshold (price columns only).
        rows_to_drop = self._long_nan_streak_mask(result, _PRICE_COLS)
        n_streak_drops = int(rows_to_drop.sum())
        if n_streak_drops > 0:
            self._logger.warning(
                "Dropped %d rows due to >%d consecutive NaN in price columns",
                n_streak_drops,
                _MAX_CONSECUTIVE_NAN,
            )
            result = result.loc[~rows_to_drop].copy()

        # Forward-fill remaining (short) gaps in price columns only.
        for col in _PRICE_COLS:
            if col in result.columns:
                result[col] = result[col].ffill()

        # --- Step 3: Normalize dtypes -----------------------------------
        result = self._normalize_dtypes(result)

        final_len = len(result)
        if final_len < initial_len:
            self._logger.info(
                "clean_ohlcv: %d -> %d rows (%d removed)",
                initial_len,
                final_len,
                initial_len - final_len,
            )

        return result

    # ------------------------------------------------------------------
    # AC-D002-3: align_dates
    # ------------------------------------------------------------------

    def align_dates(self, dfs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Align multiple symbol DataFrames to common trading dates.

        Performs an inner join on the ``date`` index / column so that only
        dates present in **every** symbol are kept.

        Args:
            dfs: Mapping of ``{symbol: DataFrame}``.  Each DataFrame must
                 contain a ``date`` column or a DatetimeIndex.

        Returns:
            A new dict of ``{symbol: aligned_DataFrame}`` (copies).
        """
        if not dfs:
            return {}

        # Collect date sets from each symbol.
        date_sets: list[set[pd.Timestamp]] = []
        for symbol, frame in dfs.items():
            dates = self._extract_dates(frame)
            date_sets.append(set(dates))

        common_dates = sorted(set.intersection(*date_sets))
        self._logger.info(
            "align_dates: %d symbols -> %d common trading dates",
            len(dfs),
            len(common_dates),
        )

        aligned: dict[str, pd.DataFrame] = {}
        for symbol, frame in dfs.items():
            tmp = frame.copy()
            dates = self._extract_dates(tmp)
            mask = dates.isin(common_dates)
            aligned[symbol] = tmp.loc[mask].reset_index(drop=True)

        return aligned

    # ------------------------------------------------------------------
    # AC-D002-4: add_returns
    # ------------------------------------------------------------------

    def add_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add daily, weekly, and log return columns.

        New columns:
            - ``daily_return``:  ``close.pct_change()``
            - ``log_return``:    ``np.log(close / close.shift(1))``
            - ``weekly_return``: weekly close pct_change merged back to
              daily rows.

        Args:
            df: DataFrame with at least a ``close`` and ``date`` column.

        Returns:
            A copy of *df* with the three return columns appended.
        """
        result = df.copy()

        # Daily return
        result["daily_return"] = result["close"].pct_change()

        # Log return
        result["log_return"] = np.log(result["close"] / result["close"].shift(1))

        # Weekly return: resample to weekly (last close), compute
        # pct_change, then merge back to daily granularity.
        result = self._add_weekly_return(result)

        return result

    # ------------------------------------------------------------------
    # AC-D002-5: save_processed
    # ------------------------------------------------------------------

    def save_processed(self, df: pd.DataFrame, name: str) -> Path:
        """Save a processed DataFrame to ``data/processed/`` as parquet.

        Args:
            df: The DataFrame to persist.
            name: Base filename (without extension).  The file is saved as
                ``data/processed/{name}.parquet``.

        Returns:
            The absolute ``Path`` to the saved parquet file.
        """
        processed_dir = get_data_dir("processed")
        processed_dir.mkdir(parents=True, exist_ok=True)
        file_path = processed_dir / f"{name}.parquet"
        df.to_parquet(file_path, index=False)
        self._logger.info("Saved processed data -> %s", file_path)
        return file_path

    # ------------------------------------------------------------------
    # Convenience: process_all
    # ------------------------------------------------------------------

    def process_all(self, raw_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Run the full preprocessing pipeline on multiple symbols.

        Pipeline order: clean -> align -> add returns -> save.

        Args:
            raw_data: Mapping of ``{symbol: raw_DataFrame}``.

        Returns:
            A new dict of ``{symbol: processed_DataFrame}``.
        """
        # 1. Clean each symbol independently.
        cleaned: dict[str, pd.DataFrame] = {
            symbol: self.clean_ohlcv(frame) for symbol, frame in raw_data.items()
        }

        # 2. Align to common trading dates.
        aligned = self.align_dates(cleaned)

        # 3. Add return columns and save.
        processed: dict[str, pd.DataFrame] = {}
        for symbol, frame in aligned.items():
            enriched = self.add_returns(frame)
            self.save_processed(enriched, symbol)
            processed[symbol] = enriched

        self._logger.info("process_all complete: %d symbols processed", len(processed))
        return processed

    # ==================================================================
    # Private helpers
    # ==================================================================

    @staticmethod
    def _long_nan_streak_mask(df: pd.DataFrame, columns: list[str]) -> pd.Series:
        """Return a boolean mask flagging rows inside long NaN streaks.

        A row is flagged if **any** of *columns* is NaN and that NaN
        belongs to a consecutive run longer than ``_MAX_CONSECUTIVE_NAN``.
        """
        combined_mask = pd.Series(False, index=df.index)

        for col in columns:
            if col not in df.columns:
                continue
            is_nan = df[col].isna()
            # Group consecutive NaN runs and measure their length.
            groups = (~is_nan).cumsum()
            streak_lengths = is_nan.groupby(groups).transform("sum")
            combined_mask = combined_mask | (
                is_nan & (streak_lengths > _MAX_CONSECUTIVE_NAN)
            )

        return combined_mask

    @staticmethod
    def _normalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce columns to canonical dtypes in-place on *df*."""
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        for col in _PRICE_COLS:
            if col in df.columns:
                df[col] = df[col].astype(np.float64)

        if "volume" in df.columns:
            # Forward-fill before int cast to avoid NaN -> int error.
            df["volume"] = df["volume"].fillna(0).astype(np.int64)

        return df

    @staticmethod
    def _extract_dates(df: pd.DataFrame) -> pd.Series:
        """Extract a Series of datetime dates from a DataFrame."""
        if "date" in df.columns:
            return pd.to_datetime(df["date"])
        if isinstance(df.index, pd.DatetimeIndex):
            return df.index.to_series()
        raise ValueError("DataFrame must have a 'date' column or a DatetimeIndex")

    @staticmethod
    def _add_weekly_return(df: pd.DataFrame) -> pd.DataFrame:
        """Compute weekly returns and merge back to daily rows."""
        date_col = "date" if "date" in df.columns else None

        if date_col is None:
            # Fall back to index if it is a DatetimeIndex.
            if not isinstance(df.index, pd.DatetimeIndex):
                raise ValueError(
                    "Cannot compute weekly return without date information"
                )
            weekly = (
                df["close"].resample("W").last().pct_change().rename("weekly_return")
            )
            df = df.join(weekly, how="left")
            df["weekly_return"] = df["weekly_return"].ffill()
            return df

        # Use explicit date column.
        tmp = df.set_index(pd.to_datetime(df[date_col]))
        weekly = tmp["close"].resample("W").last().pct_change().rename("weekly_return")
        # Reindex to daily dates and forward-fill within each week.
        weekly_aligned = weekly.reindex(tmp.index, method="ffill")
        df["weekly_return"] = weekly_aligned.values

        return df
