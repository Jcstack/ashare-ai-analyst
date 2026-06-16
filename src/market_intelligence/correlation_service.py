"""Correlation analysis service.

Computes pairwise correlation matrices and detects anomalies (significant
correlation breakdowns) among a set of stock symbols.

Part of v20.0 Phase 5 market intelligence layer.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("market_intelligence.correlation_service")


class CorrelationService:
    """Compute and monitor inter-stock correlations.

    Args:
        stock_service: Optional shared StockService for fetching price data.
    """

    def __init__(self, stock_service: Any | None = None) -> None:
        self._stock_service = stock_service

    def compute_matrix(
        self,
        symbols: list[str],
        lookback_days: int = 60,
    ) -> dict[str, Any]:
        """Compute pairwise correlation matrix for the given symbols.

        Args:
            symbols: List of 6-digit stock codes.
            lookback_days: Number of trading days to use.

        Returns:
            Dict with ``matrix`` (symbol-to-symbol correlation map),
            ``anomalies`` (pairs whose correlation is unusually low),
            and ``timestamp``.
        """
        if len(symbols) < 2:
            return {
                "matrix": {},
                "anomalies": [],
                "timestamp": _now(),
            }

        returns_df = self._build_returns_df(symbols, lookback_days)
        if returns_df is None or returns_df.shape[1] < 2:
            return {
                "matrix": {},
                "anomalies": [],
                "timestamp": _now(),
            }

        corr_matrix = returns_df.corr()

        # Serialise to nested dict
        matrix_dict: dict[str, dict[str, float]] = {}
        for sym in corr_matrix.columns:
            matrix_dict[sym] = {
                other: round(float(corr_matrix.loc[sym, other]), 4)
                for other in corr_matrix.columns
            }

        anomalies = self._find_anomalies(corr_matrix, threshold=0.3)

        return {
            "matrix": matrix_dict,
            "anomalies": anomalies,
            "timestamp": _now(),
        }

    def detect_anomalies(
        self,
        symbols: list[str],
        threshold: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Detect correlation breakdowns among *symbols*.

        Compares the recent short-window correlation against a longer
        baseline and flags pairs whose correlation dropped significantly.

        Args:
            symbols: List of stock codes.
            threshold: Minimum absolute change in correlation to flag.

        Returns:
            List of anomaly dicts with pair, baseline_corr, recent_corr,
            and change.
        """
        if len(symbols) < 2:
            return []

        baseline_df = self._build_returns_df(symbols, lookback_days=60)
        recent_df = self._build_returns_df(symbols, lookback_days=10)

        if baseline_df is None or recent_df is None:
            return []
        if baseline_df.shape[1] < 2 or recent_df.shape[1] < 2:
            return []

        baseline_corr = baseline_df.corr()
        recent_corr = recent_df.corr()

        # Only consider symbols present in both matrices
        common = list(set(baseline_corr.columns) & set(recent_corr.columns))
        if len(common) < 2:
            return []

        anomalies: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for i, sym_a in enumerate(common):
            for sym_b in common[i + 1 :]:
                pair_key = (sym_a, sym_b)
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                bl = baseline_corr.loc[sym_a, sym_b]
                rc = recent_corr.loc[sym_a, sym_b]
                if np.isnan(bl) or np.isnan(rc):
                    continue

                change = rc - bl
                if abs(change) >= threshold:
                    anomalies.append(
                        {
                            "pair": [sym_a, sym_b],
                            "baseline_corr": round(float(bl), 4),
                            "recent_corr": round(float(rc), 4),
                            "change": round(float(change), 4),
                        }
                    )

        anomalies.sort(key=lambda x: abs(x["change"]), reverse=True)
        return anomalies

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_returns_df(
        self,
        symbols: list[str],
        lookback_days: int,
    ) -> pd.DataFrame | None:
        """Build a DataFrame of daily returns for *symbols*."""
        series_map: dict[str, pd.Series] = {}

        for sym in symbols:
            closes = self._get_closes(sym, lookback_days)
            if closes is not None and len(closes) >= 2:
                series_map[sym] = closes.pct_change().dropna()

        if len(series_map) < 2:
            return None

        return pd.DataFrame(series_map)

    def _get_closes(self, symbol: str, days: int) -> pd.Series | None:
        """Retrieve closing prices for *symbol*."""
        if self._stock_service is None:
            return None
        try:
            df = self._stock_service.get_historical_data(symbol, period=days)
            if df is not None and "close" in df.columns:
                return df["close"]
        except Exception:
            logger.debug("Failed to fetch closes for %s", symbol, exc_info=True)
        return None

    def _find_anomalies(
        self,
        corr_matrix: pd.DataFrame,
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Find pairs with unusually low correlation in the matrix."""
        anomalies: list[dict[str, Any]] = []
        cols = list(corr_matrix.columns)
        seen: set[tuple[str, str]] = set()

        for i, sym_a in enumerate(cols):
            for sym_b in cols[i + 1 :]:
                pair_key = (sym_a, sym_b)
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                val = corr_matrix.loc[sym_a, sym_b]
                if np.isnan(val):
                    continue
                if val < threshold:
                    anomalies.append(
                        {
                            "pair": [sym_a, sym_b],
                            "correlation": round(float(val), 4),
                        }
                    )

        anomalies.sort(key=lambda x: x["correlation"])
        return anomalies


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
