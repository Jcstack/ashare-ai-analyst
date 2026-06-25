"""Tests for QuantSignalV2Strategy — the v2-stack → backtest-engine adapter.

Covers the BaseStrategy contract and, most importantly, the no-look-ahead
guarantee that makes the resulting equity curve trustworthy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategy.base import SIGNAL_HOLD
from src.strategy.quant_v2 import QuantSignalV2Strategy


def _synthetic_ohlcv(n: int = 80, seed: int = 7) -> pd.DataFrame:
    """Deterministic OHLCV that trends up then down (exercises both directions)."""
    rng = np.random.default_rng(seed)
    half = n // 2
    trend = np.concatenate(
        [np.linspace(0.0, 0.4, half), np.linspace(0.4, -0.1, n - half)]
    )
    noise = rng.normal(0, 0.01, n).cumsum()
    close = 100.0 * np.exp(trend + noise)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * (1 + rng.normal(0, 0.002, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.004, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.004, n))),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
        }
    )


class TestContract:
    def test_one_row_per_bar_with_required_columns(self) -> None:
        df = _synthetic_ohlcv()
        out = QuantSignalV2Strategy(use_regime=False).generate_signals(df)
        assert len(out) == len(df)
        assert {"date", "signal", "strength", "reason"}.issubset(out.columns)

    def test_signal_and_strength_domains(self) -> None:
        df = _synthetic_ohlcv()
        out = QuantSignalV2Strategy(use_regime=False).generate_signals(df)
        assert out["signal"].isin([-1, 0, 1]).all()
        assert (out["strength"] >= 0.0).all()
        assert (out["strength"] <= 1.0).all()

    def test_input_is_not_mutated(self) -> None:
        df = _synthetic_ohlcv()
        before = df.copy()
        QuantSignalV2Strategy(use_regime=False).generate_signals(df)
        pd.testing.assert_frame_equal(df, before)

    def test_warmup_period_holds(self) -> None:
        df = _synthetic_ohlcv()
        strat = QuantSignalV2Strategy(use_regime=False, min_history=30)
        out = strat.generate_signals(df)
        # Bars before min_history are forced to HOLD with zero strength.
        warm = out.iloc[: strat.min_history - 1]
        assert (warm["signal"] == SIGNAL_HOLD).all()
        assert (warm["strength"] == 0.0).all()


class TestNoLookAhead:
    def test_signals_depend_only_on_past(self) -> None:
        """generate_signals(df)[:k] must equal generate_signals(df[:k]).

        If a bar's signal used any future data, truncating the input would
        change earlier signals. Identical outputs prove the pass is causal.
        """
        df = _synthetic_ohlcv(n=80)
        k = 60
        strat = QuantSignalV2Strategy(use_regime=False)
        full = strat.generate_signals(df).iloc[:k].reset_index(drop=True)
        truncated = strat.generate_signals(df.iloc[:k]).reset_index(drop=True)

        assert (full["signal"].to_numpy() == truncated["signal"].to_numpy()).all()
        np.testing.assert_allclose(
            full["strength"].to_numpy(), truncated["strength"].to_numpy(), atol=1e-9
        )


class TestRegimePath:
    def test_regime_enabled_runs_and_keeps_contract(self) -> None:
        df = _synthetic_ohlcv(n=80)
        out = QuantSignalV2Strategy(use_regime=True, regime_stride=5).generate_signals(
            df
        )
        assert len(out) == len(df)
        assert out["signal"].isin([-1, 0, 1]).all()
        assert (out["strength"] <= 1.0).all()
