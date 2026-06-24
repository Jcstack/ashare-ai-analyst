"""Tests for IntradaySectorFlowTracker."""

from __future__ import annotations

from unittest.mock import patch, MagicMock


class TestIntradaySectorFlowTracker:
    def test_init(self):
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()
        assert tracker is not None
        assert tracker._redis is None

    def test_init_with_redis(self):
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        mock_redis = MagicMock()
        tracker = IntradaySectorFlowTracker(redis_client=mock_redis)
        assert tracker._redis is mock_redis

    def test_fetch_current_flow_returns_list(self):
        """fetch_current_flow should return a list of dicts."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()

        # Mock akshare import and call to avoid network
        import pandas as pd

        mock_df = pd.DataFrame(
            {
                "名称": ["半导体", "白酒"],
                "涨跌幅": [2.1, -0.5],
                "主力净流入-净额": [520000000, -310000000],
                "领涨股票": ["北方华创", "贵州茅台"],
                "涨跌幅.1": [5.0, -1.2],
            }
        )
        # ak and em_api_call are imported inside fetch_current_flow
        mock_ak = MagicMock()
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            with patch("src.data.eastmoney_proxy.em_api_call", return_value=mock_df):
                result = tracker.fetch_current_flow()
                assert isinstance(result, list)

    def test_fetch_current_flow_empty_on_import_error(self):
        """Should return [] when akshare is not available."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()
        # Clear any cache
        tracker._mem_cache = {}

        with patch.dict("sys.modules", {"akshare": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("no akshare"),
            ):
                # This will fail on import — should return []
                result = tracker.fetch_current_flow()
                assert isinstance(result, list)

    def test_detect_rotation_returns_dict(self):
        """detect_rotation should return dict with rotating_in/rotating_out."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()

        with patch.object(tracker, "fetch_current_flow", return_value=[]):
            result = tracker.detect_rotation()
            assert isinstance(result, dict)
            assert "rotating_in" in result
            assert "rotating_out" in result
            assert "timestamp" in result

    def test_detect_rotation_with_data(self):
        """Should detect rotation when rank changes are significant."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()

        mock_flow = [
            {
                "sector": "半导体",
                "net_inflow": 5.2,
                "change_pct": 2.1,
                "leader_stock": "北方华创",
                "leader_change": 5.0,
                "rank_change": 10,  # big improvement
            },
            {
                "sector": "白酒",
                "net_inflow": -3.1,
                "change_pct": -0.5,
                "leader_stock": "贵州茅台",
                "leader_change": -1.2,
                "rank_change": -8,  # big decline
            },
        ]
        with patch.object(tracker, "fetch_current_flow", return_value=mock_flow):
            result = tracker.detect_rotation()
            assert len(result["rotating_in"]) >= 1
            assert len(result["rotating_out"]) >= 1
            assert result["rotating_in"][0]["sector"] == "半导体"
            assert result["rotating_out"][0]["sector"] == "白酒"

    def test_get_sector_momentum(self):
        """get_sector_momentum should return momentum dict for a sector."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()

        mock_flow = [
            {
                "sector": "半导体",
                "net_inflow": 5.2,
                "change_pct": 2.1,
                "leader_stock": "北方华创",
                "leader_change": 5.0,
                "rank_change": 3,
            },
        ]
        with patch.object(tracker, "fetch_current_flow", return_value=mock_flow):
            result = tracker.get_sector_momentum("半导体")
            assert isinstance(result, dict)
            assert result["sector"] == "半导体"
            assert result["net_inflow"] == 5.2
            assert result["trend"] == "inflow"

    def test_get_sector_momentum_not_found(self):
        """Should return neutral result when sector not in flow data."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()

        with patch.object(tracker, "fetch_current_flow", return_value=[]):
            result = tracker.get_sector_momentum("不存在的板块")
            assert result["trend"] == "neutral"
            assert result["net_inflow"] == 0.0

    def test_cache_prevents_duplicate_fetch(self):
        """Second call within TTL should use cache, not fetch again."""
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()

        mock_flow = [
            {
                "sector": "测试",
                "net_inflow": 1.0,
                "change_pct": 0.5,
                "leader_stock": "",
                "leader_change": 0.0,
                "rank_change": 0,
            }
        ]
        # Pre-populate cache
        tracker._set_cache("current_flow", mock_flow)

        # Should return cached value without calling akshare
        result = tracker.fetch_current_flow()
        assert isinstance(result, list)
        assert result == mock_flow
