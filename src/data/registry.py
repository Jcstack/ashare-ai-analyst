"""Stock registry for all A-share stocks.

Provides a cached registry of all A-share stock codes and names,
with fuzzy search support for the stock search UI (FR-D003, FR-W002).
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("data.registry")

# Default cache TTL: 24 hours
_DEFAULT_TTL_SECONDS = 86400


class StockRegistry:
    """In-memory registry of all A-share stocks with search capability.

    Fetches the full stock list from AKShare and caches it with a TTL.
    Provides fuzzy search by code prefix or name substring.

    Args:
        ttl_seconds: Cache time-to-live in seconds. Defaults to 24h.
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._cache: pd.DataFrame | None = None
        self._cache_time: float = 0.0

    def fetch_all_stocks(self) -> pd.DataFrame:
        """Fetch the full A-share stock list from AKShare.

        Returns:
            DataFrame with columns: code, name.
        """
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < self._ttl_seconds:
            return self._cache

        import akshare as ak

        from src.data.fetcher import _bypass_proxy

        # SH: SSE direct (fast ~3s)
        # SZ: SZSE direct (fast, avoids unreachable EastMoney spot_em)
        try:
            with _bypass_proxy():
                frames: list[pd.DataFrame] = []

                # --- Shanghai (SSE) ---
                for sym in ("主板A股", "科创板"):
                    try:
                        sh = ak.stock_info_sh_name_code(symbol=sym)
                        sh = sh.rename(columns={"证券代码": "code", "证券简称": "name"})
                        frames.append(sh[["code", "name"]])
                    except Exception as exc:
                        logger.warning("SH %s fetch failed: %s", sym, exc)

                # --- Shenzhen (SZSE) ---
                try:
                    sz = ak.stock_info_sz_name_code(symbol="A股列表")
                    sz = sz.rename(columns={"A股代码": "code", "A股简称": "name"})
                    frames.append(sz[["code", "name"]])
                except Exception as exc:
                    logger.warning("SZ fetch failed: %s", exc)
                    # Last resort: EastMoney spot (may be blocked by VPN)
                    try:
                        spot = ak.stock_zh_a_spot_em()
                        sz2 = spot[spot["代码"].str.match(r"^[03]")].rename(
                            columns={"代码": "code", "名称": "name"}
                        )
                        frames.append(sz2[["code", "name"]])
                    except Exception:
                        logger.warning("EastMoney spot fallback also failed")

            if not frames:
                raise RuntimeError("All stock list sources failed")

            df = pd.concat(frames, ignore_index=True).drop_duplicates(
                subset="code", keep="first"
            )
            df["code"] = df["code"].astype(str).str.zfill(6)
            self._cache = df
            self._cache_time = now
            logger.info("Stock registry refreshed: %d stocks", len(df))
            return df
        except Exception as exc:
            logger.error("Failed to fetch stock list: %s", exc)
            if self._cache is not None:
                return self._cache
            return pd.DataFrame(columns=["code", "name"])

    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        """Search stocks by code prefix or name substring.

        Args:
            query: Search query string (code or Chinese name).
            limit: Maximum number of results. Defaults to 20.

        Returns:
            List of dicts with keys: symbol, name, board.
        """
        if not query or not query.strip():
            return []

        query = query.strip()
        df = self.fetch_all_stocks()
        if df.empty:
            return []

        # Match by code prefix or name substring
        mask = df["code"].str.startswith(query) | df["name"].str.contains(
            query, case=False, na=False
        )
        matches = df[mask].head(limit)

        results = []
        for _, row in matches.iterrows():
            code = str(row["code"])
            results.append(
                {
                    "symbol": code,
                    "name": str(row["name"]),
                    "board": self.get_board(code),
                }
            )
        return results

    @staticmethod
    def get_board(symbol: str) -> str:
        """Determine the board type from the stock code prefix.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Board type: "main", "chinext", or "star".
        """
        if symbol.startswith("688"):
            return "star"
        if symbol.startswith("3"):
            return "chinext"
        return "main"

    def get_stock_info(self, symbol: str) -> dict[str, Any] | None:
        """Look up a single stock by its code.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with symbol, name, board; or None if not found.
        """
        df = self.fetch_all_stocks()
        if df.empty:
            return None

        match = df[df["code"] == symbol]
        if match.empty:
            return None

        row = match.iloc[0]
        return {
            "symbol": str(row["code"]),
            "name": str(row["name"]),
            "board": self.get_board(str(row["code"])),
        }
