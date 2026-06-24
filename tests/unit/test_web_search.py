"""Unit tests for WebSearchService."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from src.web.services.web_search_service import WebSearchService


def _make_mock_ddgs(text_results=None, news_results=None, text_side_effect=None):
    """Create a mock DDGS context manager with given results."""
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    if text_side_effect:
        mock_instance.text.side_effect = text_side_effect
    else:
        mock_instance.text.return_value = text_results or []

    mock_instance.news.return_value = news_results or []

    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


def _patch_ddgs(mock_cls):
    """Patch sys.modules so `from ddgs import DDGS` resolves."""
    fake_module = MagicMock()
    fake_module.DDGS = mock_cls
    return patch.dict(sys.modules, {"ddgs": fake_module})


class TestWebSearchService:
    """Tests for WebSearchService."""

    def setup_method(self):
        self.svc = WebSearchService()

    # ------------------------------------------------------------------
    # Basic search (text)
    # ------------------------------------------------------------------

    def test_text_search_returns_results(self):
        """Text search returns formatted results."""
        mock_cls, mock_inst = _make_mock_ddgs(
            text_results=[
                {
                    "title": "博纳影业票房大涨",
                    "body": "博纳影业出品的电影票房突破10亿",
                    "href": "https://example.com/1",
                },
                {
                    "title": "影视板块异动",
                    "body": "影视板块集体拉升",
                    "href": "https://example.com/2",
                },
            ]
        )

        with _patch_ddgs(mock_cls):
            result = self.svc.search("博纳影业 票房")

        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "博纳影业票房大涨"
        assert result["results"][0]["snippet"] == "博纳影业出品的电影票房突破10亿"
        assert result["results"][0]["url"] == "https://example.com/1"
        assert result["type"] == "text"

    # ------------------------------------------------------------------
    # News search
    # ------------------------------------------------------------------

    def test_news_search_uses_news_method(self):
        """News search calls ddgs.news() instead of ddgs.text()."""
        mock_cls, mock_inst = _make_mock_ddgs(
            news_results=[
                {
                    "title": "宁德时代发布新技术",
                    "body": "新一代电池技术发布",
                    "url": "https://example.com/3",
                    "date": "2026-02-23",
                },
            ]
        )

        with _patch_ddgs(mock_cls):
            result = self.svc.search("宁德时代", search_type="news")

        assert result["type"] == "news"
        assert len(result["results"]) == 1
        assert result["results"][0]["date"] == "2026-02-23"
        mock_inst.news.assert_called_once()
        mock_inst.text.assert_not_called()

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def test_rate_limit_min_interval(self):
        """Calls within the minimum interval are rejected."""
        allowed, _ = self.svc._check_rate_limit()
        assert allowed is True
        # Immediate second call should fail (< 2s interval)
        allowed, cooldown = self.svc._check_rate_limit()
        assert allowed is False
        assert cooldown > 0

    def test_rate_limit_window_exhaustion(self):
        """Exceeding max calls within the window is rejected."""
        for _ in range(10):
            self.svc._last_call = 0.0  # Reset interval guard
            allowed, _ = self.svc._check_rate_limit()
            assert allowed is True

        # 11th call should be rejected (window full)
        self.svc._last_call = 0.0
        allowed, cooldown = self.svc._check_rate_limit()
        assert allowed is False
        assert cooldown > 0

    def test_rate_limit_returns_error_dict(self):
        """Service returns error dict when rate limited."""
        for _ in range(10):
            self.svc._last_call = 0.0
            self.svc._check_rate_limit()

        result = self.svc.search("test query")
        assert "error" in result
        assert "频率超限" in result["error"]

    # ------------------------------------------------------------------
    # ImportError fallback
    # ------------------------------------------------------------------

    def test_import_error_graceful_degradation(self):
        """Returns error dict when all search backends are unavailable.

        With the ddgs module removed, ``from ddgs import DDGS`` fails and the
        DDGS backend degrades to ``None``; SearXNG/Tavily are also unreachable
        in the test environment, so every backend fails. The service must
        return the graceful-degradation error dict rather than raising.
        """
        # Remove the module so `from ddgs import DDGS` fails
        with patch.dict(sys.modules, {"ddgs": None}):
            result = self.svc.search("test query")

        assert "error" in result
        assert "所有搜索引擎均不可用" in result["error"]

    # ------------------------------------------------------------------
    # Search failure
    # ------------------------------------------------------------------

    def test_search_exception_returns_error(self):
        """Search exceptions are caught and surfaced as an error dict.

        A backend that raises (here DDGS raising on ``text()``) must be caught
        and degrade to ``None`` rather than propagating. With no other backend
        reachable in the test environment, ``search`` returns the
        graceful-degradation error dict instead of raising.
        """
        mock_cls, _ = _make_mock_ddgs(text_side_effect=RuntimeError("Network timeout"))

        with _patch_ddgs(mock_cls):
            result = self.svc.search("test query")

        assert "error" in result
        assert "所有搜索引擎均不可用" in result["error"]

    # ------------------------------------------------------------------
    # max_results cap
    # ------------------------------------------------------------------

    def test_max_results_capped_at_10(self):
        """max_results is capped at 10 even if a larger value is passed."""
        mock_cls, mock_inst = _make_mock_ddgs(text_results=[])

        with _patch_ddgs(mock_cls):
            self.svc.search("test", max_results=50)

        call_kwargs = mock_inst.text.call_args
        assert call_kwargs.kwargs.get("max_results") == 10
