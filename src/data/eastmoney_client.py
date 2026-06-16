"""Self-contained EastMoney data client (I-067 replacement).

Calls push2.eastmoney.com API directly via ``curl_cffi`` with Chrome TLS
impersonation.  Falls back to an auth gateway in VPN-blocked environments
using **isolated URL rewriting** — no global monkey-patching.

Replaces the previous ``akshare-proxy-patch`` dependency which had critical
security issues (global ``requests.Session.request`` monkey-patch, plaintext
auth, MITM via opaque third-party proxy).

Usage::

    from src.data.eastmoney_client import get_eastmoney_client

    client = get_eastmoney_client()
    snapshot = client.fetch_spot()       # ~5800 A-shares with sector (行业)
    concepts = client.fetch_concept_boards()

Configuration: ``config/stocks.yaml`` → ``data_sources.eastmoney_proxy``.
Auth token: env var ``AKSHARE_PROXY_TOKEN``.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.eastmoney_client")

# ---------------------------------------------------------------------------
# f-field reference (from EastMoney push2 API)
# ---------------------------------------------------------------------------
# f2=最新价 f3=涨跌幅 f4=涨跌额 f5=成交量(手) f6=成交额(元) f7=振幅
# f8=换手率 f9=PE(动态) f10=量比 f12=代码 f13=市场 f14=名称
# f15=最高 f16=最低 f17=今开 f18=昨收 f20=总市值(元) f23=PB
# f100=所属行业 f115=PB(alt)
SPOT_FIELDS = (
    "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f23,f100,f115"
)

# Concept board: f3=涨跌幅 f12=代码 f14=名称 f104=上涨 f105=下跌 f136=领涨股涨跌幅
CONCEPT_FIELDS = "f3,f12,f14,f104,f105,f136"

# Industry board: same fields as concept
INDUSTRY_FIELDS = "f3,f12,f14,f104,f105,f20"

# A-share filter: SH main + STAR + SZ main + ChiNext + BSE
FS_ALL_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
# Concept board filter
FS_CONCEPT = "m:90+t:3+f:!50"
# Industry board filter
FS_INDUSTRY = "m:90+t:2+f:!50"

PAGE_SIZE = 100
# Common UT token (public, found in akshare source)
UT_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    """Convert to float, returning None for missing/invalid values."""
    if v is None or v == "-" or v == "":
        return None
    try:
        f = float(v)
        return None if f != f else f  # NaN check
    except (ValueError, TypeError):
        return None


def _safe_str(v: Any) -> str:
    """Convert to string, returning '' for missing/dash values."""
    if v is None or v == "-" or v == "":
        return ""
    return str(v)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class _AuthCache:
    """Thread-safe cache for gateway auth config (proxy URL + cookies)."""

    def __init__(self, ttl: float = 15.0) -> None:
        self.data: dict[str, str] | None = None
        self.expire_at: float = 0
        self.lock = threading.Lock()
        self.ttl = ttl

    def get(self) -> dict[str, str] | None:
        if self.data and time.time() < self.expire_at:
            return self.data
        return None

    def set(self, data: dict[str, str]) -> None:
        with self.lock:
            self.data = data
            self.expire_at = time.time() + self.ttl

    def invalidate(self) -> None:
        with self.lock:
            self.expire_at = 0


class EastMoneyClient:
    """Self-contained client for EastMoney push2 API.

    Connection strategy (isolated, no global side effects):

    1. **Direct** — ``curl_cffi`` → ``https://push2.eastmoney.com`` with
       Chrome TLS impersonation.  Works in production / server environments.
    2. **Gateway** — authenticates with the gateway auth service, obtains a
       rotating proxy + browser fingerprint (UA + cookies), then routes
       requests through that proxy.  Isolated: only affects this client's
       requests, no global ``requests.Session`` monkey-patching.

    In ``auto`` mode (default), tries direct first.  On failure, switches to
    gateway for the remainder of the session.
    """

    AUTH_PORT = 47001
    AUTH_PATH = "/api/akshare-auth"
    AUTH_VERSION = "0.2.7"

    def __init__(
        self,
        *,
        gateway: str = "",
        token: str = "",
        timeout: int = 15,
        max_workers: int = 8,
        mode: str = "auto",
    ) -> None:
        self._gateway = gateway
        self._token = token
        self._timeout = timeout
        self._max_workers = max_workers
        self._mode = mode  # auto | direct | gateway
        self._session: Any = None
        self._direct_ok: bool | None = None  # None = untested
        self._auth_cache = _AuthCache(ttl=15.0)

    # -- Session management --------------------------------------------------

    def _get_session(self) -> Any:
        if self._session is None:
            from curl_cffi.requests import Session

            self._session = Session(impersonate="chrome")
        return self._session

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    # -- Auth ----------------------------------------------------------------

    def _get_auth_config(self) -> dict[str, str] | None:
        """Get gateway auth config (cached for 15s).

        Calls ``http://<gateway>:47001/api/akshare-auth`` which returns::

            {"proxy": "http://user:pass@ip:port",
             "ua": "Mozilla/5.0 ...",
             "nid18": "...",
             "nid18_create_time": "..."}
        """
        cached = self._auth_cache.get()
        if cached:
            return cached

        auth_url = f"http://{self._gateway}:{self.AUTH_PORT}{self.AUTH_PATH}"
        try:
            session = self._get_session()
            resp = session.get(
                auth_url,
                params={"token": self._token, "version": self.AUTH_VERSION},
                timeout=5,
            )
            data = resp.json()
            if data.get("ua") and data.get("proxy"):
                self._auth_cache.set(data)
                return data
            logger.warning("Gateway auth failed: %s", data.get("error_msg", "no ua"))
        except Exception as exc:
            logger.warning("Gateway auth request failed: %s", exc)

        # Return stale cache if fresh fetch failed
        return self._auth_cache.data

    # -- Request layer -------------------------------------------------------

    def _request(self, url: str) -> dict | None:
        """GET JSON from *url* with auto-fallback direct → gateway."""
        # --- Direct ---
        if self._mode != "gateway" and self._direct_ok is not False:
            result = self._try_direct(url)
            if result is not None:
                self._direct_ok = True
                return result
            # Mark direct as broken so subsequent calls skip it
            if self._mode == "auto":
                self._direct_ok = False
                logger.info("Direct push2 access failed, switching to gateway")

        # --- Gateway fallback ---
        if self._mode != "direct" and self._token:
            return self._try_gateway(url)

        return None

    def _try_direct(self, url: str) -> dict | None:
        try:
            resp = self._get_session().get(url, timeout=self._timeout)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("data"):
                    return data
        except Exception as exc:
            logger.debug("Direct request failed: %s", exc)
        return None

    def _try_gateway(self, url: str) -> dict | None:
        """Route through authenticated rotating proxy (isolated)."""
        auth = self._get_auth_config()
        if not auth:
            return None

        headers = {
            "User-Agent": auth["ua"],
            "Cookie": (
                f"nid18={auth['nid18']}; nid18_create_time={auth['nid18_create_time']}"
            ),
        }
        proxies = {"http": auth["proxy"], "https": auth["proxy"]}

        try:
            resp = self._get_session().get(
                url, headers=headers, proxies=proxies, timeout=self._timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("data"):
                    return data
        except Exception as exc:
            logger.debug("Gateway proxy request failed: %s", exc)
        return None

    # -- Page fetching -------------------------------------------------------

    def _build_url(
        self,
        server: int,
        fs: str,
        fields: str,
        fid: str = "f3",
        pn: int = 1,
        pz: int = PAGE_SIZE,
    ) -> str:
        return (
            f"https://{server}.push2.eastmoney.com/api/qt/clist/get"
            f"?pn={pn}&pz={pz}&po=1&np=1"
            f"&ut={UT_TOKEN}&fltt=2&invt=2&fid={fid}"
            f"&fs={fs}&fields={fields}"
        )

    def _fetch_page(
        self, server: int, fs: str, fields: str, fid: str, pn: int
    ) -> dict | None:
        """Fetch a single page with retry on transient failures."""
        url = self._build_url(server, fs, fields, fid, pn)
        for attempt in range(3):
            result = self._request(url)
            if result is not None:
                return result
            if attempt < 2:
                time.sleep(0.3 * (attempt + 1))
        return None

    def _fetch_all_pages(
        self, server: int, fs: str, fields: str, fid: str = "f3"
    ) -> list[dict]:
        """Fetch all pages concurrently using ThreadPoolExecutor."""
        t0 = time.monotonic()

        # Page 1 — learn total count
        first = self._fetch_page(server, fs, fields, fid, pn=1)
        if not first:
            return []

        data_section = first.get("data") or {}
        total = data_section.get("total", 0)
        all_records: list[dict] = data_section.get("diff") or []
        if not isinstance(all_records, list):
            all_records = []

        if total <= PAGE_SIZE:
            elapsed = time.monotonic() - t0
            logger.debug(
                "Fetched %d records in 1 page (%.1fs)", len(all_records), elapsed
            )
            return all_records

        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

        # Remaining pages — concurrent
        failed_pages: list[int] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._fetch_page, server, fs, fields, fid, pn): pn
                for pn in range(2, total_pages + 1)
            }
            for future in as_completed(futures):
                pn = futures[future]
                try:
                    result = future.result()
                    if result:
                        diff = (result.get("data") or {}).get("diff") or []
                        if isinstance(diff, list):
                            all_records.extend(diff)
                    else:
                        failed_pages.append(pn)
                except Exception as exc:
                    failed_pages.append(pn)
                    logger.warning("Page %d failed: %s", pn, exc)

        if failed_pages:
            logger.warning(
                "%d/%d pages failed (pages: %s)",
                len(failed_pages),
                total_pages,
                failed_pages[:10],
            )

        elapsed = time.monotonic() - t0
        logger.info(
            "Fetched %d records across %d pages (%.1fs, %d workers)",
            len(all_records),
            total_pages,
            elapsed,
            self._max_workers,
        )
        return all_records

    # -- Public data methods -------------------------------------------------

    def fetch_spot(self) -> list[dict]:
        """Fetch full A-share market snapshot including f100=行业.

        Returns normalised dicts::

            {
                "symbol": "600519",
                "name": "贵州茅台",
                "price": 1688.0,
                "change_pct": 1.23,
                "sector": "酿酒行业",  # ← from f100, previously missing!
                ...
            }
        """
        raw = self._fetch_all_pages(server=82, fs=FS_ALL_A, fields=SPOT_FIELDS)
        normalised: list[dict] = []
        for row in raw:
            symbol = _safe_str(row.get("f12"))
            if not symbol:
                continue
            normalised.append(
                {
                    "symbol": symbol,
                    "name": _safe_str(row.get("f14")),
                    "price": _safe_float(row.get("f2")) or 0,
                    "change_pct": _safe_float(row.get("f3")) or 0,
                    "change_amt": _safe_float(row.get("f4")),
                    "volume": _safe_float(row.get("f5")) or 0,
                    "amount": _safe_float(row.get("f6")),
                    "amplitude": _safe_float(row.get("f7")),
                    "turnover_rate": _safe_float(row.get("f8")),
                    "pe_ratio": _safe_float(row.get("f9")),
                    "volume_ratio": _safe_float(row.get("f10")) or 1.0,
                    "high": _safe_float(row.get("f15")),
                    "low": _safe_float(row.get("f16")),
                    "open": _safe_float(row.get("f17")),
                    "prev_close": _safe_float(row.get("f18")),
                    "market_cap": _safe_float(row.get("f20")),
                    "pb_ratio": _safe_float(row.get("f23")),
                    "sector": _safe_str(row.get("f100")),
                }
            )
        logger.info("EastMoney spot: %d stocks fetched", len(normalised))
        return normalised

    def fetch_concept_boards(self) -> list[dict]:
        """Fetch concept board list from EastMoney.

        Returns dicts with keys: code, name, pct_change, up_count,
        down_count, lead_pct.
        """
        raw = self._fetch_all_pages(
            server=79, fs=FS_CONCEPT, fields=CONCEPT_FIELDS, fid="f3"
        )
        boards: list[dict] = []
        for row in raw:
            code = _safe_str(row.get("f12"))
            name = _safe_str(row.get("f14"))
            if not name:
                continue
            boards.append(
                {
                    "code": code,
                    "name": name,
                    "pct_change": _safe_float(row.get("f3")),
                    "up_count": int(row.get("f104", 0) or 0),
                    "down_count": int(row.get("f105", 0) or 0),
                    "lead_pct": _safe_float(row.get("f136")),
                }
            )
        logger.info("EastMoney concept boards: %d fetched", len(boards))
        return boards

    def fetch_industry_boards(self) -> list[dict]:
        """Fetch industry board (行业板块) list from EastMoney.

        Returns dicts with keys: code, name, pct_change, up_count,
        down_count, total_market_cap.
        """
        raw = self._fetch_all_pages(
            server=17, fs=FS_INDUSTRY, fields=INDUSTRY_FIELDS, fid="f3"
        )
        boards: list[dict] = []
        for row in raw:
            code = _safe_str(row.get("f12"))
            name = _safe_str(row.get("f14"))
            if not name:
                continue
            boards.append(
                {
                    "code": code,
                    "name": name,
                    "pct_change": _safe_float(row.get("f3")),
                    "up_count": int(row.get("f104", 0) or 0),
                    "down_count": int(row.get("f105", 0) or 0),
                    "total_market_cap": _safe_float(row.get("f20")),
                }
            )
        logger.info("EastMoney industry boards: %d fetched", len(boards))
        return boards

    def fetch_board_constituents(self, board_code: str) -> list[dict]:
        """Fetch constituent stocks for a concept/industry board.

        Args:
            board_code: Board code (e.g. "BK1128").

        Returns dicts with keys: symbol, name, price, pct_change, amount,
        amplitude.
        """
        cons_fields = "f2,f3,f6,f7,f12,f14"
        fs = f"b:{board_code}+f:!50"
        raw = self._fetch_all_pages(server=82, fs=fs, fields=cons_fields)
        stocks: list[dict] = []
        for row in raw:
            symbol = _safe_str(row.get("f12"))
            if not symbol:
                continue
            stocks.append(
                {
                    "symbol": symbol,
                    "name": _safe_str(row.get("f14")),
                    "price": _safe_float(row.get("f2")),
                    "pct_change": _safe_float(row.get("f3")),
                    "amount": _safe_float(row.get("f6")),
                    "amplitude": _safe_float(row.get("f7")),
                }
            )
        return stocks

    def health_check(self) -> dict[str, Any]:
        """Quick connectivity test — returns mode and timing info."""
        t0 = time.monotonic()
        # Try fetching page 1 of spot (1 page, fast)
        url = self._build_url(server=82, fs=FS_ALL_A, fields="f12", fid="f12", pz=1)

        direct_ok = False
        gateway_ok = False

        # Test direct
        if self._mode != "gateway":
            direct_ok = self._try_direct(url) is not None

        # Test gateway
        if self._mode != "direct" and self._token:
            gateway_ok = self._try_gateway(url) is not None

        elapsed = time.monotonic() - t0
        return {
            "direct_ok": direct_ok,
            "gateway_ok": gateway_ok,
            "mode": self._mode,
            "active_mode": "direct" if self._direct_ok else "gateway",
            "elapsed_ms": round(elapsed * 1000),
        }


# ---------------------------------------------------------------------------
# Singleton & init
# ---------------------------------------------------------------------------

_client: EastMoneyClient | None = None


def get_eastmoney_client() -> EastMoneyClient:
    """Get or create the EastMoney client singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = _create_client()
    return _client


def _create_client() -> EastMoneyClient:
    """Create client from ``config/stocks.yaml``."""
    try:
        config = load_config("stocks")
    except Exception:
        config = {}

    proxy_cfg = config.get("data_sources", {}).get("eastmoney_proxy", {})
    return EastMoneyClient(
        gateway=proxy_cfg.get("gateway", ""),
        token=os.environ.get("AKSHARE_PROXY_TOKEN", ""),
        timeout=proxy_cfg.get("timeout", 15),
        max_workers=proxy_cfg.get("max_workers", 8),
        mode=proxy_cfg.get("mode", "auto"),
    )


def init_eastmoney_client() -> bool:
    """Initialise the EastMoney client at process startup.

    This replaces the old ``init_proxy_patch()`` — no global monkey-patching,
    just creates the ``curl_cffi`` client singleton.

    Returns True on success, False on failure (non-fatal).
    """
    try:
        client = get_eastmoney_client()
        logger.info(
            "EastMoney client initialised (gateway=%s, mode=%s)",
            client._gateway,
            client._mode,
        )
        return True
    except Exception as exc:
        logger.warning("EastMoney client init failed: %s", exc)
        return False
