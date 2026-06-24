"""Daily outcome verification pipeline — the AI's feedback loop.

Runs post-market (16:30 CST) on trading days to:
1. Evaluate T+1/T+3/T+5 outcomes for pending signals via OutcomeTracker
2. Update ConfidenceCalibrator with completed outcomes
3. Update BayesianBelief likelihood tables from empirical data
3b. Validate factors via FactorValidator (IC ranking, decay detection, redundancy)
4. Flag theses whose T+3 outcomes turned negative
5. Generate a daily review message summarizing calibration changes

This is the single most critical pipeline for the agent's ability to
learn from its decisions. Without it, confidence scores remain static
and the agent cannot self-correct.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from openclaw.celery_app import app

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _is_trading_day() -> bool:
    """Check if today is a trading day."""
    from openclaw.timeline_scheduler import TimelineScheduler

    return TimelineScheduler().is_trading_day()


async def _fetch_closing_price(symbol: str, date_str: str) -> float | None:
    """Fetch closing price for a symbol on a given date.

    Uses DataFetcher to pull daily OHLCV data and extract the close price.
    Falls back to realtime quote if the historical fetch fails (e.g. for
    today's date before data providers update).

    Args:
        symbol: 6-digit stock code.
        date_str: Date in YYYY-MM-DD format.

    Returns:
        Closing price as float, or None if unavailable.
    """
    try:
        from src.data.fetcher import DataFetcher

        fetcher = DataFetcher()
        # Convert YYYY-MM-DD to YYYYMMDD for AKShare
        date_compact = date_str.replace("-", "")
        df = fetcher.fetch_daily_ohlcv(
            symbol,
            start_date=date_compact,
            end_date=date_compact,
        )
        if df is not None and not df.empty:
            close_col = "close" if "close" in df.columns else None
            if close_col and len(df) > 0:
                return float(df.iloc[-1][close_col])
    except Exception as exc:
        logger.debug("Historical fetch failed for %s on %s: %s", symbol, date_str, exc)

    # Fallback: try realtime quote (useful for today's date)
    try:
        from src.data.realtime import RealtimeQuoteManager

        rtm = RealtimeQuoteManager()
        df = rtm.get_quotes([symbol])
        if df is not None and not df.empty:
            price = float(df.iloc[0].get("price", 0))
            if price > 0:
                return price
    except Exception as exc:
        logger.debug("Realtime fallback failed for %s: %s", symbol, exc)

    return None


async def _evaluate_calibration_decisions() -> int:
    """Evaluate pending decisions in decisions.db for calibration loop.

    For each decision older than 1 day without T+1 price, fetch closing
    price and compute return + direction correctness.
    For each decision older than 3 days without T+3 price, do the same.

    Returns number of decisions updated.
    """
    import sqlite3
    from datetime import timedelta
    from pathlib import Path

    db_path = Path("data/decisions.db")
    if not db_path.exists():
        return 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    now = datetime.now(UTC)
    updated = 0

    try:
        rows = conn.execute(
            """SELECT proposal_id, symbol, action, entry_price, decided_at,
                      t1_price, t3_price, direction_correct
               FROM decisions
               WHERE entry_price IS NOT NULL
                 AND direction_correct IS NULL
                 AND decided_at >= datetime('now', '-30 days')
               ORDER BY decided_at ASC
               LIMIT 50"""
        ).fetchall()

        for row in rows:
            symbol = row["symbol"]
            entry_price = row["entry_price"]
            if not symbol or not entry_price:
                continue

            try:
                decided_at = datetime.fromisoformat(row["decided_at"])
            except (ValueError, TypeError):
                continue

            age_days = (now - decided_at.replace(tzinfo=UTC)).days
            changes = {}

            # T+1
            if row["t1_price"] is None and age_days >= 1:
                t1_date = (decided_at + timedelta(days=1)).strftime("%Y-%m-%d")
                price = await _fetch_closing_price(symbol, t1_date)
                if price and price > 0:
                    ret = (price - entry_price) / entry_price
                    changes["t1_price"] = price
                    changes["t1_return_pct"] = round(ret * 100, 2)

            # T+3
            if row["t3_price"] is None and age_days >= 3:
                t3_date = (decided_at + timedelta(days=3)).strftime("%Y-%m-%d")
                price = await _fetch_closing_price(symbol, t3_date)
                if price and price > 0:
                    ret = (price - entry_price) / entry_price
                    changes["t3_price"] = price
                    changes["t3_return_pct"] = round(ret * 100, 2)

                    # Direction correct at T+3
                    is_bullish = row["action"] in ("buy", "add")
                    is_bearish = row["action"] in ("sell", "reduce")
                    if is_bullish:
                        changes["direction_correct"] = 1 if ret > 0 else 0
                    elif is_bearish:
                        changes["direction_correct"] = 1 if ret < 0 else 0
                    else:
                        changes["direction_correct"] = 1 if abs(ret) < 0.03 else 0

            if changes:
                set_clause = ", ".join(f"{k} = ?" for k in changes)
                values = list(changes.values()) + [row["proposal_id"]]
                conn.execute(
                    f"UPDATE decisions SET {set_clause} WHERE proposal_id = ?",
                    values,
                )
                updated += 1

        conn.commit()
        if updated > 0:
            logger.info("Calibration decisions evaluated: %d updated", updated)
    except Exception as exc:
        logger.warning("Calibration decision evaluation failed: %s", exc)
    finally:
        conn.close()

    return updated


async def _update_decision_journal_outcomes() -> dict:
    """Update pending decision journal entries with T+1/T+3/T+5 outcomes.

    Reads pending entries from the decision_journal table in agent.db,
    fetches closing prices for the appropriate horizons, and updates
    outcome columns + status.

    Returns:
        Summary dict with counts of entries updated per horizon.
    """
    import sqlite3
    from pathlib import Path

    db_path = Path("data/agent.db")
    if not db_path.exists():
        logger.debug("agent.db not found, skipping journal outcome update")
        return {"t1": 0, "t3": 0, "t5": 0, "status_resolved": 0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    updated = {"t1": 0, "t3": 0, "t5": 0, "status_resolved": 0}

    try:
        rows = conn.execute(
            """
            SELECT id, symbol, timestamp, entry_price, action,
                   outcome_t1, outcome_t3, outcome_t5, outcome_status
            FROM decision_journal
            WHERE outcome_status = 'pending'
              AND symbol IS NOT NULL
              AND timestamp >= datetime('now', '-30 days')
            ORDER BY timestamp ASC
            """
        ).fetchall()

        if not rows:
            logger.debug("No pending decision journal entries to update")
            conn.close()
            return updated

        now = datetime.now(UTC)

        for row in rows:
            symbol = row["symbol"]
            try:
                decision_dt = datetime.fromisoformat(row["timestamp"])
            except (ValueError, TypeError):
                continue

            age_days = (now - decision_dt.replace(tzinfo=UTC)).days
            entry_price = row["entry_price"]

            # T+1: update if >= 1 day old and not yet filled
            if age_days >= 1 and row["outcome_t1"] is None:
                from datetime import timedelta

                t1_date = (decision_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                price = await _fetch_closing_price(symbol, t1_date)
                if price is not None and entry_price and entry_price > 0:
                    ret = (price - entry_price) / entry_price
                    conn.execute(
                        "UPDATE decision_journal SET outcome_t1 = ? WHERE id = ?",
                        (round(ret, 6), row["id"]),
                    )
                    updated["t1"] += 1

            # T+3: update if >= 3 days old and not yet filled
            if age_days >= 3 and row["outcome_t3"] is None:
                from datetime import timedelta

                t3_date = (decision_dt + timedelta(days=3)).strftime("%Y-%m-%d")
                price = await _fetch_closing_price(symbol, t3_date)
                if price is not None and entry_price and entry_price > 0:
                    ret = (price - entry_price) / entry_price
                    conn.execute(
                        "UPDATE decision_journal SET outcome_t3 = ? WHERE id = ?",
                        (round(ret, 6), row["id"]),
                    )
                    updated["t3"] += 1

            # T+5: update if >= 5 days old and not yet filled
            if age_days >= 5 and row["outcome_t5"] is None:
                from datetime import timedelta

                t5_date = (decision_dt + timedelta(days=5)).strftime("%Y-%m-%d")
                price = await _fetch_closing_price(symbol, t5_date)
                if price is not None and entry_price and entry_price > 0:
                    ret = (price - entry_price) / entry_price
                    conn.execute(
                        "UPDATE decision_journal SET outcome_t5 = ? WHERE id = ?",
                        (round(ret, 6), row["id"]),
                    )
                    updated["t5"] += 1

            # Resolve status once T+5 is available (or T+3 if old enough)
            # Re-read the row to get latest values after updates
            if age_days >= 5:
                cur = conn.execute(
                    "SELECT outcome_t1, outcome_t3, outcome_t5 "
                    "FROM decision_journal WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if cur and cur["outcome_t5"] is not None:
                    action_lower = (row["action"] or "buy").lower()
                    ret_t5 = cur["outcome_t5"]
                    if action_lower in ("buy", "add"):
                        status = "win" if ret_t5 > 0 else "loss"
                    elif action_lower in ("sell", "reduce"):
                        status = "win" if ret_t5 < 0 else "loss"
                    else:
                        status = "win" if abs(ret_t5) < 0.01 else "loss"
                    conn.execute(
                        "UPDATE decision_journal SET outcome_status = ? WHERE id = ?",
                        (status, row["id"]),
                    )
                    updated["status_resolved"] += 1

        conn.commit()
        logger.info(
            "Decision journal outcomes updated: t1=%d, t3=%d, t5=%d, resolved=%d",
            updated["t1"],
            updated["t3"],
            updated["t5"],
            updated["status_resolved"],
        )
    except Exception as exc:
        logger.warning("Failed to update decision journal outcomes: %s", exc)
    finally:
        conn.close()

    return updated


async def _validate_factors(outcomes: list) -> dict:
    """Run factor validation using completed outcome data.

    Records factor scores and returns from tracked signals into the
    FactorValidator, then runs validation/decay/redundancy checks.

    Args:
        outcomes: List of DecisionOutcome objects from OutcomeTracker.

    Returns:
        Summary dict with factor validation results.
    """
    from src.agent_loop.factor_validator import FactorValidator

    result: dict = {
        "factors_recorded": 0,
        "returns_recorded": 0,
        "factor_rankings": [],
        "decayed_factors": [],
        "redundant_pairs": [],
    }

    try:
        validator = FactorValidator()

        # ------------------------------------------------------------------
        # Step A: Record factor scores from signals that have source/confidence
        # ------------------------------------------------------------------
        # Use outcome source + confidence as proxy factor scores.
        # Each signal source acts as a "factor" whose predictive power we track.
        factor_score_rows: list[dict] = []
        return_rows: list[dict] = []

        for outcome in outcomes:
            if not outcome.symbol or not outcome.decided_price:
                continue

            # Record the confidence as a factor score keyed by source
            if hasattr(outcome, "source") and outcome.source:
                factor_score_rows.append(
                    {
                        "symbol": outcome.symbol,
                        "factor_name": f"source_{outcome.source}",
                        "score": outcome.decided_price,  # entry price as baseline
                    }
                )

            # Record the action confidence as a general factor
            if hasattr(outcome, "confidence") and outcome.confidence:
                factor_score_rows.append(
                    {
                        "symbol": outcome.symbol,
                        "factor_name": "confidence",
                        "score": outcome.confidence,
                    }
                )

            # Step B: Record T+5 returns for completed outcomes
            if outcome.t5_return_pct is not None:
                return_rows.append(
                    {
                        "symbol": outcome.symbol,
                        "return_pct": outcome.t5_return_pct / 100.0,  # pct → decimal
                    }
                )

        # Also pull factor scores from the decision journal (richer data)
        try:
            import json
            import sqlite3
            from pathlib import Path

            db_path = Path("data/agent.db")
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")

                journal_rows = conn.execute(
                    """
                    SELECT symbol, timestamp, confidence, action,
                           sentiment_phase, data_sources
                    FROM decision_journal
                    WHERE timestamp >= datetime('now', '-7 days')
                      AND symbol IS NOT NULL
                      AND confidence IS NOT NULL
                    """
                ).fetchall()

                for jrow in journal_rows:
                    try:
                        sym = jrow["symbol"]

                        # Confidence as factor
                        factor_score_rows.append(
                            {
                                "symbol": sym,
                                "factor_name": "journal_confidence",
                                "score": float(jrow["confidence"]),
                            }
                        )

                        # Sentiment phase as categorical factor (mapped to numeric)
                        phase = jrow["sentiment_phase"]
                        if phase:
                            phase_map = {
                                "fear": -1.0,
                                "despair": -0.5,
                                "hope": 0.5,
                                "euphoria": 1.0,
                                "neutral": 0.0,
                            }
                            score = phase_map.get(phase.lower(), 0.0)
                            factor_score_rows.append(
                                {
                                    "symbol": sym,
                                    "factor_name": "sentiment_phase",
                                    "score": score,
                                }
                            )

                        # Data source count as breadth factor
                        ds = jrow["data_sources"]
                        if ds:
                            try:
                                sources = json.loads(ds)
                                factor_score_rows.append(
                                    {
                                        "symbol": sym,
                                        "factor_name": "data_breadth",
                                        "score": float(len(sources)),
                                    }
                                )
                            except (json.JSONDecodeError, TypeError):
                                pass
                    except Exception:
                        continue

                conn.close()
        except Exception as exc:
            logger.debug("Journal factor extraction failed: %s", exc)

        # Batch record factor scores (grouped by date)
        if factor_score_rows:
            # Group by date from outcomes (use today as fallback)
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            await validator.record_factor_scores(today, factor_score_rows)
            result["factors_recorded"] = len(factor_score_rows)
            logger.info(
                "Recorded %d factor scores for validation", len(factor_score_rows)
            )

        # Batch record returns
        if return_rows:
            # Use the earliest outcome date (T+5 signals were created ~5 days ago)
            from datetime import timedelta

            record_date = (datetime.now(_CST) - timedelta(days=5)).strftime("%Y-%m-%d")
            await validator.record_returns(record_date, return_rows)
            result["returns_recorded"] = len(return_rows)
            logger.info("Recorded %d T+5 returns for validation", len(return_rows))

        # ------------------------------------------------------------------
        # Step C: Rank factors and detect decay
        # ------------------------------------------------------------------
        rankings = await validator.rank_factors(lookback_days=90)
        if rankings:
            result["factor_rankings"] = [
                {
                    "name": r.factor_name,
                    "ic": r.information_coefficient,
                    "hit_rate": r.hit_rate,
                    "significant": r.is_significant,
                }
                for r in rankings[:10]  # top 10
            ]
            logger.info(
                "Factor rankings computed: %d factors, top=%s (IC=%.4f)",
                len(rankings),
                rankings[0].factor_name,
                rankings[0].information_coefficient,
            )

            # Check for decay in each factor
            for report in rankings:
                if report.decay_detected:
                    result["decayed_factors"].append(report.factor_name)
                    logger.warning(
                        "Factor decay detected: %s (IC=%.4f, was significant)",
                        report.factor_name,
                        report.information_coefficient,
                    )

        # ------------------------------------------------------------------
        # Step D: Detect redundancy
        # ------------------------------------------------------------------
        redundant = await validator.detect_redundancy(lookback_days=90)
        if redundant:
            result["redundant_pairs"] = [
                {"a": a, "b": b, "corr": c} for a, b, c in redundant
            ]
            for a, b, corr in redundant:
                logger.info("Redundant factor pair: %s ↔ %s (corr=%.4f)", a, b, corr)

    except Exception as exc:
        logger.warning("Factor validation failed (non-fatal): %s", exc)

    return result


async def _run_outcome_verification() -> dict:
    """Core verification logic — evaluates outcomes and updates calibration.

    Returns a summary dict for the Celery task result and daily review message.
    """
    from src.agent_loop.bayesian_belief import CalibrationStore
    from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
    from src.agent_loop.outcome_tracker import OutcomeTracker
    from src.web.services.message_store import MessageStore
    from src.web.services.portfolio_store import PortfolioStore

    tracker = OutcomeTracker()
    calibrator = ConfidenceCalibrator()
    calibration_store = CalibrationStore()
    message_store = MessageStore()
    portfolio_store = PortfolioStore()

    # Load any existing empirical tables
    calibration_store.load_empirical_tables()

    # ------------------------------------------------------------------
    # Step 1: Evaluate pending signal outcomes (T+1, T+3, T+5)
    # ------------------------------------------------------------------
    logger.info("Evaluating pending signal outcomes...")
    outcomes = await tracker.evaluate_pending(price_fetcher=_fetch_closing_price)
    logger.info("Outcome evaluation complete: %d outcomes resolved", len(outcomes))

    # ------------------------------------------------------------------
    # Step 2: Update ConfidenceCalibrator with completed outcomes
    # ------------------------------------------------------------------
    if outcomes:
        calibrator.update_from_outcomes(outcomes)
        logger.info("ConfidenceCalibrator updated with %d outcomes", len(outcomes))

    # ------------------------------------------------------------------
    # Step 3: Update BayesianBelief likelihood tables
    # ------------------------------------------------------------------
    # Get calibration data from outcome tracker (empirical P(signal|bull/bear))
    calibration_data = tracker.get_calibration_data(lookback_days=90, min_samples=5)
    if calibration_data:
        calibration_store.update_from_empirical(calibration_data)
        logger.info(
            "BayesianBelief likelihood tables updated: %d buckets",
            len(calibration_data),
        )

    # Also update via the full empirical pipeline for persistence
    # Build outcome dicts for the CalibrationStore.update_likelihood_tables method
    accuracy_by_source = tracker.get_accuracy_by_source(lookback_days=90)
    outcome_dicts = []
    for src_acc in accuracy_by_source:
        if src_acc.total_signals >= 5:
            # Create synthetic outcome entries for the calibration update
            for _ in range(src_acc.direction_correct):
                outcome_dicts.append(
                    {
                        "source": src_acc.source,
                        "bucket": "strong"
                        if src_acc.accuracy >= 0.75
                        else ("moderate" if src_acc.accuracy >= 0.55 else "weak"),
                        "direction_correct": True,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                )
            for _ in range(src_acc.total_signals - src_acc.direction_correct):
                outcome_dicts.append(
                    {
                        "source": src_acc.source,
                        "bucket": "strong"
                        if src_acc.accuracy >= 0.75
                        else ("moderate" if src_acc.accuracy >= 0.55 else "weak"),
                        "direction_correct": False,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                )

    buckets_updated = 0
    if outcome_dicts:
        buckets_updated = calibration_store.update_likelihood_tables(
            outcome_dicts, min_samples=5
        )
        logger.info(
            "Empirical likelihood tables persisted: %d buckets", buckets_updated
        )

    # Invalidate DI cache so next heartbeat reloads updated calibration
    if buckets_updated > 0:
        try:
            from src.web.dependencies import get_decision_pipeline

            get_decision_pipeline.cache_clear()
            logger.info(
                "DecisionPipeline DI cache cleared — next heartbeat will "
                "reload %d updated Bayesian buckets",
                buckets_updated,
            )
        except Exception as exc:
            logger.warning("DI cache invalidation failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 3b: Factor validation (decay detection, redundancy, ranking)
    # ------------------------------------------------------------------
    factor_result = await _validate_factors(outcomes)
    logger.info(
        "Factor validation: %d scores recorded, %d returns recorded, %d decayed",
        factor_result.get("factors_recorded", 0),
        factor_result.get("returns_recorded", 0),
        len(factor_result.get("decayed_factors", [])),
    )

    # ------------------------------------------------------------------
    # Step 4: Check thesis validity for T+3 negative outcomes
    # ------------------------------------------------------------------
    flagged_theses = []
    try:
        from src.agent_loop.thesis_tracker import ThesisTracker

        thesis_tracker = ThesisTracker()
        active_theses = thesis_tracker.get_active_theses()
        thesis_symbols = {t.symbol for t in active_theses}

        for outcome in outcomes:
            if (
                outcome.action in ("buy", "add")
                and outcome.t3_price is not None
                and outcome.decided_price > 0
            ):
                t3_return = (
                    outcome.t3_price - outcome.decided_price
                ) / outcome.decided_price
                if t3_return < 0 and outcome.symbol in thesis_symbols:
                    flagged_theses.append(
                        {
                            "symbol": outcome.symbol,
                            "proposal_id": outcome.proposal_id,
                            "t3_return_pct": round(t3_return * 100, 2),
                            "decided_price": outcome.decided_price,
                            "t3_price": outcome.t3_price,
                        }
                    )
                    logger.warning(
                        "Thesis review needed: %s T+3 return %.2f%% (entry=%.2f, T+3=%.2f)",
                        outcome.symbol,
                        t3_return * 100,
                        outcome.decided_price,
                        outcome.t3_price,
                    )
    except Exception as exc:
        logger.warning("Thesis validity check failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 4b: Update decision journal outcomes
    # ------------------------------------------------------------------
    journal_updated = await _update_decision_journal_outcomes()

    # ------------------------------------------------------------------
    # Step 4c: Evaluate decisions.db for calibration feedback loop
    # ------------------------------------------------------------------
    calibration_evaluated = await _evaluate_calibration_decisions()

    # ------------------------------------------------------------------
    # Step 5: Compute portfolio-level win rate from positions
    # ------------------------------------------------------------------
    positions = portfolio_store.list_positions()
    position_count = len(positions)

    # ------------------------------------------------------------------
    # Step 6: Generate calibration report
    # ------------------------------------------------------------------
    calibration_report = calibrator.get_calibration_report()

    # ------------------------------------------------------------------
    # Step 7: Generate daily review message
    # ------------------------------------------------------------------
    wins = sum(1 for o in outcomes if o.direction_correct is True)
    losses = sum(1 for o in outcomes if o.direction_correct is False)
    total_evaluated = wins + losses
    win_rate = (wins / total_evaluated * 100) if total_evaluated > 0 else 0.0

    # Build summary in Chinese (user-facing)
    summary_parts = []
    summary_parts.append(f"今日验证了 {len(outcomes)} 个交易信号的实际表现")
    if total_evaluated > 0:
        summary_parts.append(f"方向正确率: {win_rate:.0f}% ({wins}胜/{losses}负)")
    if buckets_updated > 0:
        summary_parts.append(f"更新了 {buckets_updated} 个信号源的置信度校准")
    if flagged_theses:
        symbols = ", ".join(t["symbol"] for t in flagged_theses)
        summary_parts.append(f"需要复盘: {symbols} (T+3收益为负)")
    decayed = factor_result.get("decayed_factors", [])
    if decayed:
        summary_parts.append(f"因子衰减警告: {', '.join(decayed)}")
    summary_parts.append(f"当前持仓: {position_count} 只")

    summary = "。".join(summary_parts) + "。"

    # Detailed content
    content_parts = ["# 每日决策复盘\n"]
    content_parts.append(
        f"**验证时间**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )

    if total_evaluated > 0:
        content_parts.append("## 信号表现")
        content_parts.append(f"- 已完成评估: {total_evaluated} 个信号")
        content_parts.append(f"- 方向正确率: {win_rate:.1f}%")
        content_parts.append(f"- 胜: {wins} / 负: {losses}\n")

    if flagged_theses:
        content_parts.append("## 需要复盘的投资论点")
        for t in flagged_theses:
            content_parts.append(
                f"- **{t['symbol']}**: 入场价 {t['decided_price']:.2f} → "
                f"T+3价格 {t['t3_price']:.2f} ({t['t3_return_pct']:+.2f}%)"
            )
        content_parts.append("")

    if calibration_report.get("status") == "ok":
        content_parts.append("## 校准状态")
        overall_acc = calibration_report.get("overall_accuracy")
        if overall_acc is not None:
            content_parts.append(f"- 整体准确率: {overall_acc:.1%}")
        evaluated = calibration_report.get("evaluated_decisions", 0)
        content_parts.append(f"- 已评估决策数: {evaluated}")
        avg_returns = calibration_report.get("avg_returns", {})
        if avg_returns.get("t1") is not None:
            content_parts.append(f"- 平均T+1收益: {avg_returns['t1']:.2f}%")
        if avg_returns.get("t3") is not None:
            content_parts.append(f"- 平均T+3收益: {avg_returns['t3']:.2f}%")

    # Factor validation section
    factor_rankings = factor_result.get("factor_rankings", [])
    if factor_rankings:
        content_parts.append("## 因子有效性")
        for fr in factor_rankings[:5]:
            sig_mark = " *" if fr["significant"] else ""
            content_parts.append(
                f"- {fr['name']}: IC={fr['ic']:.4f}, "
                f"命中率={fr['hit_rate']:.1%}{sig_mark}"
            )
        if decayed:
            content_parts.append(f"\n**衰减警告**: {', '.join(decayed)} 近期预测力下降")
        redundant = factor_result.get("redundant_pairs", [])
        if redundant:
            pairs = [f"{p['a']}↔{p['b']}({p['corr']:.2f})" for p in redundant[:3]]
            content_parts.append(f"**冗余因子对**: {', '.join(pairs)}")
        content_parts.append("")

    content = "\n".join(content_parts)

    # Determine priority
    priority = "medium"
    if flagged_theses:
        priority = "high"
    if total_evaluated > 0 and win_rate < 40:
        priority = "high"
    if decayed:
        priority = "high"

    try:
        msg_id = message_store.create_message(
            msg_type="daily_review",
            title="每日决策复盘报告",
            summary=summary,
            content=content,
            priority=priority,
            action_advice="查看校准变化，关注需要复盘的论点"
            if flagged_theses
            else None,
            risk_note=f"当前胜率 {win_rate:.0f}%" if total_evaluated > 0 else None,
            data_freshness="daily",
            data_collected_at=datetime.now(UTC).isoformat(),
        )
        logger.info("Daily review message created: ID=%d", msg_id)
    except Exception as exc:
        logger.warning("Failed to create daily review message: %s", exc)

    # ------------------------------------------------------------------
    # Step 7: Publish outcomes to Redis for HeartbeatAgent morning reflection
    # ------------------------------------------------------------------
    try:
        import redis as _redis

        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        r = _redis.from_url(broker, decode_responses=True)
        today_str = datetime.now(UTC).strftime("%Y%m%d")
        agent_outcomes = []
        for o in outcomes:
            pnl_pct = 0.0
            if o.decided_price and o.decided_price > 0 and o.t1_price:
                pnl_pct = (o.t1_price - o.decided_price) / o.decided_price * 100
            agent_outcomes.append(
                {
                    "symbol": o.symbol,
                    "action": o.action,
                    "result": "win" if pnl_pct > 0 else "loss",
                    "pnl_pct": round(pnl_pct, 2),
                    "decided_price": o.decided_price,
                    "t1_price": o.t1_price,
                }
            )
        if agent_outcomes:
            import json as _json

            r.set(
                f"agent:outcomes:{today_str}",
                _json.dumps(agent_outcomes, ensure_ascii=False),
                ex=172800,  # 48h TTL
            )
            logger.info(
                "Published %d outcomes to agent:outcomes:%s",
                len(agent_outcomes),
                today_str,
            )
    except Exception as exc:
        logger.warning("Failed to publish outcomes to Redis: %s", exc)

    result = {
        "outcomes_evaluated": len(outcomes),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 1),
        "calibration_buckets_updated": buckets_updated,
        "flagged_theses": len(flagged_theses),
        "portfolio_positions": position_count,
        "calibration_active": calibration_report.get("calibration_active", False),
        "calibration_decisions_evaluated": calibration_evaluated,
        "journal_updated": journal_updated,
        "factor_validation": factor_result,
    }
    logger.info("Daily outcome verification result: %s", result)
    return result


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.daily_outcome_verification.task_daily_outcome_verification",
    soft_time_limit=180,
    time_limit=240,
)
def task_daily_outcome_verification():
    """每日决策复盘 (16:30 CST, 交易日).

    Post-market feedback loop: evaluates signal outcomes, updates
    confidence calibration, flags weak theses, and generates a
    daily review message.
    """
    if not _is_trading_day():
        logger.debug("Not a trading day — skipping outcome verification")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Daily Outcome Verification (16:30) START ===")
    result = _run_async(_run_outcome_verification())
    logger.info("=== Daily Outcome Verification (16:30) END ===")
    return {"task": "daily_outcome_verification", **result}
