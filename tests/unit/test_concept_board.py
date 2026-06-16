"""Tests for ConceptBoardService."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.concept_board import (
    ConceptBoardItem,
    ConceptBoardService,
)


@pytest.fixture
def svc():
    return ConceptBoardService()


# ---------------------------------------------------------------------------
# fetch_concept_list
# ---------------------------------------------------------------------------


@patch("akshare.stock_board_concept_name_em")
def test_fetch_concept_list_success(mock_fn, svc):
    mock_fn.return_value = pd.DataFrame(
        {
            "板块代码": ["BK0501", "BK0896"],
            "板块名称": ["5G概念", "文生视频"],
            "涨跌幅": [1.5, 5.12],
            "上涨家数": [18, 25],
            "下跌家数": [5, 3],
            "总市值": [5e9, 1.2e10],
        }
    )

    items = svc.fetch_concept_list()
    assert len(items) == 2
    assert items[0].code == "BK0501"
    assert items[0].name == "5G概念"
    assert items[0].pct_change == 1.5
    assert items[1].up_count == 25


@patch.object(ConceptBoardService, "_fetch_concept_list_em_direct", return_value=[])
@patch("akshare.stock_board_concept_name_em")
def test_fetch_concept_list_empty(mock_fn, mock_fallback, svc):
    mock_fn.return_value = pd.DataFrame()
    assert svc.fetch_concept_list() == []


@patch.object(ConceptBoardService, "_fetch_concept_list_em_direct", return_value=[])
@patch("akshare.stock_board_concept_name_em")
def test_fetch_concept_list_error(mock_fn, mock_fallback, svc):
    mock_fn.side_effect = Exception("Network error")
    assert svc.fetch_concept_list() == []


@patch("akshare.stock_board_concept_name_em")
def test_fetch_concept_list_cached(mock_fn, svc):
    mock_fn.return_value = pd.DataFrame(
        {
            "板块代码": ["BK0501"],
            "板块名称": ["5G概念"],
            "涨跌幅": [1.5],
            "上涨家数": [18],
            "下跌家数": [5],
            "总市值": [5e9],
        }
    )
    svc.fetch_concept_list()
    svc.fetch_concept_list()  # Should hit cache
    assert mock_fn.call_count == 1


# ---------------------------------------------------------------------------
# fetch_concept_constituents
# ---------------------------------------------------------------------------


@patch("akshare.stock_board_concept_cons_em")
def test_fetch_constituents_success(mock_fn, svc):
    mock_fn.return_value = pd.DataFrame(
        {
            "代码": ["001330", "600977"],
            "名称": ["博纳影业", "中国电影"],
            "最新价": [8.5, 12.3],
            "涨跌幅": [7.83, 3.2],
            "成交额": [5e8, 8e8],
            "振幅": [9.1, 5.2],
        }
    )

    items = svc.fetch_concept_constituents("BK0501")
    assert len(items) == 2
    assert items[0].symbol == "001330"
    assert items[0].pct_change == 7.83


@patch("akshare.stock_board_concept_cons_em")
def test_fetch_constituents_error(mock_fn, svc):
    mock_fn.side_effect = Exception("fail")
    assert svc.fetch_concept_constituents("BK0501") == []


# ---------------------------------------------------------------------------
# fetch_stock_concepts (reverse lookup)
# ---------------------------------------------------------------------------


@patch.object(ConceptBoardService, "_fetch_industry", return_value="文化传媒")
@patch.object(
    ConceptBoardService,
    "_fetch_core_conception",
    return_value=[
        # CoreConception API returns numeric codes, not BK-prefixed
        {"name": "影视院线", "code": "1222"},
        {"name": "文生视频", "code": "847"},
        {"name": "短剧", "code": ""},
    ],
)
@patch.object(
    ConceptBoardService,
    "fetch_concept_list",
    return_value=[
        # AKShare concept list uses BK-prefixed codes
        ConceptBoardItem(
            code="BK0501",
            name="影视院线",
            pct_change=3.21,
            up_count=18,
            down_count=5,
            amount=5e9,
        ),
        ConceptBoardItem(
            code="BK0896",
            name="文生视频",
            pct_change=5.12,
            up_count=25,
            down_count=3,
            amount=1.2e10,
        ),
    ],
)
@patch.object(ConceptBoardService, "fetch_industry_list", return_value=[])
def test_fetch_stock_concepts(mock_ind_list, mock_list, mock_core, mock_industry, svc):
    """Name-based join should work when codes differ between APIs."""
    result = svc.fetch_stock_concepts("001330")

    assert result.symbol == "001330"
    assert result.industry == "文化传媒"
    assert len(result.concepts) == 3
    names = [c.name for c in result.concepts]
    assert "影视院线" in names
    assert "文生视频" in names
    assert "短剧" in names

    # Verify matched concepts got live performance data via name-based join
    matched = {c.name: c for c in result.concepts}
    assert matched["影视院线"].pct_change == 3.21
    assert matched["文生视频"].up_count == 25
    # Unmatched concept should have zero defaults
    assert matched["短剧"].pct_change == 0.0


@patch.object(ConceptBoardService, "_fetch_industry", return_value="")
@patch.object(ConceptBoardService, "_fetch_core_conception", return_value=[])
@patch.object(ConceptBoardService, "fetch_industry_list", return_value=[])
def test_fetch_stock_concepts_empty(mock_ind_list, mock_core, mock_industry, svc):
    result = svc.fetch_stock_concepts("999999")
    assert result.concepts == []


# ---------------------------------------------------------------------------
# fetch_concept_history
# ---------------------------------------------------------------------------


@patch("akshare.stock_board_concept_hist_em")
def test_fetch_history_success(mock_fn, svc):
    mock_fn.return_value = pd.DataFrame(
        {
            "日期": ["2026-02-12", "2026-02-13"],
            "开盘": [100.0, 101.0],
            "收盘": [101.0, 103.0],
            "最高": [102.0, 104.0],
            "最低": [99.0, 100.5],
            "成交量": [1e6, 1.2e6],
            "成交额": [1e8, 1.3e8],
            "涨跌幅": [1.0, 1.98],
        }
    )
    records = svc.fetch_concept_history("BK0501", "daily", 60)
    assert len(records) == 2
    assert records[0]["date"] == "2026-02-12"
    assert records[1]["pct_change"] == 1.98


@patch("akshare.stock_board_concept_hist_em")
def test_fetch_history_error(mock_fn, svc):
    mock_fn.side_effect = Exception("fail")
    assert svc.fetch_concept_history("BK0501") == []


# ---------------------------------------------------------------------------
# _fetch_core_conception (HTTP)
# ---------------------------------------------------------------------------


def test_core_conception_sz_prefix(svc):
    """SZ market prefix for codes not starting with 6/9; dict response format."""
    with patch.object(svc, "_get_http_session") as mock_sess:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ssbk": [
                {"BOARD_NAME": "影视院线", "BOARD_CODE": "BK0501", "IS_PRECISE": "1"},
                {"BOARD_NAME": "文生视频", "BOARD_CODE": "BK0896", "IS_PRECISE": "1"},
            ],
            "hxtc": [],
        }
        mock_resp.raise_for_status.return_value = None
        mock_sess.return_value.get.return_value = mock_resp

        result = svc._fetch_core_conception("001330")
        assert result == [
            {"name": "影视院线", "code": "BK0501"},
            {"name": "文生视频", "code": "BK0896"},
        ]
        call_url = mock_sess.return_value.get.call_args[0][0]
        assert "SZ001330" in call_url


def test_core_conception_sh_prefix(svc):
    """SH market prefix for codes starting with 6; dict response format."""
    with patch.object(svc, "_get_http_session") as mock_sess:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ssbk": [{"BOARD_NAME": "银行", "BOARD_CODE": "BK0475", "IS_PRECISE": "1"}],
            "hxtc": [],
        }
        mock_resp.raise_for_status.return_value = None
        mock_sess.return_value.get.return_value = mock_resp

        result = svc._fetch_core_conception("601398")
        assert result == [{"name": "银行", "code": "BK0475"}]
        call_url = mock_sess.return_value.get.call_args[0][0]
        assert "SH601398" in call_url


def test_core_conception_error(svc):
    with patch.object(svc, "_get_http_session") as mock_sess:
        mock_sess.return_value.get.side_effect = Exception("timeout")
        assert svc._fetch_core_conception("001330") == []


def test_core_conception_filters_imprecise(svc):
    """IS_PRECISE='0' entries should be filtered; None/missing IS_PRECISE kept."""
    with patch.object(svc, "_get_http_session") as mock_sess:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ssbk": [
                {"BOARD_NAME": "影视院线", "BOARD_CODE": "BK0501", "IS_PRECISE": "1"},
                {"BOARD_NAME": "传媒", "BOARD_CODE": "BK9901", "IS_PRECISE": "0"},
                {
                    "BOARD_NAME": "影视动漫制作",
                    "BOARD_CODE": "BK0502",
                },  # missing IS_PRECISE → kept
            ],
            "hxtc": [],
        }
        mock_resp.raise_for_status.return_value = None
        mock_sess.return_value.get.return_value = mock_resp

        result = svc._fetch_core_conception("001330")
        assert result == [
            {"name": "影视院线", "code": "BK0501"},
            {"name": "影视动漫制作", "code": "BK0502"},
        ]


def test_core_conception_legacy_list_format(svc):
    """Legacy list format should still work for backward compatibility."""
    with patch.object(svc, "_get_http_session") as mock_sess:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"BOARD_NAME": "银行", "BOARD_CODE": "BK0475", "IS_PRECISE": "1"},
            {
                "BOARD_NAME": "西部大开发",
                "BOARD_CODE": "BK0476",
            },  # No IS_PRECISE → kept
            {"BOARD_NAME": "深股通"},  # No IS_PRECISE, but noise name → filtered
        ]
        mock_resp.raise_for_status.return_value = None
        mock_sess.return_value.get.return_value = mock_resp

        result = svc._fetch_core_conception("601398")
        # IS_PRECISE="1" kept; missing IS_PRECISE kept (unless noise name)
        assert result == [
            {"name": "银行", "code": "BK0475"},
            {"name": "西部大开发", "code": "BK0476"},
        ]


def test_core_conception_filters_noise_names(svc):
    """Noise concept names (昨日高振幅 etc.) should be filtered regardless of IS_PRECISE."""
    with patch.object(svc, "_get_http_session") as mock_sess:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ssbk": [
                {"BOARD_NAME": "AIGC概念", "BOARD_CODE": "BK1000", "IS_PRECISE": "1"},
                {"BOARD_NAME": "昨日高振幅", "BOARD_CODE": "BK9001"},
                {"BOARD_NAME": "昨日高换手", "BOARD_CODE": "BK9002", "IS_PRECISE": "1"},
                {"BOARD_NAME": "融资融券", "BOARD_CODE": "BK9003"},
                {"BOARD_NAME": "MSCI中国", "BOARD_CODE": "BK9004"},
            ],
            "hxtc": [],
        }
        mock_resp.raise_for_status.return_value = None
        mock_sess.return_value.get.return_value = mock_resp

        result = svc._fetch_core_conception("001330")
        assert result == [{"name": "AIGC概念", "code": "BK1000"}]
