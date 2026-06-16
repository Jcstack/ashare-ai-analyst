"""Remote Qlib adapter — connects to the Qlib microservice via HTTP.

Used when Qlib runs in a separate container (Python 3.11) and the main
application (Python 3.13) communicates with it over the network.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("prediction.qlib_remote")

_DEFAULT_URL = "http://qlib-service:8001"


def _get_base_url() -> str:
    """Resolve Qlib service URL from env → config → default."""
    env_url = os.environ.get("QLIB_SERVICE_URL")
    if env_url:
        return env_url.rstrip("/")
    try:
        cfg = load_config("research")
        url = cfg.get("actuary", {}).get("service_url", "")
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return _DEFAULT_URL


class QlibRemoteAdapter:
    """HTTP client for the Qlib microservice."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._base_url = base_url or _get_base_url()
        self._timeout = timeout
        self._session = requests.Session()
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            resp = self._session.get(f"{self._base_url}/health", timeout=self._timeout)
            data = resp.json()
            self._available = data.get("installed", False) and data.get(
                "initialized", False
            )
            if self._available:
                logger.info(
                    "Qlib remote service available (v%s) at %s",
                    data.get("version", "?"),
                    self._base_url,
                )
            return self._available
        except Exception as exc:
            logger.debug("Qlib remote service unavailable: %s", exc)
            self._available = False
            return False

    def predict(
        self, symbols: list[str], horizon: int = 5
    ) -> dict[str, dict[str, Any]]:
        if not self.is_available():
            return {}
        try:
            resp = self._session.post(
                f"{self._base_url}/predict",
                json={"symbols": symbols, "horizon": horizon},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Qlib remote predict failed: %s", exc)
            return {}

    def get_ic_value(self, symbol: str) -> float | None:
        if not self.is_available():
            return None
        try:
            resp = self._session.post(
                f"{self._base_url}/ic",
                json={"symbol": symbol},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json().get("ic")
        except Exception as exc:
            logger.warning("Qlib remote IC failed: %s", exc)
            return None

    def get_alpha_factors(self, symbol: str) -> dict[str, float] | None:
        if not self.is_available():
            return None
        try:
            resp = self._session.post(
                f"{self._base_url}/alpha",
                json={"symbol": symbol},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json().get("alpha_factors")
        except Exception as exc:
            logger.warning("Qlib remote alpha failed: %s", exc)
            return None

    def get_health_info(self) -> dict[str, Any]:
        try:
            resp = self._session.get(f"{self._base_url}/health", timeout=self._timeout)
            data = resp.json()
            data["mode"] = "remote"
            data["service_url"] = self._base_url
            return data
        except Exception as exc:
            return {
                "installed": False,
                "mode": "remote",
                "service_url": self._base_url,
                "error": str(exc),
            }
