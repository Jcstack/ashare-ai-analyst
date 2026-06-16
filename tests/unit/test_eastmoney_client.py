"""Tests for the self-contained EastMoney client (replaces akshare-proxy-patch)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data.eastmoney_client import (
    EastMoneyClient,
    _safe_float,
    _safe_str,
    get_eastmoney_client,
    init_eastmoney_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spot_page(records: list[dict], total: int = 0) -> dict:
    """Build a fake push2 API response."""
    return {
        "data": {
            "total": total or len(records),
            "diff": records,
        }
    }


def _make_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# Unit: helpers
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_normal(self):
        assert _safe_float(1.23) == 1.23

    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_string(self):
        assert _safe_float("3.14") == 3.14

    def test_dash(self):
        assert _safe_float("-") is None

    def test_none(self):
        assert _safe_float(None) is None

    def test_empty(self):
        assert _safe_float("") is None

    def test_invalid(self):
        assert _safe_float("abc") is None


class TestSafeStr:
    def test_normal(self):
        assert _safe_str("hello") == "hello"

    def test_dash(self):
        assert _safe_str("-") == ""

    def test_none(self):
        assert _safe_str(None) == ""

    def test_number(self):
        assert _safe_str(123) == "123"


# ---------------------------------------------------------------------------
# Unit: EastMoneyClient
# ---------------------------------------------------------------------------


class TestEastMoneyClient:
    def test_direct_mode_success(self):
        """Direct request succeeds → returns data, marks direct_ok."""
        client = EastMoneyClient(mode="direct")
        mock_session = MagicMock()
        page_data = _make_spot_page(
            [
                {
                    "f12": "600519",
                    "f14": "贵州茅台",
                    "f2": 1688.0,
                    "f3": 1.23,
                    "f100": "酿酒行业",
                }
            ],
            total=1,
        )
        mock_session.get.return_value = _make_response(page_data)
        client._session = mock_session

        result = client.fetch_spot()
        assert len(result) == 1
        assert result[0]["symbol"] == "600519"
        assert result[0]["sector"] == "酿酒行业"
        assert client._direct_ok is True

    def test_gateway_fallback_on_direct_failure(self):
        """Direct fails → auto-switches to gateway with auth."""
        client = EastMoneyClient(mode="auto", token="test-token", gateway="1.2.3.4")
        mock_session = MagicMock()

        auth_data = {
            "proxy": "http://user:pass@proxy:8080",
            "ua": "TestUA",
            "nid18": "abc",
            "nid18_create_time": "123",
        }
        page_data = _make_spot_page(
            [
                {
                    "f12": "000001",
                    "f14": "平安银行",
                    "f2": 10.5,
                    "f3": -0.5,
                    "f100": "银行",
                }
            ],
            total=1,
        )
        # Call 1: direct → fail; Call 2: auth → ok; Call 3: proxied data → ok
        mock_session.get.side_effect = [
            ConnectionError("VPN blocked"),
            _make_response(auth_data),
            _make_response(page_data),
        ]
        client._session = mock_session

        result = client.fetch_spot()
        assert len(result) == 1
        assert result[0]["symbol"] == "000001"
        assert client._direct_ok is False

    def test_gateway_auth_and_proxy(self):
        """Gateway mode: fetches auth config, uses returned proxy + cookies."""
        client = EastMoneyClient(gateway="1.2.3.4", token="tok", mode="gateway")
        mock_session = MagicMock()

        auth_data = {
            "proxy": "http://user:pass@proxy:8080",
            "ua": "Mozilla/5.0 Test",
            "nid18": "cookie_val",
            "nid18_create_time": "ts_val",
        }
        page_data = _make_spot_page(
            [{"f12": "300001", "f14": "特锐德", "f2": 20.0, "f3": 2.0}], total=1
        )
        # Call 1: auth endpoint; Call 2: proxied data
        mock_session.get.side_effect = [
            _make_response(auth_data),
            _make_response(page_data),
        ]
        client._session = mock_session

        result = client.fetch_spot()
        assert len(result) == 1

        # First call: auth endpoint
        auth_call = mock_session.get.call_args_list[0]
        assert "47001" in auth_call[0][0]
        assert "akshare-auth" in auth_call[0][0]

        # Second call: proxied data request
        data_call = mock_session.get.call_args_list[1]
        data_url = data_call[0][0]
        assert "push2.eastmoney.com" in data_url  # original URL, not rewritten
        data_kwargs = data_call[1]
        assert data_kwargs["headers"]["User-Agent"] == "Mozilla/5.0 Test"
        assert "cookie_val" in data_kwargs["headers"]["Cookie"]
        assert data_kwargs["proxies"]["https"] == "http://user:pass@proxy:8080"

    def test_gateway_mode_skips_direct(self):
        """In gateway-only mode, direct is never attempted."""
        client = EastMoneyClient(mode="gateway", token="tok", gateway="1.2.3.4")
        mock_session = MagicMock()
        auth_data = {
            "proxy": "http://p:p@1.2.3.4:80",
            "ua": "UA",
            "nid18": "n",
            "nid18_create_time": "t",
        }
        mock_session.get.side_effect = [
            _make_response(auth_data),
            _make_response(
                _make_spot_page([{"f12": "600000", "f14": "浦发银行"}], total=1)
            ),
        ]
        client._session = mock_session

        client.fetch_spot()
        # 2 calls: auth + data (no direct attempt)
        assert mock_session.get.call_count == 2
        # First call is auth
        assert "akshare-auth" in mock_session.get.call_args_list[0][0][0]

    def test_direct_mode_skips_gateway(self):
        """In direct-only mode, gateway is never attempted even on failure."""
        client = EastMoneyClient(mode="direct", token="tok")
        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("blocked")
        client._session = mock_session

        result = client.fetch_spot()
        assert result == []
        # 3 calls (direct with retry), but no gateway/auth calls
        for call in mock_session.get.call_args_list:
            url = call[0][0]
            assert "akshare-auth" not in url  # no auth endpoint called

    def test_concurrent_pages(self):
        """Multi-page fetch uses concurrent requests."""
        client = EastMoneyClient(mode="direct", max_workers=4)
        mock_session = MagicMock()

        # Page 1: total=250, so 3 pages of 100
        page1 = _make_spot_page(
            [{"f12": f"{i:06d}", "f14": f"stock{i}"} for i in range(100)],
            total=250,
        )
        page2 = _make_spot_page(
            [{"f12": f"{i:06d}", "f14": f"stock{i}"} for i in range(100, 200)],
            total=250,
        )
        page3 = _make_spot_page(
            [{"f12": f"{i:06d}", "f14": f"stock{i}"} for i in range(200, 250)],
            total=250,
        )
        mock_session.get.side_effect = [
            _make_response(page1),
            _make_response(page2),
            _make_response(page3),
        ]
        client._session = mock_session

        result = client.fetch_spot()
        assert len(result) == 250
        # 3 HTTP calls total (1 sequential + 2 concurrent)
        assert mock_session.get.call_count == 3

    def test_sector_field_populated(self):
        """f100 maps to sector in normalised output."""
        client = EastMoneyClient(mode="direct")
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(
            _make_spot_page(
                [
                    {"f12": "600519", "f14": "贵州茅台", "f100": "酿酒行业"},
                    {"f12": "000001", "f14": "平安银行", "f100": "银行"},
                    {"f12": "300750", "f14": "宁德时代", "f100": "-"},
                ],
                total=3,
            )
        )
        client._session = mock_session

        result = client.fetch_spot()
        sectors = {r["symbol"]: r["sector"] for r in result}
        assert sectors["600519"] == "酿酒行业"
        assert sectors["000001"] == "银行"
        assert sectors["300750"] == ""  # dash → empty

    def test_concept_boards(self):
        """fetch_concept_boards normalises concept board data."""
        client = EastMoneyClient(mode="direct")
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(
            _make_spot_page(
                [
                    {
                        "f12": "BK0729",
                        "f14": "人工智能",
                        "f3": 2.5,
                        "f104": 80,
                        "f105": 20,
                    },
                    {
                        "f12": "BK0655",
                        "f14": "光伏概念",
                        "f3": -1.0,
                        "f104": 30,
                        "f105": 50,
                    },
                ],
                total=2,
            )
        )
        client._session = mock_session

        boards = client.fetch_concept_boards()
        assert len(boards) == 2
        assert boards[0]["code"] == "BK0729"
        assert boards[0]["name"] == "人工智能"
        assert boards[0]["pct_change"] == 2.5

    def test_industry_boards(self):
        """fetch_industry_boards normalises industry board data."""
        client = EastMoneyClient(mode="direct")
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(
            _make_spot_page(
                [
                    {
                        "f12": "BK0475",
                        "f14": "银行",
                        "f3": 0.5,
                        "f104": 30,
                        "f105": 5,
                        "f20": 1e13,
                    }
                ],
                total=1,
            )
        )
        client._session = mock_session

        boards = client.fetch_industry_boards()
        assert len(boards) == 1
        assert boards[0]["name"] == "银行"
        assert boards[0]["total_market_cap"] == 1e13

    def test_empty_response(self):
        """Empty API response → empty list, no crash."""
        client = EastMoneyClient(mode="direct")
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(
            {"data": {"total": 0, "diff": []}}
        )
        client._session = mock_session

        assert client.fetch_spot() == []

    def test_total_failure_returns_empty(self):
        """All requests fail → empty list."""
        client = EastMoneyClient(mode="auto", token="tok", gateway="1.2.3.4")
        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("down")
        client._session = mock_session

        assert client.fetch_spot() == []

    def test_health_check(self):
        """health_check returns connectivity info."""
        client = EastMoneyClient(mode="direct")
        mock_session = MagicMock()
        mock_session.get.return_value = _make_response(
            {"data": {"total": 1, "diff": [{"f12": "x"}]}}
        )
        client._session = mock_session

        health = client.health_check()
        assert health["direct_ok"] is True
        assert "elapsed_ms" in health


# ---------------------------------------------------------------------------
# Unit: Singleton / init
# ---------------------------------------------------------------------------


class TestInit:
    def setup_method(self):
        # Reset singleton between tests
        import src.data.eastmoney_client as mod

        mod._client = None

    def test_init_eastmoney_client_success(self):
        with patch("src.data.eastmoney_client.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "data_sources": {
                    "eastmoney_proxy": {
                        "enabled": True,
                        "gateway": "1.2.3.4",
                        "mode": "direct",
                    }
                }
            }
            assert init_eastmoney_client() is True

    def test_init_config_missing(self):
        """Missing config → still succeeds with defaults."""
        with patch("src.data.eastmoney_client.load_config") as mock_cfg:
            mock_cfg.side_effect = FileNotFoundError("stocks.yaml")
            assert init_eastmoney_client() is True

    def test_get_client_singleton(self):
        """get_eastmoney_client returns same instance."""
        with patch("src.data.eastmoney_client.load_config") as mock_cfg:
            mock_cfg.return_value = {"data_sources": {}}
            c1 = get_eastmoney_client()
            c2 = get_eastmoney_client()
            assert c1 is c2


# ---------------------------------------------------------------------------
# Unit: backward compat wrapper
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def setup_method(self):
        import src.data.eastmoney_client as mod

        mod._client = None

    def test_import_init_proxy_patch(self):
        """Old import path still works."""
        from src.data.eastmoney_proxy import init_proxy_patch

        with patch("src.data.eastmoney_client.load_config") as mock_cfg:
            mock_cfg.return_value = {"data_sources": {}}
            assert init_proxy_patch() is True
