"""Tests for AlternativeBarGenerator -- volume, amount, and imbalance bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta


def _make_minute_data(n=100, base_price=10.0):
    np.random.seed(42)
    dates = [datetime(2026, 3, 10, 9, 30) + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": [base_price + np.random.normal(0, 0.05) for _ in range(n)],
            "high": [base_price + 0.1 + np.random.normal(0, 0.05) for _ in range(n)],
            "low": [base_price - 0.1 + np.random.normal(0, 0.05) for _ in range(n)],
            "close": [base_price + np.random.normal(0, 0.05) for _ in range(n)],
            "volume": [int(50000 + np.random.normal(0, 10000)) for _ in range(n)],
            "amount": [
                base_price * 50000 + np.random.normal(0, 50000) for _ in range(n)
            ],
        }
    )


class TestAlternativeBarGenerator:
    @pytest.fixture()
    def generator(self):
        from src.quant.alternative_bars import AlternativeBarGenerator

        return AlternativeBarGenerator()

    def test_volume_bars_returns_df(self, generator):
        data = _make_minute_data()
        result = generator.volume_bars(data, threshold=200000)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_volume_bars_correct_volume(self, generator):
        """Each volume bar should have roughly threshold volume (overflow may reduce next bar)."""
        data = _make_minute_data()
        threshold = 200000
        result = generator.volume_bars(data, threshold=threshold)
        if len(result) > 1:
            # Total volume across all bars should be roughly correct
            total_vol = result["volume"].sum()
            assert total_vol > 0
            # Average bar volume should be near the threshold
            avg_vol = total_vol / len(result)
            assert avg_vol >= threshold * 0.5

    def test_amount_bars_returns_df(self, generator):
        data = _make_minute_data()
        result = generator.amount_bars(data, threshold=2_000_000)
        assert isinstance(result, pd.DataFrame)

    def test_empty_data(self, generator):
        result = generator.volume_bars(pd.DataFrame(), threshold=100000)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_none_data(self, generator):
        result = generator.volume_bars(None, threshold=100000)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_compute_factors(self, generator):
        data = _make_minute_data()
        bars = generator.volume_bars(data, threshold=200000)
        factors = generator.compute_factors_from_bars(bars)
        assert isinstance(factors, dict)
        for key in [
            "bar_frequency",
            "bar_size_consistency",
            "recent_bar_direction",
            "bar_acceleration",
        ]:
            assert key in factors
            assert 0.0 <= factors[key] <= 1.0

    def test_compute_factors_empty_bars(self, generator):
        factors = generator.compute_factors_from_bars(pd.DataFrame())
        assert all(v == 0.5 for v in factors.values())

    def test_compute_factors_none(self, generator):
        factors = generator.compute_factors_from_bars(None)
        assert all(v == 0.5 for v in factors.values())

    def test_tick_imbalance_bars(self, generator):
        """Tick imbalance bars expect numeric direction (+1/-1)."""
        from dataclasses import dataclass

        @dataclass
        class NumericTick:
            datetime: object
            price: float
            volume: int
            amount: float
            direction: int

        np.random.seed(42)
        ticks = []
        for i in range(100):
            d = 1 if i % 3 != 0 else -1
            ticks.append(
                NumericTick(
                    datetime=datetime(2026, 3, 10, 9, 30, i % 60),
                    price=10.0 + np.random.normal(0, 0.01),
                    volume=100,
                    amount=1000,
                    direction=d,
                )
            )
        result = generator.tick_imbalance_bars(ticks, expected_imbalance=10.0)
        assert isinstance(result, pd.DataFrame)

    def test_tick_imbalance_bars_empty(self, generator):
        result = generator.tick_imbalance_bars([], expected_imbalance=10.0)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_volume_bars_columns(self, generator):
        data = _make_minute_data()
        result = generator.volume_bars(data, threshold=200000)
        if not result.empty:
            expected_cols = [
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "bar_count",
            ]
            for col in expected_cols:
                assert col in result.columns, f"Missing column: {col}"

    def test_amount_bars_threshold(self, generator):
        """Amount bars should accumulate until threshold RMB is reached."""
        data = _make_minute_data()
        threshold = 1_000_000
        result = generator.amount_bars(data, threshold=threshold)
        assert isinstance(result, pd.DataFrame)
        if len(result) > 1:
            # Average bar amount should be near the threshold
            avg_amt = result["amount"].mean()
            assert avg_amt >= threshold * 0.5
