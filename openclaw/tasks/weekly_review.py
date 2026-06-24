"""Weekly review pipeline — aggregate weekly performance and calibration.

Per PRD v50.0 §13.2: Saturday morning weekly review.
Aggregates daily outcomes, factor attribution, regime adaptation analysis,
best/worst decisions, and parameter adjustment recommendations.

Scheduled: Saturday 10:00 CST
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_week_range() -> tuple[str, str]:
    """Return (monday_iso, saturday_iso) for the week being reviewed.

    Called on Saturday, so "this week" is Mon-Fri just completed.
    """
    now = datetime.now(_CST)
    # Saturday = weekday 5.  Go back to Monday = now - 5 days.
    monday = now - timedelta(days=now.weekday())
    monday_str = monday.strftime("%Y-%m-%d")
    friday = monday + timedelta(days=4)
    friday_str = friday.strftime("%Y-%m-%d")
    return monday_str, friday_str


def _get_weekly_decisions(week_start: str, week_end: str) -> list:
    """Query DecisionLog for decisions made this week."""
    import sqlite3
    from pathlib import Path

    db_path = Path("data/decisions.db")
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM decisions
            WHERE decided_at >= ? AND decided_at < datetime(?, '+1 day')
            ORDER BY decided_at ASC
            """,
            (week_start, week_end),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("Failed to query weekly decisions: %s", exc)
        return []
    finally:
        conn.close()


def _get_weekly_signal_stats(decisions: list) -> dict:
    """Count signals by action and outcome for the week."""
    stats: dict[str, dict[str, int]] = {}
    for d in decisions:
        action = d.get("action", "unknown")
        if action not in stats:
            stats[action] = {"total": 0, "correct": 0, "incorrect": 0, "pending": 0}
        stats[action]["total"] += 1

        dc = d.get("direction_correct")
        if dc is None:
            stats[action]["pending"] += 1
        elif dc:
            stats[action]["correct"] += 1
        else:
            stats[action]["incorrect"] += 1
    return stats


def _compute_weekly_pnl(decisions: list) -> dict:
    """Compute aggregate P&L metrics from the week's decisions."""
    total_pnl_pct = 0.0
    evaluated = 0
    wins = 0
    losses = 0
    max_win = 0.0
    max_loss = 0.0

    for d in decisions:
        # Use t5_return_pct if available, else t3, else t1
        ret = d.get("t5_return_pct") or d.get("t3_return_pct") or d.get("t1_return_pct")
        if ret is None:
            continue
        evaluated += 1
        total_pnl_pct += ret
        if ret > 0:
            wins += 1
            max_win = max(max_win, ret)
        else:
            losses += 1
            max_loss = min(max_loss, ret)

    return {
        "total_pnl_pct": round(total_pnl_pct, 2),
        "evaluated": evaluated,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / evaluated * 100, 1) if evaluated > 0 else 0.0,
        "max_win_pct": round(max_win, 2),
        "max_loss_pct": round(max_loss, 2),
    }


def _get_best_worst_decisions(decisions: list, top_n: int = 3) -> dict:
    """Find the best and worst decisions by P&L impact."""
    scored: list[tuple[float, dict]] = []
    for d in decisions:
        ret = d.get("t5_return_pct") or d.get("t3_return_pct") or d.get("t1_return_pct")
        if ret is not None:
            scored.append((ret, d))

    scored.sort(key=lambda x: x[0], reverse=True)

    def _summarize(ret: float, d: dict) -> dict:
        return {
            "symbol": d.get("symbol", "?"),
            "action": d.get("action", "?"),
            "return_pct": round(ret, 2),
            "decided_price": d.get("decided_price"),
            "decided_at": d.get("decided_at", ""),
        }

    best = [_summarize(r, d) for r, d in scored[:top_n]]
    worst = [_summarize(r, d) for r, d in scored[-top_n:] if r < 0]

    return {"best": best, "worst": worst}


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _run_weekly_review() -> dict:
    """Core weekly review logic.

    Returns a summary dict for the Celery task result and message.
    """
    from src.agent_loop.bayesian_belief import CalibrationStore
    from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
    from src.agent_loop.factor_validator import FactorValidator
    from src.web.services.message_store import MessageStore

    week_start, week_end = _get_week_range()
    logger.info("Weekly review period: %s to %s", week_start, week_end)

    result: dict = {
        "week_start": week_start,
        "week_end": week_end,
    }

    # ------------------------------------------------------------------
    # 1. Aggregate weekly decisions and P&L
    # ------------------------------------------------------------------
    decisions = _get_weekly_decisions(week_start, week_end)
    result["total_decisions"] = len(decisions)

    pnl = _compute_weekly_pnl(decisions)
    result["pnl"] = pnl

    signal_stats = _get_weekly_signal_stats(decisions)
    result["signal_stats"] = signal_stats

    # ------------------------------------------------------------------
    # 2. Portfolio snapshot
    # ------------------------------------------------------------------
    try:
        from src.web.services.portfolio_store import PortfolioStore

        portfolio_store = PortfolioStore()
        positions = portfolio_store.list_positions()
        result["position_count"] = len(positions)
    except Exception as exc:
        logger.warning("Portfolio snapshot failed: %s", exc)
        positions = []
        result["position_count"] = 0

    # ------------------------------------------------------------------
    # 3. Factor attribution
    # ------------------------------------------------------------------
    factor_result: dict = {
        "factor_rankings": [],
        "decayed_factors": [],
        "redundant_pairs": [],
    }
    try:
        validator = FactorValidator()
        rankings = await validator.rank_factors(lookback_days=90)
        if rankings:
            factor_result["factor_rankings"] = [
                {
                    "name": r.factor_name,
                    "ic": r.information_coefficient,
                    "hit_rate": r.hit_rate,
                    "significant": r.is_significant,
                }
                for r in rankings[:10]
            ]
            for r in rankings:
                if r.decay_detected:
                    factor_result["decayed_factors"].append(r.factor_name)

            redundant = await validator.detect_redundancy(lookback_days=90)
            if redundant:
                factor_result["redundant_pairs"] = [
                    {"a": a, "b": b, "corr": round(c, 4)} for a, b, c in redundant
                ]
    except Exception as exc:
        logger.warning("Factor attribution failed (non-fatal): %s", exc)

    result["factor_validation"] = factor_result

    # ------------------------------------------------------------------
    # 4. Regime adaptation analysis
    # ------------------------------------------------------------------
    regime_info: dict = {"regime": "unknown", "phase": "unknown"}
    try:
        from src.agent_loop.shared_belief_state import SharedBeliefState

        belief = SharedBeliefState()
        belief._load_from_redis()  # type: ignore[attr-defined]
        regime_info["regime"] = belief.regime.hmm_state
        regime_info["phase"] = belief.regime.sentiment_phase
        regime_info["reflexivity"] = belief.regime.reflexivity_state
    except Exception as exc:
        logger.debug("Regime state unavailable: %s", exc)

    result["regime"] = regime_info

    # ------------------------------------------------------------------
    # 5. Best/worst decisions
    # ------------------------------------------------------------------
    best_worst = _get_best_worst_decisions(decisions)
    result["best_decisions"] = best_worst["best"]
    result["worst_decisions"] = best_worst["worst"]

    # ------------------------------------------------------------------
    # 6. Bayesian table health check
    # ------------------------------------------------------------------
    bayesian_health: dict = {"low_sample_cells": [], "total_cells": 0}
    try:
        cal_store = CalibrationStore()
        loaded = cal_store.load_empirical_tables()
        bayesian_health["total_cells"] = loaded

        # Check sample counts from the DB directly
        import sqlite3
        from pathlib import Path

        cal_db = Path("data/calibration.db")
        if cal_db.exists():
            conn = sqlite3.connect(str(cal_db), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT key, sample_count FROM likelihood_tables"
                ).fetchall()
                for row in rows:
                    if row["sample_count"] < 30:
                        bayesian_health["low_sample_cells"].append(
                            {"key": row["key"], "count": row["sample_count"]}
                        )
            finally:
                conn.close()
    except Exception as exc:
        logger.debug("Bayesian health check failed: %s", exc)

    result["bayesian_health"] = bayesian_health

    # ------------------------------------------------------------------
    # 7. Calibration / Brier score proxy
    # ------------------------------------------------------------------
    calibration_report: dict = {}
    try:
        calibrator = ConfidenceCalibrator()
        calibration_report = calibrator.get_calibration_report()
    except Exception as exc:
        logger.debug("Calibration report unavailable: %s", exc)

    result["calibration"] = calibration_report

    # ------------------------------------------------------------------
    # 8. Parameter adjustment recommendations
    # ------------------------------------------------------------------
    recommendations: list[str] = []

    # 8a. Signal type win rate checks
    for action, stats in signal_stats.items():
        total_eval = stats["correct"] + stats["incorrect"]
        if total_eval >= 5:
            wr = stats["correct"] / total_eval * 100
            if wr < 45:
                recommendations.append(
                    f"'{action}' 信号胜率仅 {wr:.0f}%, 建议降低该类信号权重"
                )

    # 8b. Overall calibration quality
    overall_acc = calibration_report.get("overall_accuracy")
    if overall_acc is not None and overall_acc < 0.45:
        recommendations.append(
            f"整体准确率 {overall_acc:.0%}, 低于45%阈值, 建议重新校准置信度模型"
        )

    # 8c. Max drawdown check
    if pnl["max_loss_pct"] < -5.0:
        recommendations.append(
            f"本周最大单笔亏损 {pnl['max_loss_pct']:.1f}%, 超过5%警戒线, "
            "建议收紧止损距离"
        )

    # 8d. Consecutive losses / risk budget
    if pnl["losses"] >= 5 and pnl["win_rate"] < 40:
        recommendations.append(
            f"本周 {pnl['losses']} 笔亏损 (胜率 {pnl['win_rate']:.0f}%), "
            "建议暂停新开仓并复盘策略"
        )

    # 8e. Factor decay
    if factor_result["decayed_factors"]:
        decayed_str = ", ".join(factor_result["decayed_factors"])
        recommendations.append(f"因子衰减: {decayed_str}, 建议降权或替换")

    # 8f. Low sample Bayesian cells
    low_cells = bayesian_health.get("low_sample_cells", [])
    if len(low_cells) > 3:
        recommendations.append(
            f"{len(low_cells)} 个贝叶斯校准桶样本不足 (<30), 校准可靠性有限"
        )

    result["recommendations"] = recommendations

    # ------------------------------------------------------------------
    # 9. Generate weekly review message
    # ------------------------------------------------------------------
    summary_parts = []
    summary_parts.append(
        f"本周 ({week_start} ~ {week_end}) 共执行 {len(decisions)} 个决策"
    )
    if pnl["evaluated"] > 0:
        summary_parts.append(
            f"胜率 {pnl['win_rate']:.0f}% ({pnl['wins']}胜/{pnl['losses']}负)"
        )
        summary_parts.append(f"累计收益 {pnl['total_pnl_pct']:+.2f}%")
    if recommendations:
        summary_parts.append(f"有 {len(recommendations)} 条调整建议")
    summary = "。".join(summary_parts) + "。"

    # Detailed content in Chinese
    content_parts = ["# 周度复盘报告\n"]
    content_parts.append(f"**复盘周期**: {week_start} ~ {week_end}")
    content_parts.append(
        f"**生成时间**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )

    # P&L section
    content_parts.append("## 本周业绩")
    content_parts.append(f"- 总决策数: {len(decisions)}")
    if pnl["evaluated"] > 0:
        content_parts.append(f"- 已评估: {pnl['evaluated']} 个")
        content_parts.append(f"- 胜率: {pnl['win_rate']:.1f}%")
        content_parts.append(f"- 累计收益: {pnl['total_pnl_pct']:+.2f}%")
        content_parts.append(f"- 最大单笔盈利: {pnl['max_win_pct']:+.2f}%")
        content_parts.append(f"- 最大单笔亏损: {pnl['max_loss_pct']:+.2f}%")
    content_parts.append(f"- 当前持仓: {len(positions)} 只\n")

    # Signal attribution
    if signal_stats:
        content_parts.append("## 信号归因")
        for action, stats in signal_stats.items():
            total_eval = stats["correct"] + stats["incorrect"]
            wr = (
                f"{stats['correct'] / total_eval * 100:.0f}%"
                if total_eval > 0
                else "待评估"
            )
            content_parts.append(
                f"- {action}: {stats['total']}笔, 胜率{wr} (待评估{stats['pending']}笔)"
            )
        content_parts.append("")

    # Best/worst
    if best_worst["best"]:
        content_parts.append("## 最佳决策 (Top 3)")
        for d in best_worst["best"]:
            content_parts.append(
                f"- **{d['symbol']}** {d['action']}: {d['return_pct']:+.2f}%"
            )
        content_parts.append("")

    if best_worst["worst"]:
        content_parts.append("## 最差决策 (Bottom 3)")
        for d in best_worst["worst"]:
            content_parts.append(
                f"- **{d['symbol']}** {d['action']}: {d['return_pct']:+.2f}%"
            )
        content_parts.append("")

    # Regime
    content_parts.append("## 市场环境")
    content_parts.append(f"- HMM状态: {regime_info.get('regime', '未知')}")
    content_parts.append(f"- 情绪阶段: {regime_info.get('phase', '未知')}")
    content_parts.append(f"- 反身性: {regime_info.get('reflexivity', '未知')}\n")

    # Factor rankings
    if factor_result["factor_rankings"]:
        content_parts.append("## 因子有效性 (Top 5)")
        for fr in factor_result["factor_rankings"][:5]:
            sig_mark = " *" if fr["significant"] else ""
            content_parts.append(
                f"- {fr['name']}: IC={fr['ic']:.4f}, "
                f"命中率={fr['hit_rate']:.1%}{sig_mark}"
            )
        if factor_result["decayed_factors"]:
            content_parts.append(
                f"\n**衰减警告**: {', '.join(factor_result['decayed_factors'])}"
            )
        content_parts.append("")

    # Bayesian health
    if low_cells:
        content_parts.append("## 贝叶斯校准健康")
        content_parts.append(f"- 低样本桶数: {len(low_cells)} (阈值: 30)")
        for cell in low_cells[:5]:
            content_parts.append(f"  - {cell['key']}: {cell['count']} 样本")
        content_parts.append("")

    # Calibration
    if calibration_report.get("status") == "ok":
        content_parts.append("## 校准状态")
        if overall_acc is not None:
            content_parts.append(f"- 整体准确率: {overall_acc:.1%}")
        content_parts.append(
            f"- 已评估决策: {calibration_report.get('evaluated_decisions', 0)}"
        )
        avg_ret = calibration_report.get("avg_returns", {})
        if avg_ret.get("t1") is not None:
            content_parts.append(f"- 平均T+1收益: {avg_ret['t1']:.2f}%")
        if avg_ret.get("t3") is not None:
            content_parts.append(f"- 平均T+3收益: {avg_ret['t3']:.2f}%")
        content_parts.append("")

    # Recommendations
    if recommendations:
        content_parts.append("## 参数调整建议")
        for i, rec in enumerate(recommendations, 1):
            content_parts.append(f"{i}. {rec}")
        content_parts.append("")
    else:
        content_parts.append("## 参数调整建议")
        content_parts.append("本周各项指标正常, 无需调整。\n")

    content = "\n".join(content_parts)

    # Priority logic
    priority = "medium"
    if recommendations:
        priority = "high"
    if pnl["evaluated"] > 0 and pnl["win_rate"] < 40:
        priority = "high"

    # Create message
    try:
        message_store = MessageStore()
        msg_id = message_store.create_message(
            msg_type="weekly_review",
            title="周度复盘报告",
            summary=summary,
            content=content,
            priority=priority,
            action_advice="查看本周决策归因和参数调整建议" if recommendations else None,
            risk_note=f"本周胜率 {pnl['win_rate']:.0f}%"
            if pnl["evaluated"] > 0
            else None,
            data_freshness="weekly",
            data_collected_at=datetime.now(UTC).isoformat(),
        )
        logger.info("Weekly review message created: ID=%d", msg_id)
    except Exception as exc:
        logger.warning("Failed to create weekly review message: %s", exc)

    # Push to Discord
    try:
        from src.utils.notifier import DiscordNotifier

        notifier = DiscordNotifier()
        if notifier.enabled:
            notifier.send_daily_summary(
                [
                    {
                        "symbol": "周报",
                        "signal": f"胜率{pnl['win_rate']:.0f}%",
                        "confidence": pnl["win_rate"] / 100.0
                        if pnl["evaluated"] > 0
                        else 0.0,
                    }
                ]
            )
    except Exception as exc:
        logger.debug("Discord push failed (non-fatal): %s", exc)

    logger.info("Weekly review result: %s", result)
    return result


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.weekly_review.task_weekly_review",
    soft_time_limit=300,
    time_limit=360,
)
def task_weekly_review():
    """周度复盘 (周六10:00, 绩效归因+校准检查+参数建议).

    Saturday morning weekly review: aggregates daily outcomes, factor
    attribution, regime adaptation analysis, best/worst decisions,
    and parameter adjustment recommendations.
    """
    logger.info("=== Weekly Review (Saturday 10:00) START ===")
    result = _run_async(_run_weekly_review())
    logger.info("=== Weekly Review (Saturday 10:00) END ===")
    return {"task": "weekly_review", **result}
