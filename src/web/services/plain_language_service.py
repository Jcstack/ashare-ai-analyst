"""Translates AI agent outputs into plain Chinese messages.

Converts raw AI data (conviction scores, kelly fractions, regime labels)
into human-readable Chinese text that retail investors can understand.
Falls back to template-based translation when LLM is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MessageCreate:
    """Data transfer object for creating a new message."""

    symbol: str | None
    msg_type: (
        str  # buy_signal | sell_signal | risk_alert | market_watch | hold_reminder
    )
    title: str
    summary: str
    action_advice: str | None = None
    risk_note: str | None = None
    detail_analysis: str | None = None
    raw_data_ref: dict | None = None
    impact: str = "NORMAL"  # NORMAL | HIGH | CRITICAL
    content: str | None = None
    priority: str = "medium"  # critical | high | medium | low
    stock_recommendations: list[dict] | None = None
    post_market_data: dict | None = None
    expires_at: str | None = None


# -- Conviction label mapping --------------------------------------------------

_CONVICTION_LABELS = [
    (0.8, "把握较大"),
    (0.6, "把握尚可"),
    (0.4, "把握一般"),
    (0.0, "把握不大，建议观望"),
]

# -- Regime label mapping ------------------------------------------------------

_REGIME_LABELS = {
    "bull_quiet": "当前大盘走势向好且波动较小",
    "bull_volatile": "当前大盘走势向好但波动较大",
    "bear_quiet": "当前大盘走势偏弱但波动较小",
    "bear_volatile": "当前大盘走势偏弱且波动较大",
    "neutral": "当前大盘处于震荡整理状态",
    "unknown": "当前大盘走势不明朗",
}

# -- Confidence label mapping ---------------------------------------------------

_CONFIDENCE_LABELS = {
    "high": "信心较高",
    "medium": "信心适中",
    "low": "信心偏低",
}


def _conviction_label(score: float) -> str:
    """Convert a 0-1 conviction score to a plain Chinese label."""
    for threshold, label in _CONVICTION_LABELS:
        if score >= threshold:
            return label
    return "把握不大，建议观望"


def _regime_label(regime: str) -> str:
    """Convert a regime key to plain Chinese."""
    return _REGIME_LABELS.get(regime, f"市场状态: {regime}")


def _pct_to_chinese(pct: float) -> str:
    """Format a percentage for Chinese readers."""
    return f"{abs(pct):.1f}%"


def _kelly_to_advice(fraction: float) -> str:
    """Convert kelly fraction to position size advice."""
    pct = round(fraction * 100)
    if pct <= 0:
        return "建议暂不投入资金"
    if pct <= 5:
        return f"建议用总资金的 {pct}% 小仓试探"
    if pct <= 15:
        return f"建议用总资金的 {pct}% 买入"
    return f"建议用总资金的 {pct}% 买入（仓位较重，注意风险）"


class PlainLanguageService:
    """Translates AI agent outputs into plain Chinese messages.

    Uses template-based translation with optional LLM enhancement.
    Integrates DataFreshnessGuard (FR-AIX008) for accuracy validation.
    """

    def __init__(
        self,
        message_store: Any = None,
        llm_router: Any = None,
        freshness_guard: Any = None,
    ) -> None:
        self._store = message_store
        self._llm = llm_router
        self._freshness_guard = freshness_guard

    # ------------------------------------------------------------------
    # Persist with freshness enrichment
    # ------------------------------------------------------------------

    async def _persist(self, msg: MessageCreate) -> None:
        """Persist message with freshness metadata if store is available."""
        if not self._store:
            return

        freshness = "realtime"
        data_collected_at = None

        if self._freshness_guard and msg.raw_data_ref:
            data_time = msg.raw_data_ref.get(
                "data_collected_at"
            ) or msg.raw_data_ref.get("timestamp")
            freshness = self._freshness_guard.get_freshness_level(data_time)
            data_collected_at = data_time

            # Prepend staleness warning to summary
            label = self._freshness_guard.freshness_label(freshness)
            if label and freshness == "stale" and label not in msg.summary:
                msg.summary = f"({label}) {msg.summary}"

        try:
            self._store.create_message(
                symbol=msg.symbol,
                msg_type=msg.msg_type,
                title=msg.title,
                summary=msg.summary,
                content=msg.content,
                priority=msg.priority,
                action_advice=msg.action_advice,
                risk_note=msg.risk_note,
                detail_analysis=msg.detail_analysis,
                stock_recommendations=msg.stock_recommendations,
                post_market_data=msg.post_market_data,
                raw_data_ref=msg.raw_data_ref,
                data_freshness=freshness,
                data_collected_at=str(data_collected_at) if data_collected_at else None,
                expires_at=msg.expires_at,
            )
        except Exception as exc:
            logger.warning("Failed to persist message: %s", exc)

    # ------------------------------------------------------------------
    # Trade decision → message
    # ------------------------------------------------------------------

    async def translate_trade_decision(self, decision: dict) -> MessageCreate:
        """Convert TraderAgent/DecisionPipeline decision to a plain language message.

        Expected decision keys:
            symbol, name, action, confidence, shares, price_target,
            stop_loss, take_profit, debate_summary, reasoning_chain,
            risk_notes, portfolio_impact, kelly_fraction, thesis
        """
        symbol = decision.get("symbol", "")
        name = decision.get("name", symbol)
        action = decision.get("action", "buy")
        confidence = decision.get("confidence", 0.5)
        shares = decision.get("shares", 0)
        price_target = decision.get("price_target")
        stop_loss = decision.get("stop_loss")
        kelly_fraction = decision.get("kelly_fraction")
        debate_summary = decision.get("debate_summary", "")
        risk_notes = decision.get("risk_notes", [])
        reasoning_chain = decision.get("reasoning_chain", [])

        # Cross-check: debate scores vs action direction
        bull_score = decision.get("bull_score", 0.0)
        bear_score = decision.get("bear_score", 0.0)
        if bull_score or bear_score:
            if action in ("buy", "add") and bear_score > bull_score + 0.2:
                logger.warning(
                    "Direction conflict for %s: action=%s but bear_score(%.2f) "
                    "> bull_score(%.2f) — overriding to hold",
                    symbol,
                    action,
                    bear_score,
                    bull_score,
                )
                action = "hold"
                decision["action"] = "hold"
            elif action in ("sell", "reduce") and bull_score > bear_score + 0.2:
                logger.warning(
                    "Direction conflict for %s: action=%s but bull_score(%.2f) "
                    "> bear_score(%.2f) — overriding to hold",
                    symbol,
                    action,
                    bull_score,
                    bear_score,
                )
                action = "hold"
                decision["action"] = "hold"

        # New TradeProposal fields
        contingency_plan = decision.get("contingency_plan")
        invalidation_condition = decision.get("invalidation_condition")
        valid_until_raw = decision.get("valid_until")
        scenario_best = decision.get("scenario_best")
        scenario_base = decision.get("scenario_base")
        scenario_worst = decision.get("scenario_worst")
        holding_period_days = decision.get("holding_period_days")

        # Format valid_until as readable time string
        valid_until_str: str | None = None
        if valid_until_raw:
            if isinstance(valid_until_raw, str):
                valid_until_str = valid_until_raw
            elif hasattr(valid_until_raw, "strftime"):
                valid_until_str = valid_until_raw.strftime("%m月%d日 %H:%M")

        # Determine message type
        if action in ("sell", "reduce"):
            msg_type = "sell_signal"
        elif action in ("hold", "watch"):
            msg_type = "hold_reminder"
        else:
            msg_type = "buy_signal"

        # Build title
        action_labels = {
            "buy": "买入",
            "sell": "卖出",
            "add": "加仓",
            "reduce": "减仓",
            "hold": "持有",
        }
        action_cn = action_labels.get(action, action)
        conviction_cn = _conviction_label(confidence)
        title = f"AI建议{action_cn} {name}（{symbol}），{conviction_cn}"

        # Build summary
        summary_parts = [f"AI分析认为 {name} 当前适合{action_cn}，"]
        summary_parts.append(f"判断{conviction_cn}（置信度 {confidence * 100:.0f}%）。")
        if debate_summary:
            # Truncate long debates
            short_debate = debate_summary[:150]
            if len(debate_summary) > 150:
                short_debate += "..."
            summary_parts.append(f"分析要点：{short_debate}")
        summary = "".join(summary_parts)

        # Action advice
        advice_parts = []
        if shares > 0:
            advice_parts.append(f"建议买入 {shares} 股")
        if kelly_fraction is not None:
            advice_parts.append(_kelly_to_advice(kelly_fraction))
        if price_target:
            advice_parts.append(f"目标价位 {price_target:.2f} 元")
        if stop_loss:
            if isinstance(stop_loss, (int, float)):
                if stop_loss < 0:
                    advice_parts.append(
                        f"如果跌了 {_pct_to_chinese(stop_loss)} 就该卖出止损"
                    )
                else:
                    advice_parts.append(f"止损价位 {stop_loss:.2f} 元")
        if holding_period_days:
            advice_parts.append(f"建议持有 {holding_period_days} 天")
        if valid_until_str:
            advice_parts.append(f"信号有效期至 {valid_until_str}")
        if invalidation_condition:
            advice_parts.append(f"若出现「{invalidation_condition}」则信号失效")
        action_advice = "；".join(advice_parts) if advice_parts else None

        # Risk note
        risk_parts = []
        if isinstance(risk_notes, list):
            for note in risk_notes[:3]:
                risk_parts.append(str(note))
        elif isinstance(risk_notes, str) and risk_notes:
            risk_parts.append(risk_notes)
        risk_note = "。".join(risk_parts) if risk_parts else None

        # Detail analysis
        detail_parts = []
        if reasoning_chain:
            detail_parts.append("## AI 推理过程\n")
            for i, step in enumerate(reasoning_chain[:5], 1):
                detail_parts.append(f"{i}. {step}\n")
        if debate_summary:
            detail_parts.append(f"\n## 多角度分析\n{debate_summary}")

        # Scenario analysis
        if scenario_best or scenario_base or scenario_worst:
            detail_parts.append("\n## 情景分析")
            if scenario_best:
                detail_parts.append(f"- 乐观情景：{scenario_best}")
            if scenario_base:
                detail_parts.append(f"- 基准情景：{scenario_base}")
            if scenario_worst:
                detail_parts.append(f"- 悲观情景：{scenario_worst}")

        # Contingency and invalidation
        if contingency_plan:
            detail_parts.append(f"\n## 应急预案\n{contingency_plan}")
        if invalidation_condition:
            detail_parts.append(f"\n## 失效条件\n{invalidation_condition}")

        # Holding period and validity
        validity_parts = []
        if holding_period_days:
            validity_parts.append(f"建议持有 {holding_period_days} 天")
        if valid_until_str:
            validity_parts.append(f"信号有效期至 {valid_until_str}")
        if validity_parts:
            detail_parts.append(f"\n## 时效信息\n{'；'.join(validity_parts)}")

        detail = "\n".join(detail_parts) if detail_parts else None

        # Build stock_recommendations for executor signal format
        confidence_cn = (
            "高" if confidence >= 0.7 else ("中" if confidence >= 0.4 else "低")
        )
        entry_price = decision.get("entry_price") or decision.get("current_price")
        take_profit = decision.get("take_profit") or price_target
        rec: dict[str, Any] = {
            "direction": "SELL" if action in ("sell", "reduce") else "BUY",
            "symbol": symbol,
            "name": name,
            "buy_range": (
                [round(entry_price * 0.99, 2), round(entry_price * 1.01, 2)]
                if entry_price
                else None
            ),
            "position_pct": round(kelly_fraction * 100, 1) if kelly_fraction else None,
            "shares": shares if shares else None,
            "stop_loss": round(stop_loss, 2)
            if isinstance(stop_loss, (int, float)) and stop_loss > 0
            else None,
            "target": round(take_profit, 2) if take_profit else None,
            "holding_days": (
                f"{holding_period_days}天"
                if holding_period_days
                else decision.get("holding_period", "1-3天")
            ),
            "reason": (
                debate_summary[:200] if debate_summary else decision.get("thesis", "")
            ),
            "confidence": confidence_cn,
            "urgency": decision.get("urgency", "normal"),
            "contingency_plan": contingency_plan,
            "invalidation_condition": invalidation_condition,
            "valid_until": valid_until_str,
            "scenario_best": scenario_best,
            "scenario_base": scenario_base,
            "scenario_worst": scenario_worst,
        }
        # Only attach stock_recommendations for actionable directions
        stock_recs = [rec] if action not in ("hold", "watch") else None

        # Build HTML content from detail analysis
        content = detail if detail else summary

        msg = MessageCreate(
            symbol=symbol,
            msg_type=msg_type,
            title=title,
            summary=summary,
            action_advice=action_advice,
            risk_note=risk_note,
            detail_analysis=detail,
            raw_data_ref=decision,
            content=content,
            priority="high" if action not in ("hold", "watch") else "medium",
            stock_recommendations=stock_recs,
        )

        await self._persist(msg)
        return msg

    # ------------------------------------------------------------------
    # Risk alert → message
    # ------------------------------------------------------------------

    async def translate_risk_alert(self, alert: dict) -> MessageCreate:
        """Convert risk signals to plain language warning.

        Expected alert keys:
            symbol, name, alert_type, severity, description,
            change_pct, stop_loss_pct, regime, thesis_invalidated
        """
        symbol = alert.get("symbol")
        name = alert.get("name", symbol or "市场")
        severity = alert.get("severity", "medium")
        description = alert.get("description", "")
        change_pct = alert.get("change_pct")
        thesis_invalidated = alert.get("thesis_invalidated", False)

        severity_labels = {
            "critical": "紧急风险提醒",
            "high": "重要风险提醒",
            "medium": "风险关注",
            "low": "温馨提示",
        }
        severity_cn = severity_labels.get(severity, "风险提醒")

        # Title
        if thesis_invalidated:
            title = f"{severity_cn}：{name} 之前看好的理由已经不成立了"
        elif change_pct is not None and change_pct < 0:
            title = f"{severity_cn}：{name} 已下跌 {_pct_to_chinese(change_pct)}"
        else:
            title = f"{severity_cn}：{name}"

        # Summary
        summary_parts = []
        if description:
            summary_parts.append(description)
        if thesis_invalidated:
            summary_parts.append("之前看好的理由已经不成立了，建议重新评估持仓。")
        if change_pct is not None:
            stop_loss_pct = alert.get("stop_loss_pct")
            if stop_loss_pct is not None:
                summary_parts.append(
                    f"当前跌幅 {_pct_to_chinese(change_pct)}，"
                    f"已触及止损线（{_pct_to_chinese(stop_loss_pct)}）。"
                )
        summary = (
            " ".join(summary_parts) if summary_parts else "AI 检测到风险信号，请关注。"
        )

        # Action advice
        if severity in ("critical", "high"):
            action_advice = "建议立即检查持仓，考虑减仓或止损"
        else:
            action_advice = "建议密切关注，做好应对准备"

        # Set priority based on severity
        if severity in ("critical", "high"):
            priority = "critical"
        else:
            priority = "high"

        msg = MessageCreate(
            symbol=symbol,
            msg_type="risk_alert",
            title=title,
            summary=summary,
            action_advice=action_advice,
            risk_note=description if description else None,
            raw_data_ref=alert,
            content=summary,
            priority=priority,
        )

        await self._persist(msg)
        return msg

    # ------------------------------------------------------------------
    # Market observation → message
    # ------------------------------------------------------------------

    async def translate_market_observation(self, observation: dict) -> MessageCreate:
        """Convert regime/market analysis to plain language.

        Expected observation keys:
            regime, direction, top_sectors, bottom_sectors,
            summary, global_summary, macro_events
        """
        regime = observation.get("regime", "unknown")
        direction = observation.get("direction", "")
        top_sectors = observation.get("top_sectors", [])
        bottom_sectors = observation.get("bottom_sectors", [])
        summary_text = observation.get("summary", "")

        regime_cn = _regime_label(regime)

        # Title
        title = f"大盘观察：{regime_cn}"

        # Summary
        summary_parts = [regime_cn + "。"]
        if direction:
            summary_parts.append(f"整体方向：{direction}。")
        if top_sectors:
            sectors_str = "、".join(top_sectors[:3])
            summary_parts.append(f"表现较好的板块：{sectors_str}。")
        if bottom_sectors:
            sectors_str = "、".join(bottom_sectors[:3])
            summary_parts.append(f"表现较弱的板块：{sectors_str}。")
        if summary_text:
            summary_parts.append(summary_text)
        summary = "".join(summary_parts)

        # Detail
        detail_parts = []
        global_summary = observation.get("global_summary")
        if global_summary:
            detail_parts.append(f"## 全球市场\n{global_summary}")
        macro_events = observation.get("macro_events")
        if macro_events:
            detail_parts.append(f"\n## 宏观事件\n{macro_events}")
        detail = "\n".join(detail_parts) if detail_parts else None

        msg = MessageCreate(
            symbol=None,
            msg_type="market_watch",
            title=title,
            summary=summary,
            detail_analysis=detail,
            raw_data_ref=observation,
        )

        await self._persist(msg)
        return msg

    # ------------------------------------------------------------------
    # Recommendation → message
    # ------------------------------------------------------------------

    async def translate_recommendation(self, rec: dict) -> MessageCreate:
        """Convert recommendation pipeline output to plain message.

        Expected rec keys:
            symbol, name, action, style, score, confidence,
            reason, risk_notes, entry_price, target_price, stop_loss,
            factors, sub_scores
        """
        symbol = rec.get("symbol", "")
        name = rec.get("name", symbol)
        action = rec.get("action", "buy")
        style = rec.get("style", "")
        confidence = rec.get("confidence", "medium")
        reason = rec.get("reason", "")
        risk_notes = rec.get("risk_notes", "")
        entry_price = rec.get("entry_price")
        target_price = rec.get("target_price")
        stop_loss = rec.get("stop_loss")
        score = rec.get("score", 0)

        style_labels = {
            "value": "价值投资",
            "growth": "成长投资",
            "momentum": "动量交易",
            "swing": "波段交易",
            "dividend": "红利收息",
            "sector": "板块轮动",
        }
        style_cn = style_labels.get(style, style)
        confidence_cn = _CONFIDENCE_LABELS.get(confidence, confidence)

        # Title
        title = f"AI{style_cn}推荐：{name}（{symbol}），{confidence_cn}"

        # Summary
        summary_parts = []
        if reason:
            # Truncate long reasons
            short_reason = reason[:200]
            if len(reason) > 200:
                short_reason += "..."
            summary_parts.append(short_reason)
        else:
            summary_parts.append(f"AI 综合评分 {score:.1f} 分，{confidence_cn}。")
        summary = "".join(summary_parts)

        # Action advice
        advice_parts = []
        if entry_price:
            advice_parts.append(f"建议入场价位 {entry_price:.2f} 元")
        if target_price:
            advice_parts.append(f"目标价位 {target_price:.2f} 元")
        if stop_loss:
            if isinstance(stop_loss, (int, float)):
                if stop_loss < 1:
                    # It's a percentage
                    advice_parts.append(
                        f"如果跌了 {_pct_to_chinese(stop_loss * 100)} 就该卖出止损"
                    )
                else:
                    advice_parts.append(f"止损价位 {stop_loss:.2f} 元")
        action_advice = "；".join(advice_parts) if advice_parts else None

        # Risk note
        risk_note = risk_notes if isinstance(risk_notes, str) and risk_notes else None

        # Detail analysis
        detail_parts = []
        if reason:
            detail_parts.append(f"## AI 分析理由\n{reason}")
        sub_scores = rec.get("sub_scores")
        if sub_scores and isinstance(sub_scores, dict):
            detail_parts.append("\n## 各维度评分")
            for dim, val in sub_scores.items():
                detail_parts.append(f"- {dim}: {val}")
        factors = rec.get("factors")
        if factors and isinstance(factors, dict):
            detail_parts.append("\n## 量化因子")
            for factor, val in factors.items():
                if isinstance(val, (int, float)):
                    detail_parts.append(f"- {factor}: {val:.2f}")
        detail = "\n".join(detail_parts) if detail_parts else None

        msg_type = "sell_signal" if action in ("sell", "reduce") else "buy_signal"

        # Build stock_recommendations for structured display
        direction = "SELL" if action in ("sell", "reduce") else "BUY"
        conf_cn = _CONFIDENCE_LABELS.get(confidence, confidence)
        stock_rec: dict[str, Any] = {
            "direction": direction,
            "symbol": symbol,
            "name": name,
            "buy_range": (
                [round(entry_price * 0.99, 2), round(entry_price * 1.01, 2)]
                if entry_price
                else None
            ),
            "stop_loss": round(stop_loss, 2)
            if isinstance(stop_loss, (int, float))
            else None,
            "target": round(target_price, 2) if target_price else None,
            "holding_days": rec.get("holding_period", "1-3天"),
            "reason": reason[:200] if reason else "",
            "confidence": conf_cn if isinstance(conf_cn, str) else "中",
        }

        msg = MessageCreate(
            symbol=symbol,
            msg_type=msg_type,
            title=title,
            summary=summary,
            action_advice=action_advice,
            risk_note=risk_note,
            detail_analysis=detail,
            raw_data_ref=rec,
            stock_recommendations=[stock_rec],
        )

        await self._persist(msg)
        return msg

    # ------------------------------------------------------------------
    # Scheduled briefing → message (PRD v37.0)
    # ------------------------------------------------------------------

    async def translate_scheduled_briefing(
        self, briefing: dict[str, Any]
    ) -> MessageCreate:
        """Convert a scheduled briefing dict to a plain-language message.

        Handles: pre_market, call_auction, late_session, post_market, holiday_intel.
        """
        msg_type = briefing.get("type", "pre_market")
        title = briefing.get("title", "")
        impact = briefing.get("impact", "NORMAL")
        symbol = briefing.get("symbol", "")

        formatter = _BRIEFING_FORMATTERS.get(msg_type, _format_generic_briefing)
        summary, action_advice, risk_note = formatter(briefing)

        # Determine priority based on briefing type
        _BRIEFING_PRIORITY: dict[str, str] = {
            "late_session": "high",
            "risk_alert": "critical",
            "post_market": "medium",
            "pre_market": "medium",
            "call_auction": "medium",
            "holiday_intel": "low",
        }
        priority = _BRIEFING_PRIORITY.get(msg_type, "medium")

        # Build content as HTML from formatted summary
        content = summary

        # Build stock_recommendations for late_session candidates
        stock_recommendations: list[dict] | None = None
        if msg_type == "late_session":
            candidates = briefing.get("candidates", [])
            if candidates:
                stock_recommendations = _candidates_to_stock_recommendations(candidates)

        # Build post_market_data for post_market briefings
        post_market_data: dict | None = None
        if msg_type == "post_market":
            post_market_data = {
                "portfolio_pnl": briefing.get("portfolio_pnl"),
                "hit_rate": briefing.get("hit_rate"),
                "recommendation_results": briefing.get("recommendation_results"),
                "next_day_outlook": briefing.get("next_day_outlook"),
            }
            # Remove None values
            post_market_data = {
                k: v for k, v in post_market_data.items() if v is not None
            }
            if not post_market_data:
                post_market_data = None

        msg = MessageCreate(
            symbol=symbol or None,
            msg_type=msg_type,
            title=title,
            summary=summary,
            action_advice=action_advice,
            risk_note=risk_note,
            impact=impact,
            content=content,
            priority=priority,
            stock_recommendations=stock_recommendations,
            post_market_data=post_market_data,
            expires_at=briefing.get("expires_at"),
        )

        await self._persist(msg)
        return msg


# ------------------------------------------------------------------
# Scheduled briefing formatters (PRD v37.0)
# Each returns (summary, action_advice, risk_note)
# ------------------------------------------------------------------


def _candidates_to_stock_recommendations(
    candidates: list[dict[str, Any]],
) -> list[dict]:
    """Convert late-session candidates to stock_recommendations JSON format.

    Matches the frontend StockRecommendation interface.
    """
    recs: list[dict] = []
    for c in candidates:
        # Parse entry_price_range string "12.34 - 12.56" → [12.34, 12.56]
        buy_range: list[float] | None = None
        if c.get("entry_price_low") and c.get("entry_price_high"):
            buy_range = [c["entry_price_low"], c["entry_price_high"]]
        elif c.get("entry_price_range"):
            try:
                parts = str(c["entry_price_range"]).split("-")
                if len(parts) == 2:
                    buy_range = [float(parts[0].strip()), float(parts[1].strip())]
            except (ValueError, IndexError):
                pass

        # Parse stop_loss — may be string like "12.34" or numeric
        stop_loss_val: float | None = None
        sl = c.get("stop_loss")
        if sl is not None:
            try:
                stop_loss_val = float(sl)
            except (ValueError, TypeError):
                pass

        # Parse target_price
        target_val: float | None = None
        tp = c.get("target_price")
        if tp is not None:
            try:
                target_val = float(tp)
            except (ValueError, TypeError):
                pass

        # Confidence: numeric → 高/中/低
        conf = c.get("confidence", 0.5)
        if isinstance(conf, (int, float)):
            conf_label = "高" if conf >= 0.7 else ("中" if conf >= 0.4 else "低")
        else:
            conf_label = str(conf)

        # Position pct — may be string like "10%" or numeric
        pos_pct: float | None = None
        pp = c.get("position_pct")
        if pp is not None:
            try:
                pos_pct = float(str(pp).replace("%", ""))
            except (ValueError, TypeError):
                pass

        # Determine direction from candidate action field
        action = c.get("action", "buy").lower()
        direction = "SELL" if action in ("sell", "reduce") else "BUY"

        rec: dict[str, Any] = {
            "direction": direction,
            "symbol": c.get("symbol", ""),
            "name": c.get("name", c.get("symbol", "")),
            "buy_range": buy_range,
            "position_pct": pos_pct,
            "stop_loss": stop_loss_val,
            "target": target_val,
            "holding_days": c.get("holding_period", "1-3天"),
            "reason": c.get("reason", ""),
            "confidence": conf_label,
        }
        recs.append(rec)
    return recs


def _format_pre_market_briefing(b: dict[str, Any]) -> tuple[str, str, str]:
    parts: list[str] = []
    if b.get("global_summary"):
        parts.append(f"隔夜外盘: {b['global_summary']}")
    if b.get("dragon_tiger_summary"):
        parts.append(f"昨日龙虎榜: {b['dragon_tiger_summary']}")
    if b.get("limit_up_summary"):
        parts.append(f"涨停分析: {b['limit_up_summary']}")
    if b.get("sentiment_cycle"):
        parts.append(f"情绪周期: {b['sentiment_cycle']}")
    summary = "\n".join(parts) if parts else "暂无盘前数据"
    mode = b.get("operation_mode", "steady")
    mode_labels = {
        "aggressive": "今日建议进攻模式，可适当加仓",
        "steady": "今日建议稳健模式，控制仓位",
        "defensive": "今日建议防守模式，减仓观望",
    }
    action_advice = mode_labels.get(mode, f"今日操作模式: {mode}")
    risk_note = b.get("risk_note", "注意控制仓位，严格执行止损")
    return summary, action_advice, risk_note


def _format_call_auction_briefing(b: dict[str, Any]) -> tuple[str, str, str]:
    parts: list[str] = []
    if b.get("held_analysis"):
        parts.append(f"持仓股表现: {b['held_analysis']}")
    if b.get("watchlist_highlights"):
        parts.append(f"关注股亮点: {b['watchlist_highlights']}")
    if b.get("gap_analysis"):
        parts.append(f"跳空分析: {b['gap_analysis']}")
    summary = "\n".join(parts) if parts else "集合竞价数据暂无"
    return (
        summary,
        b.get("action_advice", "等待开盘确认方向"),
        b.get("risk_note", "竞价数据仅供参考，开盘后可能反转"),
    )


def _format_late_session_briefing(b: dict[str, Any]) -> tuple[str, str, str]:
    candidates = b.get("candidates", [])
    if not candidates:
        return (
            b.get("summary", "今日尾盘无合适买入标的"),
            b.get("action_advice", "继续观望，等待更好时机"),
            b.get("risk_note", "空仓也是一种策略"),
        )
    parts: list[str] = []
    for i, c in enumerate(candidates, 1):
        name = c.get("name", c.get("symbol", ""))
        status = c.get("status", "recommended")
        line = f"{i}. {name}"
        if status == "cancelled":
            line += " [已取消]"
        elif status == "adjusted":
            line += " [已调整]"
        if c.get("entry_price_range"):
            action = c.get("action", "buy").lower()
            action_label = "建议卖出" if action in ("sell", "reduce") else "建议买入"
            line += f" | {action_label}: {c['entry_price_range']}"
        if c.get("position_pct"):
            line += f" | 仓位: {c['position_pct']}"
        if c.get("stop_loss"):
            line += f" | 止损: {c['stop_loss']}"
        if c.get("target_price"):
            line += f" | 目标: {c['target_price']}"
        if c.get("confidence"):
            line += f" | 置信度: {c['confidence']:.0%}"
        if c.get("reason"):
            line += f"\n   原因: {c['reason']}"
        parts.append(line)
    return (
        "\n".join(parts),
        b.get("action_advice", "以上为AI建议，请根据个人风险承受能力决定"),
        b.get("risk_note", "超短线操作风险较高，务必严格止损"),
    )


def _format_post_market_briefing(b: dict[str, Any]) -> tuple[str, str, str]:
    parts: list[str] = []
    if b.get("portfolio_pnl"):
        parts.append(f"今日盈亏: {b['portfolio_pnl']}")
    if b.get("hit_rate"):
        parts.append(f"推荐命中率: {b['hit_rate']}")
    if b.get("recommendation_results"):
        parts.append(f"推荐结果: {b['recommendation_results']}")
    summary = "\n".join(parts) if parts else "今日收盘数据汇总中"
    return (
        summary,
        b.get("next_day_outlook", "明日操作计划待盘后复盘确定"),
        b.get("risk_note", ""),
    )


def _format_holiday_intel_briefing(b: dict[str, Any]) -> tuple[str, str, str]:
    parts: list[str] = []
    if b.get("global_summary"):
        parts.append(f"全球市场: {b['global_summary']}")
    if b.get("policy_news"):
        parts.append(f"政策动态: {b['policy_news']}")
    if b.get("industry_news"):
        parts.append(f"行业资讯: {b['industry_news']}")
    if b.get("geopolitical"):
        parts.append(f"地缘政治: {b['geopolitical']}")
    if b.get("action_plan"):
        parts.append(f"下个交易日计划: {b['action_plan']}")
    summary = "\n".join(parts) if parts else "休市期间暂无重大消息"
    return (
        summary,
        b.get("action_advice", "休市期间保持关注，做好下一交易日准备"),
        b.get("risk_note", "节假日外盘波动可能影响开盘走势"),
    )


def _format_generic_briefing(b: dict[str, Any]) -> tuple[str, str, str]:
    return b.get("summary", ""), b.get("action_advice", ""), b.get("risk_note", "")


_BRIEFING_FORMATTERS: dict[str, Any] = {
    "pre_market": _format_pre_market_briefing,
    "call_auction": _format_call_auction_briefing,
    "late_session": _format_late_session_briefing,
    "post_market": _format_post_market_briefing,
    "holiday_intel": _format_holiday_intel_briefing,
}
