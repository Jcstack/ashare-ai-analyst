"""Orchestration service for smart stock recommendations.

Coordinates screener -> LLM review -> persistence -> notification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from src.recommendation.models import Recommendation
from src.recommendation.rec_store import RecStore
from src.recommendation.review_agent import ReviewAgent
from src.recommendation.screener import StockScreener
from src.web.services.user_config_service import UserConfigService

logger = logging.getLogger(__name__)

NOTIFICATIONS_KEY = "notifications:alerts"
MAX_NOTIFICATIONS = 200


class RecommendationService:
    """Orchestrates stock recommendation generation and retrieval."""

    def __init__(
        self,
        rec_store: RecStore,
        screener: StockScreener,
        review_agent: ReviewAgent,
        user_config_service: UserConfigService,
        redis_client: Any | None = None,
        *,
        info_store: Any | None = None,
        realtime_quote_manager: Any | None = None,
        macro_radar: Any | None = None,
        report_store: Any | None = None,
    ) -> None:
        self._store = rec_store
        self._screener = screener
        self._agent = review_agent
        self._user_config = user_config_service
        self._redis = redis_client
        self._info_store = info_store
        self._quote_manager = realtime_quote_manager
        self._macro_radar = macro_radar
        self._report_store = report_store
        # Intel chain engine (I-089 Phase 2) — lazy init
        self._intel_chain: Any | None = None

    # ── Run status tracking (Redis-based) ──────────────────────────

    def start_run(self, session: str, styles: list[str]) -> str | None:
        """Create a new run record in Redis. Returns run_id or None if Redis unavailable."""
        if not self._redis:
            return None
        run_id = str(uuid.uuid4())
        fields: dict[str, str] = {
            "status": "running",
            "session": session,
            "styles": json.dumps(styles),
            "started_at": str(time.time()),
        }
        self._update_run_status(run_id, fields)
        try:
            self._redis.set("rec:latest_run", run_id, ex=86400)
        except Exception:
            pass
        return run_id

    def complete_run(self, run_id: str | None, total_recs: int) -> None:
        """Mark a run as completed."""
        if not run_id:
            return
        self._update_run_status(
            run_id,
            {
                "status": "completed",
                "completed_at": str(time.time()),
                "total_recs": str(total_recs),
            },
        )
        # Set cooldown only on successful completion with results
        if self._redis and total_recs > 0:
            try:
                self._redis.setex("rec:refresh_cooldown", 300, "1")
            except Exception:
                pass

    def fail_run(self, run_id: str | None, error_msg: str) -> None:
        """Mark a run as failed."""
        if not run_id:
            return
        self._update_run_status(
            run_id,
            {
                "status": "failed",
                "completed_at": str(time.time()),
                "error": error_msg,
            },
        )
        # Clear cooldown so user can retry immediately after failure
        if self._redis:
            try:
                self._redis.delete("rec:refresh_cooldown")
            except Exception:
                pass

    def _update_run_status(self, run_id: str, fields: dict[str, str]) -> None:
        """Write fields to the run hash. Never raises."""
        if not self._redis:
            return
        key = f"rec:run:{run_id}"
        try:
            self._redis.hset(key, mapping=fields)
            self._redis.expire(key, 600)
        except Exception as exc:
            logger.warning("Failed to update run status %s: %s", run_id, exc)

    def get_run_status(self, run_id: str | None = None) -> dict[str, Any]:
        """Read run status from Redis. Falls back to latest_run if no run_id."""
        if not self._redis:
            return {"status": "unknown", "error": "Redis unavailable"}
        try:
            if not run_id:
                run_id = self._redis.get("rec:latest_run")
            if not run_id:
                return {"status": "unknown", "error": "no_run_found"}

            data = self._redis.hgetall(f"rec:run:{run_id}")
            if not data:
                return {"status": "unknown", "run_id": run_id, "error": "run_expired"}

            status = data.get("status", "unknown")

            # Gap B: detect stale "running" runs (hard-killed by Celery time_limit)
            if status == "running":
                started_at = data.get("started_at")
                if started_at:
                    try:
                        elapsed = time.time() - float(started_at)
                        if elapsed > 1020:  # 17 min > time_limit(960s) + buffer
                            status = "failed"
                            data["error"] = "timeout (stale)"
                    except (ValueError, TypeError):
                        pass

            result: dict[str, Any] = {
                "run_id": run_id,
                "status": status,
                "session": data.get("session"),
                "total_recs": int(data["total_recs"]) if "total_recs" in data else None,
                "error": data.get("error"),
            }

            # Parse per-style details
            styles_raw = data.get("styles")
            if styles_raw:
                try:
                    style_keys = json.loads(styles_raw)
                except (json.JSONDecodeError, TypeError):
                    style_keys = []
                style_details: dict[str, Any] = {}
                for s in style_keys:
                    prefix = f"style:{s}:"
                    detail: dict[str, str | None] = {
                        "status": data.get(f"{prefix}status"),
                        "reason": data.get(f"{prefix}reason"),
                        "count": data.get(f"{prefix}count"),
                    }
                    # Only include if any field was set
                    if any(v is not None for v in detail.values()):
                        style_details[s] = detail
                if style_details:
                    result["style_details"] = style_details

            return result
        except Exception as exc:
            logger.warning("Failed to read run status: %s", exc)
            return {"status": "unknown", "error": str(exc)}

    # ── Core generation ──────────────────────────────────────────

    def generate_recommendations(
        self,
        style: str,
        session: str,
        run_id: str | None = None,
        timeout: float = 480.0,
    ) -> list[Recommendation]:
        """Generate recommendations: screen -> sector boost -> LLM review -> save -> notify.

        Args:
            style: Investment style key.
            session: Trading session identifier.
            run_id: Optional run tracking ID for status updates.
            timeout: Wall-clock budget in seconds for the entire generation.

        Returns:
            List of generated Recommendation objects.

        Raises:
            TimeoutError: If wall-clock budget is exceeded.
        """
        deadline = time.time() + timeout
        logger.info(
            "Generating recommendations: style=%s, session=%s, timeout=%.0fs",
            style,
            session,
            timeout,
        )

        if run_id:
            self._update_run_status(run_id, {f"style:{style}:status": "running"})

        # Load user config for blacklist and sector preferences
        user_style_config = self._user_config.get_investment_style_config()
        blacklist = set(user_style_config.get("blacklist", []))

        # Step 1: Screen candidates
        try:
            candidates = self._screener.screen(style, blacklist=blacklist)
        except Exception as exc:
            logger.error("Screening failed for style=%s: %s", style, exc)
            if run_id:
                self._update_run_status(
                    run_id,
                    {
                        f"style:{style}:status": "failed",
                        f"style:{style}:reason": str(exc)[:200],
                    },
                )
            raise

        if not candidates:
            logger.info("No candidates found for style=%s", style)
            if run_id:
                self._update_run_status(
                    run_id,
                    {
                        f"style:{style}:status": "empty",
                        f"style:{style}:reason": "no_candidates",
                    },
                )
            return []

        if time.time() > deadline:
            raise TimeoutError(f"Timeout after screening ({timeout:.0f}s budget)")

        # Step 1b: Apply sector preference boost + anti-filter-bubble
        preferred_sectors = user_style_config.get("sector_preferences", [])
        if preferred_sectors:
            candidates = self._screener.apply_sector_preferences(
                candidates, preferred_sectors
            )

        # Step 1c: Build context for LLM review
        market_context = self._build_market_context(session, style=style)
        sector_stats = self._screener._precompute_sector_stats(
            self._screener._fetch_market_snapshot()
            if self._screener._snapshot_cache is None
            else self._screener._snapshot_cache[1]
        )
        news_context = self._fetch_news_context(candidates, deadline=deadline)

        # Step 1d: Build intel/macro context for LLM (I-089)
        intel_context = self._build_intel_context(candidates, deadline=deadline)

        if time.time() > deadline:
            raise TimeoutError(f"Timeout after context build ({timeout:.0f}s budget)")

        # Step 2: LLM review with enriched context
        # Pass remaining time budget to prevent Celery timeout (I-074)
        llm_budget = max(deadline - time.time(), 15.0)
        recs = self._agent.review_candidates(
            candidates,
            style,
            session,
            market_context=market_context,
            sector_stats=sector_stats,
            news_context=news_context,
            intel_context=intel_context,
            time_budget=llm_budget,
            run_id=run_id,
        )
        if not recs:
            logger.info("No recommendations after LLM review for style=%s", style)
            if run_id:
                self._update_run_status(
                    run_id,
                    {
                        f"style:{style}:status": "empty",
                        f"style:{style}:reason": "all_rejected",
                    },
                )
            return []

        # Step 3: Persist
        self._store.save_batch(recs)
        logger.info("Saved %d recommendations for style=%s", len(recs), style)

        # Step 4: Push notification
        self._push_notification(recs, session=session)

        if run_id:
            self._update_run_status(
                run_id,
                {
                    f"style:{style}:status": "done",
                    f"style:{style}:count": str(len(recs)),
                },
            )

        return recs

    def get_recommendations(
        self,
        *,
        style: str | None = None,
        session: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get active recommendations with optional filters.

        Deduplicates by symbol — keeps the highest-scoring record per stock.
        """
        # Over-fetch to have enough after dedup, then trim
        recs = self._store.get_recommendations(
            style=style, session=session, limit=limit * 3, status="active"
        )
        result = self._deduplicate_by_symbol(recs)[:limit]
        return self._enrich_with_current_prices(result)

    def get_today_recommendations(
        self, *, style: str | None = None
    ) -> list[dict[str, Any]]:
        """Get today's recommendations (deduplicated by symbol)."""
        recs = self._store.get_today_recommendations(style=style)
        result = self._deduplicate_by_symbol(recs)
        return self._enrich_with_current_prices(result)

    # Numeric confidence mapping for downstream signal consumers
    # (the agent loop's SignalAggregator expects a float in [0, 1]).
    _CONFIDENCE_SCORE: dict[str, float] = {
        "high": 0.85,
        "medium": 0.55,
        "low": 0.3,
    }

    def get_latest_recommendations(self) -> list[dict[str, Any]]:
        """Return today's recommendations shaped for the agent signal feed.

        The agent loop's ``SignalAggregator.add_from_recommendation`` expects a
        ``reasoning`` key and a numeric ``confidence`` in ``[0, 1]``, whereas the
        backend rec dicts use ``reason`` and a categorical ``confidence``
        (``"high"``/``"medium"``/``"low"``). This adapter bridges the two shapes
        so the recommendation signal source feeds the trading loop.
        """
        recs = self.get_today_recommendations()
        feed: list[dict[str, Any]] = []
        for rec in recs:
            raw_conf = rec.get("confidence")
            if isinstance(raw_conf, int | float):
                confidence = float(raw_conf)
            else:
                confidence = self._CONFIDENCE_SCORE.get(str(raw_conf).lower(), 0.0)
            feed.append(
                {
                    "symbol": rec.get("symbol"),
                    "name": rec.get("name", ""),
                    "score": rec.get("score"),
                    "confidence": confidence,
                    "reasoning": rec.get("reason", ""),
                    "entry_price": rec.get("entry_price"),
                    "target_price": rec.get("target_price"),
                    "stop_loss": rec.get("stop_loss"),
                }
            )
        return feed

    def get_user_style(self) -> str:
        """Get user's preferred investment style."""
        raw = self._user_config.get("investment_style")
        return raw if raw else "value"

    def set_user_style(self, style: str) -> None:
        """Set user's preferred investment style."""
        self._user_config.set("investment_style", style)

    def get_full_preferences(self) -> dict:
        """Get full investment style configuration."""
        return self._user_config.get_investment_style_config()

    def update_full_preferences(self, config: dict) -> dict:
        """Update full investment style configuration."""
        return self._user_config.update_investment_style_config(config)

    def get_performance_stats(
        self,
        *,
        style: str | None = None,
        session: str | None = None,
        days: int = 90,
    ) -> dict[str, Any]:
        """Get aggregated performance statistics."""
        return self._store.get_performance_stats(
            style=style, session=session, days=days
        )

    def preflight_refresh(self) -> dict[str, Any]:
        """Quick pre-checks for manual refresh: cooldown + session + styles.

        Returns ``{"status": "ok", "session": ..., "styles": [...]}`` when ready,
        or an error/cooldown dict otherwise.  This is designed to be fast (<100ms)
        so the API can return 202 and dispatch the heavy work to Celery.
        """
        cooldown_key = "rec:refresh_cooldown"

        # Check cooldown
        if self._redis:
            try:
                existing = self._redis.get(cooldown_key)
                if existing:
                    return {
                        "status": "cooldown",
                        "message": "请等待5分钟后再次刷新",
                        "retry_after": self._redis.ttl(cooldown_key),
                    }
            except Exception as exc:
                logger.warning("Redis cooldown check failed: %s", exc)

        # Determine current session (always returns a value — "anytime" fallback)
        from openclaw.tasks.recommendation_pipeline import _current_session

        session = _current_session()

        # Get user styles
        style_config = self._user_config.get_investment_style_config()
        styles = style_config.get("styles", ["value"])

        # Start run tracking
        run_id = self.start_run(session, styles)

        return {"status": "ok", "session": session, "styles": styles, "run_id": run_id}

    def manual_refresh(self) -> dict[str, Any]:
        """Synchronous manual refresh (used by Celery task, not API).

        Returns dict with status and total count.
        """
        preflight = self.preflight_refresh()
        if preflight.get("status") != "ok":
            return preflight

        session = preflight["session"]
        styles = preflight["styles"]
        run_id = preflight.get("run_id")

        total = 0
        errors: list[str] = []
        for style in styles:
            try:
                recs = self.generate_recommendations(style, session, run_id=run_id)
                total += len(recs)
            except Exception as exc:
                logger.error("Manual refresh failed for style=%s: %s", style, exc)
                errors.append(f"{style}: {exc}")

        if errors and total == 0:
            self.fail_run(run_id, f"All styles failed: {'; '.join(errors)[:200]}")
        else:
            self.complete_run(run_id, total)

        return {
            "status": "ok",
            "session": session,
            "total": total,
        }

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        """Get a single recommendation by ID."""
        rec = self._store.get_recommendation(rec_id)
        if rec:
            enriched = self._enrich_with_current_prices([rec])
            return enriched[0]
        return rec

    def count_today_active(self) -> int:
        """Count today's active recommendations (for unread badge)."""
        return self._store.count_today_active()

    def dismiss(self, rec_id: str) -> bool:
        """Dismiss a recommendation."""
        return self._store.dismiss_recommendation(rec_id)

    def _enrich_with_current_prices(
        self, recs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Attach market prices to recommendation dicts (best-effort).

        Always fetches quotes (live during trading, closing price after hours).
        Adds ``current_price``, ``current_pct_change``, ``price_vs_entry``,
        and ``market_open`` to each record when a quote is available.
        Never raises — failures are logged and silently skipped.
        """
        if not self._quote_manager or not recs:
            return recs

        try:
            from src.utils.market_hours import is_a_share_trading_open

            market_open = is_a_share_trading_open()

            symbols = list({r["symbol"] for r in recs if r.get("symbol")})
            if not symbols:
                return recs

            df = self._quote_manager.get_quotes(symbols)
            if df is None or df.empty:
                for r in recs:
                    r["market_open"] = market_open
                return recs

            # Build a quick lookup: symbol -> row dict
            price_map: dict[str, dict[str, float | None]] = {}
            for _, row in df.iterrows():
                sym = str(row.get("symbol", ""))
                price = row.get("price")
                if sym and price and float(price) > 0:
                    price_map[sym] = {
                        "current_price": round(float(price), 2),
                        "current_pct_change": (
                            round(float(row["pct_change"]), 2)
                            if row.get("pct_change") is not None
                            else None
                        ),
                    }

            for r in recs:
                r["market_open"] = market_open
                quote = price_map.get(r.get("symbol", ""))
                if quote:
                    r["current_price"] = quote["current_price"]
                    r["current_pct_change"] = quote["current_pct_change"]
                    entry = r.get("entry_price")
                    if entry and quote["current_price"]:
                        r["price_vs_entry"] = round(
                            (quote["current_price"] - float(entry))
                            / float(entry)
                            * 100,
                            2,
                        )
        except Exception as exc:
            logger.warning("Failed to enrich recommendations with live prices: %s", exc)

        return recs

    @staticmethod
    def _deduplicate_by_symbol(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the highest-scoring record per symbol.

        Input is assumed to be sorted by score DESC (from RecStore).
        """
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for rec in recs:
            symbol = rec.get("symbol")
            if symbol not in seen:
                seen.add(symbol)
                result.append(rec)
        return result

    def _build_market_context(
        self, session: str, *, style: str | None = None
    ) -> str | None:
        """Build a market background paragraph from sector stats.

        Returns a short text describing current session, overall direction,
        top/bottom sectors, and historical win rate feedback for the LLM.
        """
        try:
            snapshot = (
                self._screener._snapshot_cache[1]
                if self._screener._snapshot_cache
                else self._screener._fetch_market_snapshot()
            )
            sector_stats = self._screener._precompute_sector_stats(snapshot)
            if not sector_stats:
                return None

            session_labels = {
                "pre_market": "盘前",
                "early": "早盘",
                "mid": "盘中",
                "late": "尾盘",
                "post_market": "盘后",
            }
            session_label = session_labels.get(session, session)

            # Overall market direction from sector averages
            all_changes = [s["avg_change_pct"] for s in sector_stats.values()]
            if all_changes:
                avg_market = sum(all_changes) / len(all_changes)
                if avg_market > 0.5:
                    direction = "整体上涨"
                elif avg_market < -0.5:
                    direction = "整体下跌"
                else:
                    direction = "震荡整理"
            else:
                direction = "未知"

            # Top/bottom sectors
            sorted_sectors = sorted(
                sector_stats.items(), key=lambda x: x[1]["avg_change_pct"], reverse=True
            )
            top3 = [f"{s}({v['avg_change_pct']:+.1f}%)" for s, v in sorted_sectors[:3]]
            bot3 = [f"{s}({v['avg_change_pct']:+.1f}%)" for s, v in sorted_sectors[-3:]]

            context = (
                f"当前时段: {session_label}\n"
                f"大盘方向: {direction}\n"
                f"活跃板块: {', '.join(top3)}\n"
                f"低迷板块: {', '.join(bot3)}"
            )

            # Append historical performance feedback (I-089 Phase 3)
            if style:
                try:
                    win_rates = self._store.get_style_win_rates(days=30)
                    wr = win_rates.get(style)
                    if wr and wr.get("count", 0) >= 5:
                        context += (
                            f"\n历史表现反馈 ({style}, 近30天):\n"
                            f"  T+1胜率: {wr['win_rate_t1']:.0%} "
                            f"(平均收益: {wr['avg_return_t1']:+.2f}%, "
                            f"样本: {wr['count']}次)"
                        )
                        if (
                            wr.get("win_rate_t1") is not None
                            and wr["win_rate_t1"] < 0.4
                        ):
                            context += "\n  ⚠ 近期胜率偏低，请提高筛选标准"
                except Exception:
                    pass

            return context
        except Exception as exc:
            logger.warning("Failed to build market context: %s", exc)
            return None

    def _fetch_news_context(
        self,
        candidates: list[Any],
        deadline: float | None = None,
    ) -> dict[str, list[str]] | None:
        """Fetch recent news headlines for candidate symbols from InfoStore.

        Returns a map of symbol -> list of headline strings (max 3 per symbol).
        Uses a 10s internal deadline (or the provided external deadline, whichever
        is sooner) and returns partial results on timeout (graceful degradation).
        """
        if not self._info_store:
            return None

        # Use the sooner of 10s from now or the external deadline
        internal_deadline = time.time() + 10.0
        if deadline is not None:
            internal_deadline = min(internal_deadline, deadline)

        try:
            result: dict[str, list[str]] = {}
            for c in candidates:
                if time.time() > internal_deadline:
                    logger.info(
                        "News context fetch deadline reached after %d/%d symbols",
                        len(result),
                        len(candidates),
                    )
                    break
                items = self._info_store.get_feed(symbol=c.symbol, limit=3, days=7)
                if items:
                    result[c.symbol] = [
                        item.get("title", "") for item in items if item.get("title")
                    ]
            return result if result else None
        except Exception as exc:
            logger.warning("Failed to fetch news context: %s", exc)
            return None

    def _fetch_signal_context(
        self,
        symbol: str,
        signal_store: Any | None = None,
    ) -> dict[str, Any]:
        """Fetch signal context for a symbol from SignalStore.

        Gathers intel signals, macro signals, and news headlines
        to provide comprehensive context for recommendation review.

        Args:
            symbol: Stock code.
            signal_store: Optional SignalStore instance.

        Returns:
            Dict with intel_signals, macro_signals, and news keys.
        """
        context: dict[str, Any] = {
            "intel_signals": [],
            "macro_signals": [],
            "news": [],
        }

        if signal_store is None:
            return context

        try:
            # Intel-sourced signals for this specific stock
            intel = signal_store.get_signals(
                asset=symbol,
                signal_type="S7_POLICY_DRIVEN",
                days=1,
                limit=5,
            )
            context["intel_signals"] = [
                {
                    "summary": s.get("summary_short", ""),
                    "confidence": s.get("confidence_score", 0),
                    "timestamp": s.get("timestamp", ""),
                }
                for s in intel
            ]
        except Exception:
            logger.debug("Failed to fetch intel signals for %s", symbol)

        try:
            # Macro signals (affects all stocks)
            macro = signal_store.get_signals(
                signal_type="S8_MACRO_DRIVEN",
                days=1,
                limit=5,
            )
            context["macro_signals"] = [
                {
                    "summary": s.get("summary_short", ""),
                    "detail": s.get("summary_detailed", ""),
                    "confidence": s.get("confidence_score", 0),
                }
                for s in macro
            ]
        except Exception:
            logger.debug("Failed to fetch macro signals")

        return context

    def _build_intel_context(
        self,
        candidates: list[Any],
        deadline: float | None = None,
    ) -> str | None:
        """Build enriched intel context from macro radar + sector intel + reports (I-089).

        Gathers:
        1. Macro radar signals (global market anomalies, policy events)
        2. Sector/industry intel from InfoStore (not just per-symbol)
        3. Recent intel reports for candidate symbols

        Returns a formatted string for injection into the LLM system prompt,
        or None if no intel is available.
        """
        parts: list[str] = []
        internal_deadline = time.time() + 8.0
        if deadline is not None:
            internal_deadline = min(internal_deadline, deadline)

        # 1. Macro radar scan
        if self._macro_radar:
            try:
                macro_signals = self._macro_radar.scan()
                if macro_signals:
                    part = "### 宏观信号\n"
                    for sig in macro_signals[:5]:
                        summary = sig.get("summary_short", sig.get("summary", ""))
                        risk = sig.get("risk_level", "")
                        if summary:
                            part += f"- [{risk}] {summary}\n"
                    parts.append(part)
            except Exception as exc:
                logger.debug("Macro radar scan failed: %s", exc)

        if time.time() > internal_deadline:
            return "\n".join(parts) if parts else None

        # 2. Sector-level intel from InfoStore
        if self._info_store:
            try:
                # Collect unique sectors from candidates
                sectors = {c.sector for c in candidates if c.sector}
                if sectors:
                    sector_items = self._info_store.get_feed(
                        category="industry", limit=10, days=3
                    )
                    if sector_items:
                        # Filter to items related to candidate sectors
                        relevant = []
                        for item in sector_items:
                            title = item.get("title", "")
                            tags = item.get("tags", [])
                            # Match if any sector keyword appears in title or tags
                            tag_str = " ".join(tags) if tags else ""
                            for sector in sectors:
                                if sector and (sector in title or sector in tag_str):
                                    relevant.append(item)
                                    break
                        if relevant:
                            part = "### 行业情报\n"
                            for item in relevant[:5]:
                                title = item.get("title", "")
                                priority = item.get("priority", "normal")
                                part += f"- [{priority}] {title}\n"
                            parts.append(part)

                # Also fetch macro/policy news
                macro_items = self._info_store.get_feed(
                    category="macro", limit=5, days=2
                )
                policy_items = self._info_store.get_feed(
                    category="policy", limit=5, days=2
                )
                combined = (macro_items or []) + (policy_items or [])
                if combined:
                    part = "### 宏观与政策\n"
                    for item in combined[:5]:
                        title = item.get("title", "")
                        if title:
                            part += f"- {title}\n"
                    parts.append(part)
            except Exception as exc:
                logger.debug("Sector/macro intel fetch failed: %s", exc)

        if time.time() > internal_deadline:
            return "\n".join(parts) if parts else None

        # 3. Recent intel reports for candidate symbols
        if self._report_store:
            try:
                for c in candidates[:10]:
                    if time.time() > internal_deadline:
                        break
                    reports = self._report_store.get_reports(symbol=c.symbol, limit=1)
                    if reports:
                        r = reports[0]
                        signal = r.get("signal", "")
                        confidence = r.get("confidence", 0)
                        summary = r.get("summary", "")[:100]
                        if summary:
                            parts.append(
                                f"### 情报分析: {c.name} ({c.symbol})\n"
                                f"- 信号: {signal} (置信度: {confidence:.0%})\n"
                                f"- 摘要: {summary}\n"
                            )
            except Exception as exc:
                logger.debug("Intel report fetch failed: %s", exc)

        if time.time() > internal_deadline:
            return "\n".join(parts) if parts else None

        # 4. Intel chain traversal (I-089 Phase 2)
        try:
            if self._intel_chain is None:
                from src.intelligence_hub.intel_chain import IntelChainEngine

                self._intel_chain = IntelChainEngine(info_store=self._info_store)

            for c in candidates[:5]:
                if time.time() > internal_deadline:
                    break
                chain_result = self._intel_chain.trace(
                    c.symbol,
                    sector=c.sector,
                    max_hops=2,
                    deadline=internal_deadline,
                )
                context_str = chain_result.to_context_str(max_items=5)
                if context_str:
                    parts.append(context_str)
        except Exception as exc:
            logger.debug("Intel chain traversal failed: %s", exc)

        return "\n".join(parts) if parts else None

    def _push_notification(
        self, recs: list[Recommendation], *, session: str | None = None
    ) -> None:
        """Push notification via Redis with session toggle and dedup controls.

        FR-REC031/032: Checks session_toggles, enforces 1 push per session per day,
        enriches notification card with confidence and score.
        """
        if not self._redis or not recs:
            return

        try:
            # Check session toggle — skip if user disabled this session
            if session:
                user_config = self._user_config.get_investment_style_config()
                toggles = user_config.get("session_toggles", {})
                if not toggles.get(session, True):
                    logger.info(
                        "Notification skipped: session '%s' toggle off", session
                    )
                    return

                # Per-session dedup: max 1 push per session per day
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                dedup_key = f"rec:push:{session}:{today}"
                if self._redis.exists(dedup_key):
                    logger.info(
                        "Notification skipped: already pushed for %s today", session
                    )
                    return
                # Set dedup key with 24h TTL
                self._redis.setex(dedup_key, 86400, "1")

            styles_label = {
                "value": "价值投资",
                "growth": "成长投资",
                "momentum": "动量交易",
                "swing": "波段交易",
                "dividend": "红利收息",
                "sector": "板块轮动",
            }
            style = recs[0].style
            label = styles_label.get(style, style)
            top_names = ", ".join(r.name for r in recs[:3])
            top_rec = recs[0]

            notification = {
                "id": str(uuid.uuid4()),
                "type": "recommendation",
                "title": f"智能选股: {label}推荐 {len(recs)} 只",
                "summary": f"推荐标的: {top_names}",
                "symbol": top_rec.symbol,
                "timestamp": datetime.now(UTC).isoformat(),
                "read": False,
                "action": "/recommendations",
                # Enriched fields (FR-REC032)
                "confidence": top_rec.confidence,
                "score": top_rec.score,
                "entry_price": top_rec.entry_price,
                "session": session,
            }
            self._redis.lpush(
                NOTIFICATIONS_KEY,
                json.dumps(notification, ensure_ascii=False),
            )
            self._redis.ltrim(NOTIFICATIONS_KEY, 0, MAX_NOTIFICATIONS - 1)
        except Exception as exc:
            logger.warning("Failed to push recommendation notification: %s", exc)
