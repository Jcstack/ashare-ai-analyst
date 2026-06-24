"""Tests for EastMoney proxy lazy activation.

Validates lazy proxy-patch activation: direct first, degrade to
akshare-proxy-patch on connection failure.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestInitProxyPatch:
    """Verify init_proxy_patch only inits curl_cffi, NOT proxy-patch."""

    def setup_method(self) -> None:
        import src.data.eastmoney_client as client_mod
        import src.data.eastmoney_proxy as proxy_mod

        client_mod._client = None
        proxy_mod._initialized = False
        proxy_mod._proxy_patch_active = False

    def test_init_proxy_patch_returns_bool(self) -> None:
        with patch("src.data.eastmoney_client.load_config") as mock_cfg:
            mock_cfg.return_value = {"data_sources": {}}
            from src.data.eastmoney_proxy import init_proxy_patch

            assert init_proxy_patch() is True

    def test_init_proxy_patch_is_callable(self) -> None:
        from src.data.eastmoney_proxy import init_proxy_patch

        assert callable(init_proxy_patch)

    def test_module_has_all_exports(self) -> None:
        import src.data.eastmoney_proxy as mod

        for name in ("init_proxy_patch", "em_api_call", "is_proxy_active"):
            assert name in mod.__all__

    def test_init_does_not_install_proxy_patch(self) -> None:
        """init_proxy_patch should NOT activate akshare-proxy-patch."""
        import src.data.eastmoney_proxy as mod

        with (
            patch.object(mod, "_install_akshare_proxy_patch") as mock_install,
            patch("src.data.eastmoney_client.load_config", return_value={}),
        ):
            mod._initialized = False
            mod.init_proxy_patch()
            mock_install.assert_not_called()
            assert mod._proxy_patch_active is False


class TestEmApiCall:
    """Test em_api_call lazy activation wrapper."""

    def setup_method(self) -> None:
        import src.data.eastmoney_proxy as mod

        mod._proxy_patch_active = False

    def test_direct_success_no_proxy(self) -> None:
        """When direct call succeeds, proxy-patch is NOT activated."""
        import src.data.eastmoney_proxy as mod

        fn = MagicMock(return_value="ok")
        result = mod.em_api_call(fn, symbol="test")
        assert result == "ok"
        fn.assert_called_once_with(symbol="test")
        assert mod._proxy_patch_active is False

    def test_connection_error_activates_proxy_and_retries(self) -> None:
        """On connection failure, activate proxy-patch and retry."""
        import src.data.eastmoney_proxy as mod

        from requests.exceptions import ConnectionError as ReqConnError

        fn = MagicMock(side_effect=[ReqConnError("Connection aborted"), "ok"])
        with patch.object(mod, "activate_proxy_patch", return_value=True):
            result = mod.em_api_call(fn, symbol="test")
        assert result == "ok"
        assert fn.call_count == 2

    def test_non_connection_error_raises_immediately(self) -> None:
        """Non-connection errors (e.g. ValueError) should NOT trigger proxy."""
        import src.data.eastmoney_proxy as mod

        fn = MagicMock(side_effect=ValueError("bad data"))
        with patch.object(mod, "activate_proxy_patch") as mock_activate:
            with pytest.raises(ValueError, match="bad data"):
                mod.em_api_call(fn, symbol="test")
            mock_activate.assert_not_called()

    def test_proxy_already_active_calls_directly(self) -> None:
        """When proxy is already active, call directly without try/retry."""
        import src.data.eastmoney_proxy as mod

        mod._proxy_patch_active = True
        fn = MagicMock(return_value="proxied")
        result = mod.em_api_call(fn)
        assert result == "proxied"
        fn.assert_called_once()

    def test_proxy_activation_fails_returns_none(self) -> None:
        """If proxy-patch can't be activated, return None for connection errors."""
        import src.data.eastmoney_proxy as mod

        from requests.exceptions import ConnectionError as ReqConnError

        fn = MagicMock(side_effect=ReqConnError("blocked"))
        with patch.object(mod, "activate_proxy_patch", return_value=False):
            result = mod.em_api_call(fn)
            assert result is None


class TestIsConnectionError:
    """Test _is_connection_error helper."""

    def test_requests_connection_error(self) -> None:
        from requests.exceptions import ConnectionError as ReqConnError

        from src.data.eastmoney_proxy import _is_connection_error

        assert _is_connection_error(ReqConnError("fail")) is True

    def test_remote_disconnected_in_str(self) -> None:
        from src.data.eastmoney_proxy import _is_connection_error

        exc = Exception("('Connection aborted.', RemoteDisconnected(...))")
        assert _is_connection_error(exc) is True

    def test_value_error_not_connection(self) -> None:
        from src.data.eastmoney_proxy import _is_connection_error

        assert _is_connection_error(ValueError("parse error")) is False

    def test_os_error_is_connection(self) -> None:
        from src.data.eastmoney_proxy import _is_connection_error

        assert _is_connection_error(OSError("network down")) is True


class TestActivateProxyPatch:
    """Test activate_proxy_patch idempotency."""

    def setup_method(self) -> None:
        import src.data.eastmoney_proxy as mod

        mod._proxy_patch_active = False

    def test_idempotent_when_active(self) -> None:
        import src.data.eastmoney_proxy as mod

        mod._proxy_patch_active = True
        with patch.object(mod, "_install_akshare_proxy_patch") as mock_install:
            assert mod.activate_proxy_patch() is True
            mock_install.assert_not_called()

    def test_calls_install_when_inactive(self) -> None:
        import src.data.eastmoney_proxy as mod

        with patch.object(
            mod, "_install_akshare_proxy_patch", return_value=True
        ) as mock_install:
            assert mod.activate_proxy_patch() is True
            mock_install.assert_called_once()
            assert mod._proxy_patch_active is True
