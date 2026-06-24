"""Celery task for thesis lifecycle automation — daily post-market.

Runs at 15:35 CST on trading days and performs:
  1. Daily conviction decay on all active/weakening theses
  2. Expiry check (expires_at < now → expired)
  3. Invalidation check (price/volume breach of invalidation_condition)
  4. Stale thesis cleanup (active > thesis_decay_hours AND conviction < 0.3)
  5. Summary message to MessageStore
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from openclaw.celery_app import app

logger = logging.getLogger(__name__)

# Regex to extract a numeric value following a keyword
_NUM_RE = re.compile(r"[\d]+(?:\.[\d]+)?")


def _load_config() -> dict:
    """Load thesis-related config from trading_loop.yaml."""
    from src.utils.config import load_config

    try:
        cfg = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        cfg = {}
    return {
        "thesis_decay_hours": cfg.get("thesis_decay_hours", 72),
        "thesis_decay_rate": cfg.get("thesis_decay_rate", 0.05),
    }


def _is_trading_day() -> bool:
    from openclaw.timeline_scheduler import TimelineScheduler

    return TimelineScheduler().is_trading_day()


def _get_thesis_tracker():
    from src.agent_loop.thesis_tracker import ThesisTracker

    return ThesisTracker()


def _get_message_store():
    from src.web.services.message_store import MessageStore

    return MessageStore()


def _get_realtime_price(symbol: str) -> float | None:
    """Fetch current price for a symbol. Returns None on failure."""
    try:
        from src.data.realtime import RealtimeQuoteManager

        mgr = RealtimeQuoteManager()
        df = mgr.get_quotes([symbol])
        if df is not None and not df.empty:
            row = df.iloc[0]
            price = row.get("price") or row.get("close")
            if price and float(price) > 0:
                return float(price)
    except Exception:
        logger.debug("Failed to fetch realtime price for %s", symbol, exc_info=True)
    return None


def _extract_price_threshold(text: str, keyword: str) -> float | None:
    """Extract a numeric threshold following a keyword in Chinese/English text."""
    lower = text.lower()
    idx = lower.find(keyword.lower())
    if idx < 0:
        return None
    after = text[idx + len(keyword) :]
    match = _NUM_RE.search(after)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


def _check_invalidation_condition(thesis, current_price: float | None) -> str | None:
    """Check if invalidation condition is met.

    Returns a reason string if invalidated, None otherwise.
    """
    if not thesis.invalidation_condition or current_price is None:
        return None

    condition = thesis.invalidation_condition

    # Price drop below threshold: "跌破 XX 元" / "price below XX"
    for kw in ("跌破", "price below", "below "):
        threshold = _extract_price_threshold(condition, kw)
        if threshold is not None and current_price < threshold:
            return f"价格 {current_price:.2f} 已跌破阈值 {threshold:.2f}"

    # Price rise above threshold (short theses): "突破 XX" / "price above XX"
    if thesis.direction in ("short", "bearish"):
        for kw in ("突破", "price above", "above "):
            threshold = _extract_price_threshold(condition, kw)
            if threshold is not None and current_price > threshold:
                return f"价格 {current_price:.2f} 已突破阈值 {threshold:.2f}"

    return None


@app.task(
    name="openclaw.tasks.thesis_lifecycle.task_thesis_lifecycle",
    soft_time_limit=120,
    time_limit=180,
)
def task_thesis_lifecycle() -> dict:
    """Daily post-market thesis lifecycle check (15:35 CST).

    Steps:
      1. Apply daily conviction decay
      2. Expire overdue theses
      3. Check invalidation conditions against live prices
      4. Clean up stale low-conviction theses
      5. Write summary message
    """
    if not _is_trading_day():
        logger.debug("Not a trading day — skipping thesis lifecycle")
        return {"skipped": True, "reason": "not_trading_day"}

    cfg = _load_config()
    tracker = _get_thesis_tracker()
    store = _get_message_store()
    now = datetime.now(timezone.utc)

    stats = {
        "active": 0,
        "decayed": 0,
        "expired": 0,
        "invalidated": 0,
        "stale_cleaned": 0,
    }

    # ── 1. Daily decay ──────────────────────────────────────────────
    # Override per-thesis decay_rate with the global config value so that
    # the configured rate (default 5%) is applied uniformly.
    active_theses = tracker.get_active_theses()
    stats["active"] = len(active_theses)

    decay_rate = cfg["thesis_decay_rate"]
    changed = []
    with tracker._connect() as conn:
        for thesis in active_theses:
            old_conf = thesis.current_confidence
            thesis.current_confidence = max(0.0, thesis.current_confidence - decay_rate)
            old_status = thesis.status
            thesis.status = tracker._compute_status(thesis)
            tracker._save_thesis(thesis, conn)

            if thesis.current_confidence != old_conf:
                stats["decayed"] += 1

            if thesis.status != old_status:
                changed.append(thesis)
                logger.info(
                    "Thesis %s (%s) decayed: conf %.2f→%.2f, status %s→%s",
                    thesis.id[:8],
                    thesis.symbol,
                    old_conf,
                    thesis.current_confidence,
                    old_status,
                    thesis.status,
                )

    # ── 1.5. Daily conviction snapshots (v70 cross-day evolution) ────
    for thesis in active_theses:
        if thesis.status in ("invalidated", "realized"):
            continue
        price = _get_realtime_price(thesis.symbol)
        pnl_pct = None
        if price and thesis.evidence:
            # Try to compute PnL from evidence (entry price in first evidence)
            try:
                entry = float(
                    thesis.evidence[0].get("entry_price", 0)
                    or thesis.entry_condition.split()[-1]
                )
                if entry > 0:
                    pnl_pct = (price - entry) / entry * 100
            except (ValueError, IndexError, TypeError, AttributeError):
                pass
        try:
            tracker.snapshot_daily(thesis.id, pnl_pct)
        except Exception as exc:
            logger.debug("Snapshot failed for %s: %s", thesis.id[:8], exc)

    # ── 2. Expiry check ─────────────────────────────────────────────
    # Re-fetch after decay may have changed statuses
    active_theses = tracker.get_active_theses()
    expired_theses = []
    with tracker._connect() as conn:
        for thesis in active_theses:
            if thesis.expires_at <= now:
                thesis.status = "invalidated"
                thesis.resolved_at = now
                thesis.resolved_reason = "论点到期（已超过有效期限）"
                tracker._save_thesis(thesis, conn)
                expired_theses.append(thesis)
                stats["expired"] += 1
                logger.info(
                    "Thesis %s (%s) expired at %s",
                    thesis.id[:8],
                    thesis.symbol,
                    thesis.expires_at.isoformat(),
                )

    # Create messages for expired theses
    for thesis in expired_theses:
        store.create_message(
            symbol=thesis.symbol,
            msg_type="thesis_expired",
            title=f"论点过期: {thesis.narrative[:40]}",
            summary=f"论点过期: {thesis.narrative} — 建议平仓 {thesis.symbol}",
            content=(
                f"## 论点过期通知\n\n"
                f"**股票**: {thesis.symbol}\n"
                f"**论点**: {thesis.narrative}\n"
                f"**创建时间**: {thesis.created_at.isoformat()}\n"
                f"**过期时间**: {thesis.expires_at.isoformat()}\n"
                f"**最终置信度**: {thesis.current_confidence:.0%}\n\n"
                f"论点已超过有效期限，建议评估是否平仓。"
            ),
            priority="high",
            action_advice=f"建议平仓 {thesis.symbol}，论点已失效",
            risk_note="持仓缺乏有效论点支撑，风险敞口无保护",
        )

    # ── 3. Invalidation check ───────────────────────────────────────
    active_theses = tracker.get_active_theses()
    invalidated_theses = []
    for thesis in active_theses:
        if not thesis.invalidation_condition:
            continue

        price = _get_realtime_price(thesis.symbol)
        reason = _check_invalidation_condition(thesis, price)
        if reason:
            tracker.invalidate_thesis(thesis.id, reason)
            invalidated_theses.append((thesis, reason))
            stats["invalidated"] += 1
            logger.info(
                "Thesis %s (%s) invalidated: %s",
                thesis.id[:8],
                thesis.symbol,
                reason,
            )

    # Create messages for invalidated theses
    for thesis, reason in invalidated_theses:
        store.create_message(
            symbol=thesis.symbol,
            msg_type="thesis_invalidated",
            title=f"论点失效: {thesis.narrative[:40]}",
            summary=f"论点失效: {thesis.narrative} — 原因: {reason}",
            content=(
                f"## 论点失效通知\n\n"
                f"**股票**: {thesis.symbol}\n"
                f"**论点**: {thesis.narrative}\n"
                f"**失效原因**: {reason}\n"
                f"**失效条件**: {thesis.invalidation_condition}\n"
                f"**当前置信度**: {thesis.current_confidence:.0%}\n\n"
                f"论点已被市场数据否定，建议立即平仓。"
            ),
            priority="critical",
            action_advice=f"立即平仓 {thesis.symbol}，论点已被否定",
            risk_note="继续持有缺乏论点支撑，下行风险加大",
        )

    # ── 4. Stale thesis cleanup ─────────────────────────────────────
    decay_hours = cfg["thesis_decay_hours"]
    stale_cutoff = 0.3
    active_theses = tracker.get_active_theses()
    stale_theses = []
    with tracker._connect() as conn:
        for thesis in active_theses:
            age_hours = (now - thesis.created_at).total_seconds() / 3600
            if age_hours > decay_hours and thesis.current_confidence < stale_cutoff:
                thesis.status = "invalidated"
                thesis.resolved_at = now
                thesis.resolved_reason = (
                    f"陈旧清理: 已持续 {age_hours:.0f}h, "
                    f"置信度仅 {thesis.current_confidence:.0%}"
                )
                tracker._save_thesis(thesis, conn)
                stale_theses.append(thesis)
                stats["stale_cleaned"] += 1
                logger.info(
                    "Thesis %s (%s) stale-cleaned: age=%.0fh, conf=%.2f",
                    thesis.id[:8],
                    thesis.symbol,
                    age_hours,
                    thesis.current_confidence,
                )

    # Create messages for stale-cleaned theses
    for thesis in stale_theses:
        store.create_message(
            symbol=thesis.symbol,
            msg_type="thesis_expired",
            title=f"论点清理: {thesis.narrative[:40]}",
            summary=(
                f"论点长期低置信度已自动清理: {thesis.narrative} — "
                f"建议平仓 {thesis.symbol}"
            ),
            priority="high",
            action_advice=f"建议平仓 {thesis.symbol}，论点已长期衰减",
            risk_note="论点置信度长期低于阈值，持仓缺乏支撑",
        )

    # ── 5. Summary message ──────────────────────────────────────────
    remaining_active = len(tracker.get_active_theses())
    summary_text = (
        f"论点生命周期检查: {remaining_active} 活跃, "
        f"{stats['decayed']} 衰减, "
        f"{stats['expired']} 过期, "
        f"{stats['invalidated']} 失效"
    )
    if stats["stale_cleaned"]:
        summary_text += f", {stats['stale_cleaned']} 陈旧清理"

    store.create_message(
        msg_type="thesis_review",
        title="论点生命周期每日检查",
        summary=summary_text,
        content=(
            f"## 论点生命周期每日检查\n\n"
            f"- **活跃论点**: {remaining_active}\n"
            f"- **今日衰减**: {stats['decayed']}\n"
            f"- **今日过期**: {stats['expired']}\n"
            f"- **今日失效**: {stats['invalidated']}\n"
            f"- **陈旧清理**: {stats['stale_cleaned']}\n"
        ),
        priority="low",
        data_freshness="batch",
    )

    logger.info("Thesis lifecycle complete: %s", stats)
    return stats
