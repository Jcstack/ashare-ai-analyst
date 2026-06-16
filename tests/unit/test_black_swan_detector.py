"""Tests for BlackSwanDetector."""

import pytest

from src.intelligence.black_swan_detector import BlackSwanDetector


@pytest.fixture
def detector():
    return BlackSwanDetector(
        config={
            "thresholds": {
                "vix": {"extreme": 30.0, "elevated": 25.0},
                "index_drop_pct": {"extreme": -3.0, "elevated": -2.0},
                "usd_index_pct": {"extreme": 1.5, "elevated": 1.0},
                "oil_pct": {"extreme": 5.0, "elevated": 3.0},
                "gold_pct": {"extreme": 3.0, "elevated": 2.0},
                "northbound_outflow_yi": {"extreme": -100.0, "elevated": -50.0},
                "limit_down_ratio": {"extreme": 3.0},
            },
            "multi_indicator_escalation": 3,
            "cooldown_seconds": 0,  # disable cooldown for tests
        }
    )


class TestNoAlert:
    def test_empty_data(self, detector):
        assert detector.scan({}) == []

    def test_normal_market(self, detector):
        alerts = detector.scan(
            {
                "vix": 15.0,
                "gold_pct": 0.5,
                "oil_pct": 1.0,
                "usd_index_pct": 0.3,
                "index_changes": {"标普500": 0.5},
            }
        )
        assert alerts == []


class TestExtremeAlerts:
    def test_vix_extreme(self, detector):
        alerts = detector.scan({"vix": 35.0})
        assert len(alerts) == 1
        assert alerts[0].level == "EXTREME"
        assert any(b.indicator == "vix" for b in alerts[0].triggered_indicators)

    def test_index_crash(self, detector):
        alerts = detector.scan(
            {
                "index_changes": {"上证综指": -4.0},
            }
        )
        assert len(alerts) == 1
        assert alerts[0].level == "EXTREME"

    def test_oil_spike(self, detector):
        alerts = detector.scan({"oil_pct": 8.0})
        assert len(alerts) == 1
        assert alerts[0].level == "EXTREME"

    def test_northbound_massive_outflow(self, detector):
        alerts = detector.scan({"northbound_flow_yi": -150.0})
        assert len(alerts) == 1

    def test_limit_down_ratio(self, detector):
        alerts = detector.scan(
            {
                "limit_down_count": 60,
                "limit_up_count": 10,
            }
        )
        assert len(alerts) == 1
        assert alerts[0].level == "EXTREME"


class TestElevatedAlerts:
    def test_single_elevated_no_alert(self, detector):
        """Single elevated indicator below escalation threshold -> no alert."""
        alerts = detector.scan({"vix": 27.0})
        assert alerts == []  # logged but not alerted

    def test_two_elevated_no_escalation(self, detector):
        """Two elevated indicators below escalation threshold of 3."""
        alerts = detector.scan(
            {
                "vix": 27.0,
                "oil_pct": 4.0,
            }
        )
        assert alerts == []

    def test_three_elevated_escalates(self, detector):
        """Three elevated indicators -> multi-indicator EXTREME."""
        alerts = detector.scan(
            {
                "vix": 27.0,
                "oil_pct": 4.0,
                "gold_pct": 2.5,
            }
        )
        assert len(alerts) == 1
        assert alerts[0].level == "EXTREME"
        assert alerts[0].is_multi_indicator


class TestMixed:
    def test_extreme_plus_elevated(self, detector):
        """EXTREME + some ELEVATED -> only the EXTREME alert."""
        alerts = detector.scan(
            {
                "vix": 35.0,  # EXTREME
                "oil_pct": 4.0,  # ELEVATED
            }
        )
        assert len(alerts) == 1
        assert alerts[0].level == "EXTREME"
        assert not alerts[0].is_multi_indicator


class TestSnapshotConversion:
    def test_build_scan_input(self, detector):
        snapshot = {
            "volatility": [{"symbol": "^VIX", "price": 28.0}],
            "commodities": [
                {"symbol": "GC=F", "pct_change": 2.5},
                {"symbol": "CL=F", "pct_change": -1.2},
            ],
            "currencies": [
                {"symbol": "DX-Y.NYB", "pct_change": 0.8},
            ],
            "indices": [
                {"symbol": "^GSPC", "name": "标普500", "pct_change": -0.5},
            ],
        }
        result = detector.build_scan_input_from_snapshot(snapshot)
        assert result["vix"] == 28.0
        assert result["gold_pct"] == 2.5
        assert result["oil_pct"] == -1.2
        assert result["usd_index_pct"] == 0.8
        assert "标普500" in result["index_changes"]


class TestCooldown:
    def test_cooldown_prevents_duplicate(self):
        det = BlackSwanDetector(
            config={
                "cooldown_seconds": 9999,  # long cooldown
            }
        )
        alerts1 = det.scan({"vix": 35.0})
        assert len(alerts1) == 1
        alerts2 = det.scan({"vix": 35.0})
        assert len(alerts2) == 0  # cooled down


class TestSerialization:
    def test_alert_to_dict(self, detector):
        alerts = detector.scan({"vix": 35.0})
        d = alerts[0].to_dict()
        assert d["level"] == "EXTREME"
        assert "alert_id" in d
        assert len(d["triggered_indicators"]) > 0
        assert "indicator" in d["triggered_indicators"][0]
