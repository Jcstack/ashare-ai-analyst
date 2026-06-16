"""Tests for QlibRemoteAdapter — HTTP client for the Qlib microservice."""

from unittest.mock import MagicMock, patch

import pytest

from src.prediction.qlib_remote import QlibRemoteAdapter


@pytest.fixture
def adapter():
    return QlibRemoteAdapter(base_url="http://test-qlib:8001", timeout=5.0)


class TestQlibRemoteAdapter:
    def test_init_default_url(self):
        with patch.dict("os.environ", {}, clear=True):
            a = QlibRemoteAdapter()
            assert "qlib-service" in a._base_url

    def test_init_env_url(self):
        with patch.dict("os.environ", {"QLIB_SERVICE_URL": "http://my-qlib:9999"}):
            a = QlibRemoteAdapter()
            assert a._base_url == "http://my-qlib:9999"

    def test_is_available_success(self, adapter):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "installed": True,
            "initialized": True,
            "version": "0.9.0",
        }
        adapter._session.get = MagicMock(return_value=mock_resp)

        assert adapter.is_available() is True
        assert adapter._available is True

    def test_is_available_not_installed(self, adapter):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"installed": False}
        adapter._session.get = MagicMock(return_value=mock_resp)

        assert adapter.is_available() is False

    def test_is_available_connection_error(self, adapter):
        adapter._session.get = MagicMock(side_effect=ConnectionError("refused"))

        assert adapter.is_available() is False

    def test_is_available_cached(self, adapter):
        adapter._available = True
        assert adapter.is_available() is True

    def test_predict_success(self, adapter):
        adapter._available = True
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"600519": {"score": 0.75, "ic": 0.05}}
        mock_resp.raise_for_status = MagicMock()
        adapter._session.post = MagicMock(return_value=mock_resp)

        result = adapter.predict(["600519"], horizon=5)
        assert result["600519"]["score"] == 0.75
        adapter._session.post.assert_called_once()

    def test_predict_unavailable(self, adapter):
        adapter._available = False
        assert adapter.predict(["600519"]) == {}

    def test_predict_error(self, adapter):
        adapter._available = True
        adapter._session.post = MagicMock(side_effect=ConnectionError("timeout"))
        assert adapter.predict(["600519"]) == {}

    def test_get_ic_value_success(self, adapter):
        adapter._available = True
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"symbol": "600519", "ic": 0.042}
        mock_resp.raise_for_status = MagicMock()
        adapter._session.post = MagicMock(return_value=mock_resp)

        assert adapter.get_ic_value("600519") == 0.042

    def test_get_ic_value_unavailable(self, adapter):
        adapter._available = False
        assert adapter.get_ic_value("600519") is None

    def test_get_alpha_factors_success(self, adapter):
        adapter._available = True
        factors = {"momentum_5d": 0.03, "volatility_20d": 0.15}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"symbol": "600519", "alpha_factors": factors}
        mock_resp.raise_for_status = MagicMock()
        adapter._session.post = MagicMock(return_value=mock_resp)

        result = adapter.get_alpha_factors("600519")
        assert result == factors

    def test_get_alpha_factors_unavailable(self, adapter):
        adapter._available = False
        assert adapter.get_alpha_factors("600519") is None

    def test_get_health_info_success(self, adapter):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"installed": True, "version": "0.9.0"}
        adapter._session.get = MagicMock(return_value=mock_resp)

        info = adapter.get_health_info()
        assert info["mode"] == "remote"
        assert info["installed"] is True

    def test_get_health_info_error(self, adapter):
        adapter._session.get = MagicMock(side_effect=ConnectionError("down"))
        info = adapter.get_health_info()
        assert info["mode"] == "remote"
        assert info["installed"] is False
        assert "error" in info
