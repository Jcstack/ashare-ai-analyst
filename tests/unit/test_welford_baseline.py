"""Tests for Welford temporal baselines and detectors."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

from src.data.welford_baseline import (
    MIN_SAMPLES,
    WelfordBaseline,
    WelfordState,
    segment_key,
    time_to_slot,
)
from src.data.price_spike_detector import PriceSpikeDetector
from src.data.volume_anomaly_detector import VolumeAnomalyDetector


# ---------------------------------------------------------------------------
# Tests: time_to_slot
# ---------------------------------------------------------------------------


class TestTimeToSlot:
    def test_morning_open(self):
        assert time_to_slot(9, 30) == 0

    def test_morning_slots(self):
        assert time_to_slot(9, 45) == 0
        assert time_to_slot(10, 0) == 1
        assert time_to_slot(10, 15) == 1
        assert time_to_slot(10, 30) == 2
        assert time_to_slot(11, 0) == 3

    def test_morning_close(self):
        # 11:30 is the boundary — belongs to slot 3
        assert time_to_slot(11, 30) == 3

    def test_afternoon_open(self):
        assert time_to_slot(13, 0) == 4

    def test_afternoon_slots(self):
        assert time_to_slot(13, 30) == 5
        assert time_to_slot(14, 0) == 6
        assert time_to_slot(14, 30) == 7

    def test_afternoon_close(self):
        assert time_to_slot(15, 0) == 7

    def test_outside_hours(self):
        assert time_to_slot(8, 0) is None
        assert time_to_slot(12, 0) is None
        assert time_to_slot(16, 0) is None
        assert time_to_slot(0, 0) is None

    def test_lunch_break(self):
        assert time_to_slot(11, 45) is None
        assert time_to_slot(12, 30) is None


class TestSegmentKey:
    def test_format(self):
        assert segment_key(0, 3) == "d0_s3"
        assert segment_key(4, 9) == "d4_s9"


# ---------------------------------------------------------------------------
# Tests: WelfordState
# ---------------------------------------------------------------------------


class TestWelfordState:
    def test_empty(self):
        s = WelfordState()
        assert s.count == 0
        assert s.mean == 0.0
        assert s.variance == 0.0
        assert s.std == 0.0
        assert s.is_valid is False
        assert s.z_score(1.0) is None

    def test_single_update(self):
        s = WelfordState()
        s.update(10.0)
        assert s.count == 1
        assert s.mean == 10.0
        assert s.variance == 0.0

    def test_known_sequence(self):
        """Verify against known mean/variance for [2, 4, 4, 4, 5, 5, 7, 9]."""
        values = [2, 4, 4, 4, 5, 5, 7, 9]
        s = WelfordState()
        for v in values:
            s.update(v)
        assert s.count == 8
        assert math.isclose(s.mean, 5.0)
        # Population variance = 4.0
        assert math.isclose(s.variance, 4.0)
        assert math.isclose(s.std, 2.0)

    def test_z_score_insufficient_samples(self):
        s = WelfordState()
        for i in range(MIN_SAMPLES - 1):
            s.update(float(i))
        assert s.z_score(0.0) is None

    def test_z_score_valid(self):
        s = WelfordState()
        for i in range(MIN_SAMPLES + 10):
            s.update(100.0)  # constant value
        # Std dev is 0, so z_score should be None
        assert s.z_score(100.0) is None

        # Now with varied data
        s2 = WelfordState()
        for i in range(MIN_SAMPLES + 10):
            s2.update(float(i))
        z = s2.z_score(s2.mean)
        assert z is not None
        assert math.isclose(z, 0.0, abs_tol=0.01)

    def test_serialization_roundtrip(self):
        s = WelfordState(count=100, mean=5.5, m2=250.0)
        d = s.to_dict()
        s2 = WelfordState.from_dict(d)
        assert s2.count == s.count
        assert s2.mean == s.mean
        assert s2.m2 == s.m2


# ---------------------------------------------------------------------------
# Tests: WelfordBaseline
# ---------------------------------------------------------------------------


class TestWelfordBaseline:
    def test_update_and_z_score(self):
        bl = WelfordBaseline(symbol="000001", metric="volume")
        # Feed enough samples to slot (Monday, 10:00 = d0_s1)
        for i in range(MIN_SAMPLES + 5):
            bl.update(0, 10, 0, 100.0 + i * 0.1)
        z = bl.z_score(0, 10, 0, 100.0)
        assert z is not None

    def test_outside_hours_ignored(self):
        bl = WelfordBaseline(symbol="000001", metric="volume")
        bl.update(0, 12, 0, 100.0)  # lunch break — ignored
        assert bl.segment_count == 0

    def test_weekend_ignored(self):
        bl = WelfordBaseline(symbol="000001", metric="volume")
        bl.update(5, 10, 0, 100.0)  # Saturday
        assert bl.segment_count == 0

    def test_different_segments_independent(self):
        bl = WelfordBaseline(symbol="000001", metric="volume")
        bl.update(0, 10, 0, 100.0)  # Monday 10:00
        bl.update(1, 14, 0, 200.0)  # Tuesday 14:00
        assert bl.segment_count == 2

    def test_redis_persistence(self):
        mock_r = MagicMock()
        mock_r.hgetall.return_value = {}
        bl = WelfordBaseline(symbol="000001", metric="volume", redis_client=mock_r)
        bl.update(0, 10, 0, 100.0)
        mock_r.hset.assert_called_once()
        key = mock_r.hset.call_args[0][0]
        assert "welford:000001:volume" == key

    def test_valid_segment_count(self):
        bl = WelfordBaseline(symbol="000001", metric="volume")
        # Not enough samples yet
        for i in range(MIN_SAMPLES - 1):
            bl.update(0, 10, 0, float(i))
        assert bl.valid_segment_count == 0

        # One more should make it valid
        bl.update(0, 10, 0, 50.0)
        assert bl.valid_segment_count == 1


# ---------------------------------------------------------------------------
# Tests: PriceSpikeDetector
# ---------------------------------------------------------------------------


class TestPriceSpikeDetector:
    def test_no_spike_insufficient_data(self):
        detector = PriceSpikeDetector()
        result = detector.check("000001", 10.0, 9.5, 0, 10, 0)
        assert result is None  # not enough baseline data

    def test_spike_detection(self):
        mock_bus = MagicMock()
        detector = PriceSpikeDetector(event_bus=mock_bus, z_threshold=2.0)

        # Build baseline with slightly varied returns to get nonzero variance
        for i in range(MIN_SAMPLES + 5):
            price = 10.0 + 0.01 * (i % 5)  # vary between 10.00 and 10.04
            detector.check("000001", price, 10.0, 0, 10, 0)

        # Clear cooldown for testing
        detector._cooldowns.clear()

        # Now inject a huge spike: +20% return
        result = detector.check("000001", 12.0, 10.0, 0, 10, 0)
        assert result is not None
        assert result["direction"] == "up"
        assert result["z_score"] > 2.0
        mock_bus.publish.assert_called_once()

    def test_cooldown_suppresses(self):
        detector = PriceSpikeDetector(z_threshold=0.0, cooldown_seconds=3600)

        # Build baseline with varied returns
        for i in range(MIN_SAMPLES + 5):
            price = 10.0 + 0.01 * (i % 5)
            detector.check("000001", price, 10.0, 0, 10, 0)

        detector._cooldowns.clear()

        # First spike — should trigger (z_threshold=0.0, any nonzero z passes)
        r1 = detector.check("000001", 12.0, 10.0, 0, 10, 0)
        # Second spike should be suppressed by cooldown
        r2 = detector.check("000001", 13.0, 10.0, 0, 10, 0)
        assert r1 is not None
        assert r2 is None  # cooldown

    def test_invalid_prices_ignored(self):
        detector = PriceSpikeDetector()
        assert detector.check("000001", 0, 10.0, 0, 10, 0) is None
        assert detector.check("000001", 10.0, 0, 0, 10, 0) is None
        assert detector.check("000001", -1, 10.0, 0, 10, 0) is None

    def test_check_batch(self):
        detector = PriceSpikeDetector()
        quotes = [
            {"symbol": "000001", "price": 10.0, "prev_close": 9.5},
            {"symbol": "000002", "price": 20.0, "prev_close": 19.0},
        ]
        results = detector.check_batch(quotes, 0, 10, 0)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Tests: VolumeAnomalyDetector
# ---------------------------------------------------------------------------


class TestVolumeAnomalyDetector:
    def test_no_anomaly_insufficient_data(self):
        detector = VolumeAnomalyDetector()
        result = detector.check("000001", 1000.0, 0, 10, 0)
        assert result is None

    def test_high_volume_anomaly(self):
        mock_bus = MagicMock()
        detector = VolumeAnomalyDetector(event_bus=mock_bus, z_threshold=2.0)

        # Build baseline: stable ~1000 volume
        for i in range(MIN_SAMPLES + 5):
            detector.check("000001", 1000.0 + i, 0, 10, 0)

        detector._cooldowns.clear()

        # Inject massive volume spike
        result = detector.check("000001", 100000.0, 0, 10, 0)
        assert result is not None
        assert result["anomaly_type"] == "high_volume"
        assert result["z_score"] > 2.0
        mock_bus.publish.assert_called_once()

    def test_low_volume_anomaly(self):
        detector = VolumeAnomalyDetector(z_threshold=2.0)

        # Build baseline with high volume
        for i in range(MIN_SAMPLES + 5):
            detector.check("000001", 10000.0 + i * 10, 0, 10, 0)

        detector._cooldowns.clear()

        # Inject extremely low volume
        result = detector.check("000001", 1.0, 0, 10, 0)
        assert result is not None
        assert result["anomaly_type"] == "low_volume"
        assert result["z_score"] < -2.0

    def test_negative_volume_ignored(self):
        detector = VolumeAnomalyDetector()
        assert detector.check("000001", -100, 0, 10, 0) is None

    def test_check_batch(self):
        detector = VolumeAnomalyDetector()
        bars = [
            {"symbol": "000001", "volume": 1000},
            {"symbol": "000002", "volume": 2000},
        ]
        results = detector.check_batch(bars, 0, 10, 0)
        assert isinstance(results, list)
