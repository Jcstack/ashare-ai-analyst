"""Shared EastMoney datacenter API helper.

Direct access to datacenter-web.eastmoney.com/api/data/v1/get without
AKShare wrappers. More stable than AKShare wrappers which break when
EastMoney changes field names.

Used by: lockup_expiry, block_trade, insider_activity, earnings_forecast.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.eastmoney_datacenter")

__all__ = ["EastMoneyDatacenter"]

_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_UT_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"


class EastMoneyDatacenter:
    """Shared helper for EastMoney datacenter API calls.

    Usage::

        dc = EastMoneyDatacenter()
        df = dc.query("RPT_CUSTOM_STOCK_RESTRICTED_CIRCUL", page_size=50)
    """

    def __init__(self) -> None:
        self._session = create_session(timeout=(5.0, 20.0), retries=2)
        self._last_request_ts: float = 0.0

    def _polite_sleep(self, interval: float = 0.3) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    def query(
        self,
        report_name: str,
        columns: str = "ALL",
        page_number: int = 1,
        page_size: int = 50,
        sort_columns: str = "",
        sort_types: str = "-1",
        filter_str: str = "",
        extra_params: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """Query the EastMoney datacenter API.

        Args:
            report_name: Report identifier (e.g., "RPT_CUSTOM_STOCK_RESTRICTED_CIRCUL").
            columns: Column selection ("ALL" or comma-separated).
            page_number: Page number (1-based).
            page_size: Results per page.
            sort_columns: Column to sort by.
            sort_types: "-1" for descending, "1" for ascending.
            filter_str: SQL-like filter (e.g., '(SECURITY_CODE="601318")').
            extra_params: Additional query parameters.

        Returns:
            DataFrame with API results. Empty DataFrame on failure.
        """
        self._polite_sleep()

        params: dict[str, Any] = {
            "reportName": report_name,
            "columns": columns,
            "pageNumber": page_number,
            "pageSize": page_size,
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
            "source": "WEB",
            "client": "WEB",
            "filter": filter_str,
            "_": int(time.time() * 1000),
        }
        if extra_params:
            params.update(extra_params)

        try:
            resp = self._session.get(_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                logger.warning(
                    "Datacenter query failed for %s: %s",
                    report_name,
                    data.get("message", "unknown"),
                )
                return pd.DataFrame()

            result = data.get("result", {})
            rows = result.get("data", [])
            if not rows:
                return pd.DataFrame()

            return pd.DataFrame(rows)

        except Exception as exc:
            logger.warning("Datacenter API error for %s: %s", report_name, exc)
            return pd.DataFrame()

    def query_all_pages(
        self,
        report_name: str,
        max_pages: int = 5,
        page_size: int = 50,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Query multiple pages and concatenate results.

        Args:
            report_name: Report identifier.
            max_pages: Maximum pages to fetch.
            page_size: Results per page.
            **kwargs: Additional args passed to query().

        Returns:
            Concatenated DataFrame from all pages.
        """
        frames: list[pd.DataFrame] = []
        for page in range(1, max_pages + 1):
            df = self.query(
                report_name,
                page_number=page,
                page_size=page_size,
                **kwargs,
            )
            if df.empty:
                break
            frames.append(df)
            if len(df) < page_size:
                break  # last page

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
