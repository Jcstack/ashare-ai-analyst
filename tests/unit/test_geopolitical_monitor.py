"""Tests for GeopoliticalMonitor and GeopoliticalEvent."""

from __future__ import annotations

from unittest.mock import patch

from src.data.geopolitical_monitor import (
    GeopoliticalEvent,
    GeopoliticalMonitor,
)


class TestGeopoliticalEvent:
    def test_to_dict(self):
        ev = GeopoliticalEvent(
            event_type="conflict",
            region="中东",
            severity="watch",
            keywords_matched=["冲突"],
            source_text="中东地区冲突升级",
            timestamp="2026-03-07T10:00:00",
        )
        d = ev.to_dict()
        assert d["event_type"] == "conflict"
        assert d["region"] == "中东"
        assert d["severity"] == "watch"
        assert d["keywords_matched"] == ["冲突"]
        assert d["source_text"] == "中东地区冲突升级"
        assert d["timestamp"] == "2026-03-07T10:00:00"

    def test_to_dict_keys(self):
        ev = GeopoliticalEvent(
            event_type="sanctions",
            region="俄乌",
            severity="elevated",
            keywords_matched=["制裁", "禁运"],
            source_text="新一轮制裁",
            timestamp="2026-03-07T12:00:00",
        )
        expected_keys = {
            "event_type",
            "region",
            "severity",
            "keywords_matched",
            "source_text",
            "timestamp",
        }
        assert set(ev.to_dict().keys()) == expected_keys


class TestGetSeverity:
    def test_watch_single_match(self):
        assert GeopoliticalMonitor.get_severity(1) == "watch"

    def test_elevated_two_matches(self):
        assert GeopoliticalMonitor.get_severity(2) == "elevated"

    def test_critical_three_matches(self):
        assert GeopoliticalMonitor.get_severity(3) == "critical"

    def test_critical_many_matches(self):
        assert GeopoliticalMonitor.get_severity(10) == "critical"

    def test_watch_zero_matches(self):
        # Edge case: 0 matches still returns "watch"
        assert GeopoliticalMonitor.get_severity(0) == "watch"


class TestGetRegion:
    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_detect_middle_east(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.get_region("伊朗局势紧张") == "中东"

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_detect_russia_ukraine(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.get_region("俄罗斯与乌克兰冲突") == "俄乌"

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_detect_unknown(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.get_region("国际市场波动加大") == "未知"

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_detect_taiwan_strait(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.get_region("台海两岸关系") == "台海"


class TestScanText:
    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_no_match_returns_none(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.scan_text("今天天气不错") is None

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_empty_text_returns_none(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.scan_text("") is None

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_none_text_returns_none(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.scan_text(None) is None

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_single_conflict_keyword(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        ev = monitor.scan_text("中东地区冲突升级")
        assert ev is not None
        assert ev.event_type == "conflict"
        assert "冲突" in ev.keywords_matched
        assert ev.severity == "watch"
        assert ev.region == "中东"

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_multiple_keywords_elevated(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        ev = monitor.scan_text("军事冲突导致袭击事件")
        assert ev is not None
        assert len(ev.keywords_matched) >= 2

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_sanctions_type(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        ev = monitor.scan_text("美国宣布新一轮制裁措施")
        assert ev is not None
        assert ev.event_type == "sanctions"
        assert "制裁" in ev.keywords_matched

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_source_text_truncated(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        long_text = "冲突" + "x" * 1000
        ev = monitor.scan_text(long_text)
        assert ev is not None
        assert len(ev.source_text) <= 500

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_critical_severity_many_keywords(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        # Text containing 3+ keywords → critical
        ev = monitor.scan_text("战争冲突军事袭击入侵以色列")
        assert ev is not None
        assert ev.severity == "critical"
        assert len(ev.keywords_matched) >= 3


class TestScanBatch:
    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_batch_with_mixed_items(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        items = [
            {"text": "今天天气不错"},
            {"text": "中东地区冲突升级"},
            {"title": "新一轮制裁"},
        ]
        events = monitor.scan_batch(items)
        assert len(events) == 2

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_batch_empty_list(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        assert monitor.scan_batch([]) == []

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_batch_no_matches(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        items = [{"text": "正常新闻"}, {"title": "经济数据"}]
        assert monitor.scan_batch(items) == []

    @patch("src.data.geopolitical_monitor.load_config", return_value={})
    def test_batch_uses_title_fallback(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        items = [{"title": "军事演习消息"}]
        events = monitor.scan_batch(items)
        assert len(events) == 1
        assert events[0].event_type == "conflict"


class TestConfigLoading:
    @patch(
        "src.data.geopolitical_monitor.load_config",
        return_value={
            "geopolitical_keywords": {
                "conflict": ["war", "attack"],
                "trade": ["tariff"],
                "regions": ["Europe"],
            }
        },
    )
    def test_custom_config_keywords(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        # Custom keywords should work
        ev = monitor.scan_text("The war caused an attack")
        assert ev is not None
        assert "war" in ev.keywords_matched
        assert "attack" in ev.keywords_matched

    @patch(
        "src.data.geopolitical_monitor.load_config",
        side_effect=Exception("config not found"),
    )
    def test_fallback_on_config_error(self, _mock_cfg):
        monitor = GeopoliticalMonitor()
        # Should still work with defaults
        ev = monitor.scan_text("军事冲突")
        assert ev is not None
