"""Service layer for Intel Report operations.

Part of v25.0 Intel-Portfolio Analysis (FR-IA004).
"""

from __future__ import annotations

import logging
from typing import Any

from src.intelligence_hub.info_store import InfoStore
from src.intelligence_hub.report_store import IntelReportStore

logger = logging.getLogger(__name__)


class IntelReportService:
    """Business logic for intel report CRUD and chat creation."""

    def __init__(
        self,
        report_store: IntelReportStore,
        info_store: InfoStore,
    ) -> None:
        self._report_store = report_store
        self._info_store = info_store

    def get_reports(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> dict[str, Any]:
        """Return paginated reports with total count."""
        reports = self._report_store.get_reports(
            symbol=symbol,
            limit=limit,
            offset=offset,
            unread_only=unread_only,
        )
        total = self._report_store.get_total_count(
            symbol=symbol,
            unread_only=unread_only,
        )
        return {"reports": reports, "total": total}

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """Fetch a single report by ID."""
        return self._report_store.get_report(report_id)

    def get_unread_count(self) -> int:
        """Return count of unread reports."""
        return self._report_store.get_unread_count()

    def mark_read(self, report_id: str) -> bool:
        """Mark a report as read."""
        return self._report_store.mark_read(report_id)

    def delete(self, report_id: str) -> bool:
        """Delete a report."""
        return self._report_store.delete(report_id)

    def create_chat_from_report(self, report_id: str) -> dict | None:
        """Prepare a chat thread from a report for deep analysis.

        Creates the thread and links it, but does NOT process the
        initial message (that's left to the frontend via the normal
        ``/chat/threads/{id}/messages`` flow so the user sees instant
        feedback).

        Returns:
            ``{"thread_id": ..., "initial_message": ...}`` or *None*.
        """
        report = self._report_store.get_report(report_id)
        if not report:
            return None

        # If thread already exists, return it (no initial_message needed)
        if report.get("thread_id"):
            return {"thread_id": report["thread_id"], "initial_message": ""}

        from src.web.dependencies import get_agent_service
        from src.web.schemas.chat import ThreadContext

        # Build context for the thread
        context = ThreadContext(
            symbol=report["symbol"],
            mode="stock",
            intel_item_ids=report.get("intel_item_ids", []),
        )

        # Build initial message from report
        stock_name = report.get("stock_name", report["symbol"])
        signal = report.get("signal", "neutral")
        action = report.get("action", "hold")
        summary = report.get("summary", "")

        message = (
            f"请对 {stock_name}({report['symbol']}) 进行深度分析。\n\n"
            f"情报分析摘要:\n"
            f"- 信号: {signal} / 操作建议: {action}\n"
            f"- {summary}\n\n"
            f"请进一步分析该股票的技术面、资金面和基本面，给出更详细的操作建议。"
        )

        title = f"深度分析: {stock_name}({report['symbol']})"

        agent_service = get_agent_service()
        thread_id = agent_service.create_thread_only(
            title=title,
            context=context,
        )

        # Link thread to report
        self._report_store.link_thread(report_id, thread_id)
        return {"thread_id": thread_id, "initial_message": message}
