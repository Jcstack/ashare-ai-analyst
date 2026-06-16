"""Unit tests for SentinelCapture — LLM + NewsFetcher mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd


class TestSentinelCapture:
    """Test SentinelCapture with mocked dependencies."""

    def _make_capture(self, gateway=None, news_fetcher=None):
        from src.data.sentinel_capture import SentinelCapture

        return SentinelCapture(gateway=gateway, news_fetcher=news_fetcher)

    def test_capture_with_no_symbols_uses_defaults(self):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_stock_news.return_value = pd.DataFrame()
        mock_fetcher.fetch_market_anomalies.return_value = pd.DataFrame()
        mock_fetcher.fetch_hot_rank.return_value = pd.DataFrame()

        mock_gateway = MagicMock()
        mock_gateway.complete.return_value = MagicMock(
            content='{"sentiment": {}, "summary": "test"}'
        )

        capture = self._make_capture(gateway=mock_gateway, news_fetcher=mock_fetcher)

        with patch.object(capture, "_write_output"):
            result = capture.capture()

        assert "timestamp" in result
        assert "fallback_used" in result

    def test_capture_with_gemini_failure_sets_fallback(self):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_stock_news.return_value = pd.DataFrame()
        mock_fetcher.fetch_market_anomalies.return_value = pd.DataFrame()
        mock_fetcher.fetch_hot_rank.return_value = pd.DataFrame()

        mock_gateway = MagicMock()
        mock_gateway.complete.side_effect = TimeoutError("Gemini timeout")

        capture = self._make_capture(gateway=mock_gateway, news_fetcher=mock_fetcher)

        with patch.object(capture, "_write_output"):
            result = capture.capture(["600519"])

        assert result["fallback_used"] is True

    def test_collect_raw_data_fetches_news(self):
        mock_fetcher = MagicMock()
        news_df = pd.DataFrame([{"title": "Test news", "source": "eastmoney"}])
        mock_fetcher.fetch_stock_news.return_value = news_df
        mock_fetcher.fetch_market_anomalies.return_value = pd.DataFrame()
        mock_fetcher.fetch_hot_rank.return_value = pd.DataFrame()

        capture = self._make_capture(news_fetcher=mock_fetcher)
        raw = capture._collect_raw_data(["600519"])

        assert "600519" in raw["news"]
        assert len(raw["news"]["600519"]) == 1
        mock_fetcher.fetch_stock_news.assert_called_once_with("600519")

    def test_collect_raw_data_handles_news_failure(self):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_stock_news.side_effect = RuntimeError("fetch fail")
        mock_fetcher.fetch_market_anomalies.return_value = pd.DataFrame()
        mock_fetcher.fetch_hot_rank.return_value = pd.DataFrame()

        capture = self._make_capture(news_fetcher=mock_fetcher)
        raw = capture._collect_raw_data(["600519"])

        assert raw["news"]["600519"] == []

    def test_parse_sentiment_response_valid_json(self):
        capture = self._make_capture()
        content = json.dumps(
            {
                "sentiment": {"600519": {"score": 0.72, "label": "偏多"}},
                "summary": "市场情绪偏乐观",
            }
        )
        result = capture._parse_sentiment_response(["600519"], content)

        assert result["fallback_used"] is False
        assert "600519" in result["sentiment"]
        assert result["sentiment"]["600519"]["score"] == 0.72

    def test_parse_sentiment_response_invalid_json(self):
        capture = self._make_capture()
        result = capture._parse_sentiment_response(["600519"], "not valid json {")

        assert result["fallback_used"] is True

    def test_parse_sentiment_response_markdown_wrapped(self):
        capture = self._make_capture()
        content = '```json\n{"sentiment": {}, "summary": "ok"}\n```'
        result = capture._parse_sentiment_response(["600519"], content)

        assert result["fallback_used"] is False

    def test_write_output(self, tmp_path):
        capture = self._make_capture()
        # Use absolute path to avoid get_project_root resolution
        out_file = tmp_path / "gemini_sense.json"
        capture._config["output_path"] = str(out_file)

        output = {
            "timestamp": "2026-03-01T00:00:00+00:00",
            "symbols": ["600519"],
            "fallback_used": False,
            "sentiment": {},
        }

        capture._write_output(output)

        written = json.loads(out_file.read_text())
        assert written["symbols"] == ["600519"]
