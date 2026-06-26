"""Tests for the shared DataSourceRouter — single source of health truth (#49).

The daily fetcher, realtime, and news previously each held their own router, so
health was fragmented and the /admin view showed an empty per-request router.
These tests lock in that they now share one instance and the fetcher cascade
records into it.
"""

from __future__ import annotations

from src.data.source_router import (
    SourceDomain,
    get_source_router,
    reset_source_router,
)


def test_get_source_router_returns_singleton():
    reset_source_router()
    assert get_source_router() is get_source_router()


def test_reset_rebuilds_a_fresh_router():
    a = get_source_router()
    reset_source_router()
    assert get_source_router() is not a


def test_fetcher_uses_the_shared_router():
    reset_source_router()
    from src.data.fetcher import StockDataFetcher

    fetcher = StockDataFetcher()
    assert fetcher._source_router is get_source_router()


def test_fetcher_recording_propagates_to_shared_router():
    reset_source_router()
    from src.data.fetcher import StockDataFetcher

    fetcher = StockDataFetcher()
    router = get_source_router()

    # 3 consecutive failures marks the source DOWN (unavailable)...
    for _ in range(3):
        fetcher._record_source(SourceDomain.TENCENT, False)
    assert router.is_source_available(SourceDomain.TENCENT) is False

    # ...and a success recovers it — visible on the same shared instance.
    fetcher._record_source(SourceDomain.TENCENT, True)
    assert router.is_source_available(SourceDomain.TENCENT) is True


def test_record_source_never_raises():
    """Health bookkeeping must never break a fetch, even on a bad domain."""
    reset_source_router()
    from src.data.fetcher import StockDataFetcher

    fetcher = StockDataFetcher()
    fetcher._source_router = None  # simulate a broken router
    fetcher._record_source(SourceDomain.QMT, True)  # must not raise
