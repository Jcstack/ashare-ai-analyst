"""Tests for SymbolExtractor — regex, name lookup, index exclusion, and cache."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.intelligence_hub.symbol_extractor import SymbolExtractor


class TestRegexExtraction:
    """Strategy 1: regex-based stock code extraction."""

    def test_extract_shanghai_main(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        assert ext.extract("关注600036招商银行走势") == ["600036"]

    def test_extract_shenzhen_chinext(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        assert ext.extract("300750宁德时代大涨") == ["300750"]

    def test_extract_star_market(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        assert ext.extract("688981中芯国际") == ["688981"]

    def test_extract_multiple_codes(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        codes = ext.extract("600036涨停 300750跟涨")
        assert codes == ["300750", "600036"]

    def test_no_match(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        assert ext.extract("今日大盘震荡") == []

    def test_exclude_index_codes(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        # 000001 is 上证指数, should be excluded
        assert ext.extract("上证指数000001今日下跌") == []

    def test_exclude_all_common_indices(self) -> None:
        ext = SymbolExtractor(load_akshare=False)
        text = "399001 399006 000300 000016 000905 000688"
        assert ext.extract(text) == []


class TestNameExtraction:
    """Strategy 2: stock name lookup extraction."""

    def test_name_lookup(self) -> None:
        ext = SymbolExtractor(
            extra_names={"002594": "比亚迪", "600036": "招商银行"},
            load_akshare=False,
        )
        assert ext.extract("比亚迪新能源汽车销量创新高") == ["002594"]

    def test_name_lookup_multiple(self) -> None:
        ext = SymbolExtractor(
            extra_names={"002594": "比亚迪", "600036": "招商银行"},
            load_akshare=False,
        )
        codes = ext.extract("比亚迪与招商银行合作")
        assert codes == ["002594", "600036"]

    def test_short_name_excluded(self) -> None:
        """Names shorter than 2 chars should be ignored to avoid false positives."""
        ext = SymbolExtractor(
            extra_names={"000001": "A"},  # single char name
            load_akshare=False,
        )
        assert ext.extract("A股大涨") == []

    def test_combined_regex_and_name(self) -> None:
        ext = SymbolExtractor(
            extra_names={"002594": "比亚迪"},
            load_akshare=False,
        )
        codes = ext.extract("比亚迪002594与600036招商银行")
        assert codes == ["002594", "600036"]


class TestCache:
    """JSON cache save/load for offline fallback."""

    def test_save_and_load_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "stock_names_cache.json"
        names = {"600036": "招商银行", "002594": "比亚迪"}

        with patch("src.intelligence_hub.symbol_extractor._CACHE_PATH", cache_file):
            SymbolExtractor._save_cache(names)
            assert cache_file.exists()

            loaded = SymbolExtractor._load_cache()
            assert loaded == names

    def test_load_cache_missing_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "nonexistent.json"
        with patch("src.intelligence_hub.symbol_extractor._CACHE_PATH", cache_file):
            assert SymbolExtractor._load_cache() is None

    def test_load_cache_corrupt_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "bad.json"
        cache_file.write_text("not json{{{", encoding="utf-8")
        with patch("src.intelligence_hub.symbol_extractor._CACHE_PATH", cache_file):
            assert SymbolExtractor._load_cache() is None

    def test_load_cache_empty_dict(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "empty.json"
        cache_file.write_text("{}", encoding="utf-8")
        with patch("src.intelligence_hub.symbol_extractor._CACHE_PATH", cache_file):
            assert SymbolExtractor._load_cache() is None

    def _seed_cache(self, tmp_path: Path) -> Path:
        cache_file = tmp_path / "stock_names_cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"002594": "比亚迪"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return cache_file

    def test_akshare_exception_uses_cache(self, tmp_path: Path) -> None:
        """When the akshare call raises, fall back to cached names.

        The data source is mocked to raise so the test is deterministic and
        never touches the network (it previously relied on a real call failing,
        which made CI flaky when the source timed out instead of raising).
        """
        cache_file = self._seed_cache(tmp_path)
        with (
            patch("src.intelligence_hub.symbol_extractor._CACHE_PATH", cache_file),
            patch(
                "src.data.eastmoney_proxy.em_api_call",
                side_effect=ConnectionError("no network in test"),
            ),
        ):
            ext = SymbolExtractor(load_akshare=True)
            codes = ext.extract("比亚迪新能源汽车销量创新高")
            assert "002594" in codes

    def test_akshare_empty_result_uses_cache(self, tmp_path: Path) -> None:
        """A degraded source that returns an empty result (no exception) must
        still fall back to the cache — regression for the silent-empty path."""
        import pandas as pd

        cache_file = self._seed_cache(tmp_path)
        with (
            patch("src.intelligence_hub.symbol_extractor._CACHE_PATH", cache_file),
            patch(
                "src.data.eastmoney_proxy.em_api_call",
                return_value=pd.DataFrame(),
            ),
        ):
            ext = SymbolExtractor(load_akshare=True)
            codes = ext.extract("比亚迪新能源汽车销量创新高")
            assert "002594" in codes


class TestBuildExtraNames:
    """build_extra_names static method."""

    def test_from_watchlist_config(self) -> None:
        config = {
            "watchlist": [
                {"symbol": "600036", "name": "招商银行"},
                {"symbol": "002594", "name": "比亚迪"},
            ]
        }
        names = SymbolExtractor.build_extra_names(config)
        assert names == {"600036": "招商银行", "002594": "比亚迪"}

    def test_empty_config(self) -> None:
        assert SymbolExtractor.build_extra_names({}) == {}

    def test_missing_fields(self) -> None:
        config = {"watchlist": [{"symbol": "600036"}]}  # no name
        names = SymbolExtractor.build_extra_names(config)
        assert names == {}
