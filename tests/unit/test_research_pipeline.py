"""Unit tests for research pipeline Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestResearchPipelineTasks:
    """Test Celery research tasks with mocked dependencies."""

    @patch("openclaw.tasks.research_pipeline._should_execute", return_value=False)
    def test_sentinel_capture_skipped_by_timeline(self, mock_exec):
        from openclaw.tasks.research_pipeline import task_sentinel_capture

        result = task_sentinel_capture.apply().get()
        assert result["status"] == "skipped"

    @patch("openclaw.tasks.research_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.research_pipeline._get_redis")
    @patch("src.data.sentinel_capture.SentinelCapture")
    def test_sentinel_capture_success(self, mock_cls, mock_redis, mock_exec):
        mock_r = MagicMock()
        mock_redis.return_value = mock_r

        mock_capture = MagicMock()
        mock_capture.capture.return_value = {
            "symbols": ["600519"],
            "fallback_used": False,
        }
        mock_cls.return_value = mock_capture

        from openclaw.tasks.research_pipeline import task_sentinel_capture

        result = task_sentinel_capture.apply().get()

        assert result["status"] == "ok"
        assert result["symbols"] == 1
        assert result["fallback_used"] is False

    @patch("openclaw.tasks.research_pipeline._should_execute", return_value=False)
    def test_research_aggregate_skipped_by_timeline(self, mock_exec):
        from openclaw.tasks.research_pipeline import task_research_aggregate

        result = task_research_aggregate.apply().get()
        assert result["status"] == "skipped"

    @patch("openclaw.tasks.research_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.research_pipeline._get_redis")
    @patch("openclaw.tasks.research_pipeline.load_config")
    @patch("scripts.data_aggregator.DataAggregator")
    def test_research_aggregate_success(
        self, mock_agg_cls, mock_config, mock_redis, mock_exec
    ):
        mock_config.return_value = {
            "orchestration": {"default_symbols": ["600519"]},
        }
        mock_r = MagicMock()
        mock_redis.return_value = mock_r

        mock_aggregator = MagicMock()
        mock_aggregator.aggregate.return_value = [
            {"symbol": "600519", "fusion": {"signal": "看多"}},
        ]
        mock_agg_cls.return_value = mock_aggregator

        from openclaw.tasks.research_pipeline import task_research_aggregate

        result = task_research_aggregate.apply().get()

        assert result["status"] == "ok"
        assert result["signals"] == 1

    @patch("openclaw.tasks.research_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.research_pipeline.load_config")
    def test_research_aggregate_no_symbols(self, mock_config, mock_exec):
        mock_config.return_value = {"orchestration": {"default_symbols": []}}

        from openclaw.tasks.research_pipeline import task_research_aggregate

        result = task_research_aggregate.apply().get()

        assert result["status"] == "ok"
        assert result["signals"] == 0
