"""EastMoney proxy initialisation — lazy proxy-patch activation.

Strategy: prefer direct EastMoney access. If direct access fails (VPN block,
RemoteDisconnected, etc.), activate ``akshare-proxy-patch`` on demand. Once
activated, the global monkey-patch routes all subsequent AKShare ``_em`` calls
through the auth gateway automatically.

Two complementary modes:

1. **akshare-proxy-patch** (lazy): Global monkey-patch on ``requests.Session``.
   NOT activated at startup — lazily activated on first connection failure
   via ``em_api_call()``.

2. **EastMoneyClient** (curl_cffi): Self-contained client using Chrome TLS
   impersonation. Always initialized at startup.

Configuration: ``config/stocks.yaml`` → ``data_sources.eastmoney_proxy``
Auth token: env var ``AKSHARE_PROXY_TOKEN``
"""

from __future__ import annotations

import os

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.eastmoney_proxy")

_initialized = False
_proxy_patch_active = False


def _install_akshare_proxy_patch() -> bool:
    """Install the akshare-proxy-patch global monkey-patch.

    This patches ``requests.Session.request`` to route EastMoney API calls
    through an authenticated proxy gateway. Required for AKShare functions
    like ``stock_zh_a_hist()`` and ``stock_zh_a_spot_em()`` to work in
    VPN-blocked environments.

    Returns True on success, False if patch is unavailable or config missing.
    """
    try:
        from akshare_proxy_patch import install_patch
    except ImportError:
        logger.debug("akshare-proxy-patch not installed, skipping")
        return False

    try:
        config = load_config("stocks")
    except FileNotFoundError:
        config = {}

    proxy_cfg = config.get("data_sources", {}).get("eastmoney_proxy", {})
    if not proxy_cfg.get("enabled", True):
        logger.debug("EastMoney proxy disabled in config")
        return False

    gateway = proxy_cfg.get("gateway", "")
    token = os.environ.get("AKSHARE_PROXY_TOKEN", "")

    if not token:
        logger.warning("AKSHARE_PROXY_TOKEN not set, akshare-proxy-patch skipped")
        return False

    try:
        install_patch(gateway, token)
        logger.info("akshare-proxy-patch installed (gateway=%s)", gateway)
        return True
    except Exception as exc:
        logger.warning("akshare-proxy-patch install failed: %s", exc)
        return False


def init_proxy_patch() -> bool:
    """Init EastMoney support at process startup.

    Called by ``src/web/app.py`` (lifespan) and ``openclaw/celery_app.py``.
    Activates both the curl_cffi client AND the akshare-proxy-patch
    proactively so all AKShare _em calls are routed through the gateway
    from the first request (no cold-start timeout penalty).

    Returns True if at least one mode is available.
    """
    global _initialized
    if _initialized:
        return True

    success = False

    # EastMoneyClient (curl_cffi, for direct push2 API calls)
    try:
        from src.data.eastmoney_client import init_eastmoney_client

        if init_eastmoney_client():
            success = True
    except Exception as exc:
        logger.debug("EastMoneyClient init skipped: %s", exc)

    # Proactively activate akshare-proxy-patch so the first AKShare call
    # doesn't have to fail and retry.  If token/package is missing this
    # is a no-op and em_api_call will still try direct-then-lazy.
    if activate_proxy_patch():
        success = True

    _initialized = True
    return success


def is_proxy_active() -> bool:
    """Check if akshare-proxy-patch is currently active."""
    return _proxy_patch_active


def activate_proxy_patch() -> bool:
    """Activate akshare-proxy-patch on demand. Idempotent."""
    global _proxy_patch_active
    if _proxy_patch_active:
        return True
    if _install_akshare_proxy_patch():
        _proxy_patch_active = True
        return True
    return False


def _is_connection_error(exc: Exception) -> bool:
    """Check if exception is a connection-level error (not data/parse error).

    Note: ``requests.Timeout`` and ``requests.ConnectionError`` are siblings
    (both inherit from ``RequestException``), so we must check both explicitly.
    """
    try:
        from requests.exceptions import ConnectionError as ReqConnError
        from requests.exceptions import Timeout as ReqTimeout

        if isinstance(exc, (ReqConnError, ReqTimeout)):
            return True
    except ImportError:
        pass
    if isinstance(exc, (ConnectionError, OSError)):
        return True
    exc_str = str(exc)
    return any(
        s in exc_str
        for s in (
            "RemoteDisconnected",
            "Connection aborted",
            "Read timed out",
            "timed out",
        )
    )


def em_api_call(fn, *args, **kwargs):
    """Call an AKShare function with lazy proxy-patch activation.

    - If proxy-patch already active: call with graceful error handling.
    - Otherwise: try direct first. On connection failure, activate
      proxy-patch and retry once.
    - Non-connection errors (data parse, etc.) are raised immediately.
    """
    fn_name = getattr(fn, "__name__", str(fn))
    if _proxy_patch_active:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if _is_connection_error(exc):
                logger.warning(
                    "EastMoney call failed (proxy active): %s — %s", fn_name, exc
                )
                return None
            raise
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if _is_connection_error(exc) and activate_proxy_patch():
            logger.info(
                "Direct EastMoney failed, retrying via proxy-patch: %s", fn_name
            )
            try:
                return fn(*args, **kwargs)
            except Exception as retry_exc:
                if _is_connection_error(retry_exc):
                    logger.warning(
                        "EastMoney retry also failed: %s — %s", fn_name, retry_exc
                    )
                    return None
                raise
        if _is_connection_error(exc):
            logger.warning("EastMoney call failed (no proxy): %s — %s", fn_name, exc)
            return None
        raise


__all__ = ["init_proxy_patch", "em_api_call", "is_proxy_active", "activate_proxy_patch"]
