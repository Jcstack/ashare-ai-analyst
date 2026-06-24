"""DecisionHandler — extracted decision parsing and publishing logic.

DRY extraction from HeartbeatAgent. Centralises JSON extraction from
LLM responses, decision validation, and publishing to MessageStore + Redis.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from src.agent_loop.agent_state import AgentDecision, AgentState
from src.utils.logger import get_logger

# When LLM omits confidence, use action-based floor (not silent 0.5)
_CONFIDENCE_FLOOR: dict[str, float] = {
    "buy": 0.3,
    "sell": 0.3,
    "add": 0.3,
    "reduce": 0.3,
    "hold": 0.4,
    "no_trade": 0.4,
    "watch": 0.2,
}

logger = get_logger("agent_loop.decision_handler")


class DecisionHandler:
    """Parses LLM responses for decisions and publishes them.

    Attributes:
        message_store: MessageStore instance for persistence.
        redis_client: Redis client for pub/sub notifications.
    """

    def __init__(
        self,
        message_store: Any = None,
        redis_client: Any = None,
    ) -> None:
        self._message_store = message_store
        self._redis = redis_client

    @staticmethod
    def _store_thesis(symbol: str, decision: dict[str, Any]) -> None:
        """Store original buy thesis in Redis for subsequent hold decisions to reference.

        Stored as ``thesis:{symbol}`` with 30-day TTL so that the heartbeat
        agent can inject the original plan into the LLM context, preventing
        target-price drift from anchoring bias.

        IMPORTANT: Never overwrite an existing thesis. The first buy thesis
        is the master plan — subsequent buy recommendations for the same
        stock must not drift the targets.
        """
        try:
            from src.web.dependencies import get_redis

            r = get_redis()
            if not r:
                return

            # Never overwrite existing thesis — first buy is the master plan
            existing = r.get(f"thesis:{symbol}")
            if existing:
                logger.debug(
                    "Thesis for %s already exists — preserving original plan",
                    symbol,
                )
                return

            thesis = {
                "entry_price": decision.get("entry_price"),
                "stop_loss": decision.get("stop_loss"),
                "target_price": decision.get("target_price"),
                "summary": (decision.get("summary") or "")[:200],
                "created_at": datetime.now(UTC).isoformat(),
            }
            r.setex(
                f"thesis:{symbol}",
                30 * 86400,
                json.dumps(thesis, ensure_ascii=False),
            )
            logger.info(
                "Stored thesis for %s: tp=%s sl=%s",
                symbol,
                thesis["target_price"],
                thesis["stop_loss"],
            )
        except Exception:
            pass

    @staticmethod
    def parse_decisions(text: str) -> list[dict[str, Any]]:
        """Extract structured decisions from an LLM response.

        Searches for JSON blocks containing a ``decisions`` array,
        supporting both fenced markdown and inline JSON. Falls back
        to extracting stock mentions with hold/buy/sell context from
        natural language when JSON is absent.

        Args:
            text: Raw LLM response text.

        Returns:
            List of decision dicts, or empty list if none found.
        """
        if not text:
            return []

        # Primary: look for JSON blocks
        try:
            patterns = [
                r"```json\s*\n?(.*?)\n?\s*```",
                r"(\{[^{}]*\"decisions\"[^{}]*\[.*?\]\s*\})",
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.DOTALL):
                    try:
                        parsed = json.loads(match.group(1))
                        if isinstance(parsed, dict) and "decisions" in parsed:
                            decisions = parsed["decisions"]
                            if isinstance(decisions, list):
                                return [d for d in decisions if isinstance(d, dict)]
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except Exception:
            pass

        # Fallback: extract decisions from natural language text
        # When the LLM writes a report instead of JSON, mine it for decisions
        return DecisionHandler._extract_decisions_from_text(text)

    @staticmethod
    def _extract_decisions_from_text(text: str) -> list[dict[str, Any]]:
        """Mine decisions from natural language when LLM didn't output JSON.

        Looks for stock code mentions (6-digit) near action keywords
        (持有/买入/卖出/止损) and price numbers to build basic decisions.
        """
        decisions: list[dict[str, Any]] = []
        seen_symbols: set[str] = set()

        # Find 6-digit stock codes with name and surrounding context
        # Handles: "烽火通信(600498)" / "烽火通信 (600498)" / "**烽火通信 (600498)**"
        for match in re.finditer(
            r"[*]*(\S{2,8})\s*[（(\[]*(\d{6})[）)\]]*[*]*"  # name + code
            r"([\s\S]{0,400}?)"  # context (non-greedy)
            r"(?=\n[*#]|\n\d{6}|\Z)",  # stop at next heading/stock/end
            text,
        ):
            name = (match.group(1) or "").strip().strip("*").strip("(（")
            symbol = match.group(2)
            context = match.group(3)

            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)

            # Determine action from context
            action = "hold"
            if re.search(r"买入|加仓|建议买", context):
                action = "buy"
            elif re.search(r"卖出|减仓|清仓|止损.*卖", context):
                action = "sell"

            # Extract stop-loss price
            stop_loss = None
            sl_match = re.search(r"止损[：:价位]?\s*(\d+\.?\d*)", context)
            if sl_match:
                stop_loss = float(sl_match.group(1))

            # Extract target price
            target = None
            tgt_match = re.search(r"目标[：:价位]?\s*(\d+\.?\d*)", context)
            if tgt_match:
                target = float(tgt_match.group(1))

            # Extract a summary from the context
            summary = context.strip()[:200].split("\n")[0].strip()
            if not summary:
                continue

            decisions.append(
                {
                    "type": "hold_update" if action == "hold" else f"{action}_signal",
                    "action": action,
                    "symbol": symbol,
                    "name": name,
                    "stop_loss": stop_loss,
                    "target_price": target,
                    "confidence": 0.5,
                    "summary": summary,
                    "risk_note": "",
                    "_source": "text_extraction",
                }
            )

        if decisions:
            logger.info(
                "Extracted %d decisions from text (no JSON found)", len(decisions)
            )
        return decisions

    @staticmethod
    def validate_decision(decision: dict[str, Any]) -> str | None:
        """Validate a single decision for trading safety.

        Returns:
            None if valid, or a string describing the rejection reason.
        """
        action = decision.get("action", "")
        if action not in ("buy", "sell", "add", "reduce"):
            # Non-trade actions (hold, watch) don't need validation
            return None

        shares = int(decision.get("shares", 0))
        shares = (shares // 100) * 100
        if shares < 100:
            return f"shares too small after rounding: {decision.get('shares', 0)} -> {shares}"

        # entry_price required for buy/add, optional for sell/reduce
        entry_price = decision.get("entry_price")
        entry_price_f = 0.0
        if action in ("buy", "add"):
            try:
                entry_price_f = float(entry_price)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return f"entry_price not numeric: {entry_price!r}"
            if entry_price_f <= 0:
                return f"entry_price must be > 0, got {entry_price_f}"
        elif entry_price:
            try:
                entry_price_f = float(entry_price)
            except (TypeError, ValueError):
                pass  # sell/reduce: entry_price is optional

        if action in ("buy", "add"):
            stop_loss = decision.get("stop_loss")
            if stop_loss is not None:
                try:
                    stop_loss_f = float(stop_loss)
                    if stop_loss_f >= entry_price_f:
                        return (
                            f"stop_loss ({stop_loss_f}) >= entry_price "
                            f"({entry_price_f}) for {action}"
                        )
                except (TypeError, ValueError):
                    return f"stop_loss not numeric: {stop_loss!r}"

            target_price = decision.get("target_price")
            if target_price is not None:
                try:
                    target_f = float(target_price)
                    if target_f <= entry_price_f:
                        return (
                            f"target_price ({target_f}) <= entry_price "
                            f"({entry_price_f}) for {action}"
                        )
                except (TypeError, ValueError):
                    return f"target_price not numeric: {target_price!r}"

        return None

    async def push_single_decision(
        self,
        decision: dict[str, Any],
        state: AgentState,
        source_name: str,
    ) -> bool:
        """Validate and publish a single decision. Returns True if pushed.

        This is the core decision pipeline: symbol validation, trade validation,
        convergence gate, risk gate, calibration, and finally publishing to
        MessageStore + Redis + calibration DB + memory store + outcome tracker.

        Args:
            decision: A single decision dict (action, symbol, confidence, etc.).
            state: Current agent state (decisions are appended).
            source_name: Mission key or ``"tool_call"`` for attribution.

        Returns:
            True if the decision was successfully pushed, False otherwise.
        """
        if not self._message_store:
            return False

        # ── Same-day decision consistency guards ──
        # 1. Buy dedup: don't push repeated buy signals for a stock already
        #    recommended today. The user already got the signal.
        # 2. Same-day sell protection: if we recommended buying today with
        #    hold_days > 0, don't flip to sell unless stop-loss is hit.
        action = decision.get("action", "")
        symbol_raw = (decision.get("symbol") or "").strip()
        if re.fullmatch(r"\d{6}", symbol_raw) and state.decisions:
            today_actions = [d for d in state.decisions if d.symbol == symbol_raw]
            if action in ("buy", "add") and today_actions:
                prev_buys = [d for d in today_actions if d.action in ("buy", "add")]
                if prev_buys:
                    logger.info(
                        "Buy dedup: %s already recommended today (%d times), skipping",
                        symbol_raw,
                        len(prev_buys),
                    )
                    return False

            if action == "sell" and today_actions:
                prev_buys = [d for d in today_actions if d.action in ("buy", "add")]
                if prev_buys:
                    # Only allow same-day sell if stop-loss is genuinely hit
                    is_stop_loss = "止损" in (decision.get("summary") or "")
                    if not is_stop_loss and self._redis:
                        try:
                            raw_thesis = self._redis.get(f"thesis:{symbol_raw}")
                            if raw_thesis:
                                thesis = json.loads(raw_thesis)
                                from src.data.realtime import RealtimeQuoteManager

                                q = RealtimeQuoteManager().get_single_quote(symbol_raw)
                                current = float(q.get("price", 0)) if q else 0
                                thesis_sl = float(thesis.get("stop_loss") or 0)
                                if current and thesis_sl and current > thesis_sl:
                                    logger.warning(
                                        "Same-day sell blocked: %s bought today, "
                                        "current=%.2f > stop=%.2f, not a stop-loss",
                                        symbol_raw,
                                        current,
                                        thesis_sl,
                                    )
                                    return False
                        except Exception:
                            pass

        # Reject invalid symbols early (e.g. "CASH", "", non-6-digit)
        symbol = (decision.get("symbol") or "").strip()
        if not re.fullmatch(r"\d{6}", symbol):
            action = decision.get("action", "")
            if action in ("hold", "watch", "no_trade"):
                logger.debug("Skipping [%s] — invalid symbol %r", action, symbol)
                return False
            # buy/sell with bad symbol: log and skip
            if action in ("buy", "sell", "add", "reduce"):
                logger.warning("Rejected [%s] — invalid symbol %r", action, symbol)
                return False

        # Validate trade decisions
        action = decision.get("action", "")
        if action in ("buy", "sell", "add", "reduce"):
            rejection = self.validate_decision(decision)
            if rejection:
                logger.warning(
                    "Rejected decision [%s %s]: %s",
                    action,
                    decision.get("symbol", "?"),
                    rejection,
                )
                return False

        # Convergence gate: buy/add must align with prediction pipeline
        if action in ("buy", "add"):
            if not self._check_convergence(decision):
                logger.warning(
                    "Convergence gate blocked [%s %s]: quant pipeline disagrees",
                    action,
                    decision.get("symbol", "?"),
                )
                decision["action"] = "watch"
                decision["summary"] = f"[降级:量化分歧] {decision.get('summary', '')}"
                action = "watch"

        # Hard risk gate for buy/add — kill switch, circuit breaker, preflight
        if action in ("buy", "add"):
            veto_reason = self._hard_risk_check(decision)
            if veto_reason:
                logger.warning(
                    "Risk VETO [%s %s]: %s",
                    action,
                    decision.get("symbol", "?"),
                    veto_reason,
                )
                decision["action"] = "watch"
                decision["summary"] = (
                    f"[风控否决] {veto_reason}。{decision.get('summary', '')}"
                )
                decision["risk_note"] = veto_reason
                action = "watch"

        msg_type = decision.get("type", "market_insight")
        symbol = decision.get("symbol")
        name = decision.get("name", symbol or "")
        title = decision.get("title", "")
        summary = decision.get("summary", "")
        risk_note = decision.get("risk_note", "")
        raw_conf = decision.get("confidence")
        if raw_conf is not None:
            try:
                confidence = float(raw_conf)
                confidence = max(
                    0.0,
                    min(
                        1.0,
                        confidence if confidence <= 1.0 else confidence / 100,
                    ),
                )
            except (TypeError, ValueError):
                confidence = 0.3
        else:
            confidence = _CONFIDENCE_FLOOR.get(action, 0.3)
            logger.warning(
                "LLM omitted confidence for [%s %s], using floor %.2f",
                action,
                decision.get("symbol", "?"),
                confidence,
            )

        # Immediate stop-loss enforcement — check BOTH thesis and PnLTracker
        if action == "hold" and symbol:
            try:
                from src.data.realtime import RealtimeQuoteManager
                from src.web.dependencies import get_redis

                _r = get_redis()
                # Get current price
                q = RealtimeQuoteManager().get_single_quote(symbol)
                current = float(q.get("price", 0)) if q else 0

                if current and _r:
                    # Priority 1: check thesis stop loss (original buy plan)
                    raw_thesis = _r.get(f"thesis:{symbol}")
                    if raw_thesis:
                        thesis = json.loads(raw_thesis)
                        thesis_sl = float(thesis.get("stop_loss") or 0)
                        if thesis_sl and current <= thesis_sl:
                            logger.warning(
                                "THESIS STOP-LOSS: %s current=%.2f <= "
                                "original_stop=%.2f",
                                symbol,
                                current,
                                thesis_sl,
                            )
                            decision["action"] = "sell"
                            decision["type"] = "sell_signal"
                            decision["priority"] = "critical"
                            decision["summary"] = (
                                f"🚨 止损触发: 当前{current:.2f}"
                                f" <= 原始止损{thesis_sl:.2f}"
                            )
                            action = "sell"

                    # Priority 2: check PnLTracker stop loss
                    if action == "hold":
                        try:
                            from src.trading.pnl_tracker import PnLTracker

                            tracker = PnLTracker(redis_client=_r)
                            for track in tracker.get_active_tracks():
                                if track.symbol == symbol and track.stop_loss:
                                    if current <= track.stop_loss:
                                        logger.warning(
                                            "STOP-LOSS BREACH: %s current="
                                            "%.2f <= stop=%.2f",
                                            symbol,
                                            current,
                                            track.stop_loss,
                                        )
                                        decision["action"] = "sell"
                                        decision["type"] = "sell_signal"
                                        decision["priority"] = "critical"
                                        decision["summary"] = (
                                            f"🚨 止损触发: 当前{current:.2f}"
                                            f" <= 止损线{track.stop_loss:.2f}"
                                        )
                                        action = "sell"
                                        break
                        except Exception:
                            pass
            except Exception:
                pass

        # === Safety-only calibration (Agent learns judgment via prompt,
        #     code only prevents extremes) ===

        # Safety net: only cap truly extreme overconfidence (0.95+)
        if confidence >= 0.95:
            old_conf = confidence
            confidence = 0.85
            logger.info(
                "Safety cap: [%s %s] %.0f%%->85%% (extreme)",
                action,
                symbol or "?",
                old_conf * 100,
            )

        # ConfidenceCalibrator still applies (learned from data, not hard rule)
        try:
            from src.agent_loop.confidence_calibrator import (
                ConfidenceCalibrator,
            )

            cc = ConfidenceCalibrator(
                db_path="data/decisions.db",
                config={"min_samples_for_calibration": 5},
            )
            calibrated = cc.calibrate(confidence, symbol or "", action)
            if abs(calibrated - confidence) > 0.01:
                logger.info(
                    "Calibrator: [%s %s] %.0f%%->%.0f%%",
                    action,
                    symbol or "?",
                    confidence * 100,
                    calibrated * 100,
                )
                confidence = calibrated
        except Exception:
            pass

        priority = decision.get("priority", "medium")

        if not summary and action == "hold":
            return False

        # Warn (don't block) for near-limit-up stocks — 打板 is a valid strategy
        # The LLM should know but code should not block opportunities
        if action in ("buy", "add") and symbol:
            try:
                from src.data.realtime import RealtimeQuoteManager

                mgr = RealtimeQuoteManager()
                q = mgr.get_single_quote(symbol)
                if q:
                    pct = float(q.get("pct_change", q.get("change_pct", 0)) or 0)
                    if pct >= 9.5:
                        logger.info(
                            "Buy %s at %.1f%% (near limit-up / 打板)",
                            symbol,
                            pct,
                        )
            except Exception:
                pass

        # Skip hold/watch for stocks we don't own
        if action in ("hold", "watch") and symbol:
            try:
                from src.web.dependencies import get_portfolio_store

                ps = get_portfolio_store()
                positions = ps.list_positions()
                held = {p.get("symbol", "") for p in positions}
                if symbol not in held:
                    logger.debug("Skipping hold for unowned stock %s", symbol)
                    return False
            except Exception:
                pass

        action_advice = ""
        trade_data: dict[str, Any] | None = None
        if action in ("buy", "sell", "add", "reduce"):
            shares = int(decision.get("shares", 0))
            shares = (shares // 100) * 100
            entry_price = decision.get("entry_price")
            stop_loss = decision.get("stop_loss")
            target_price = decision.get("target_price")
            # buy/add need entry_price; sell/reduce don't (market price)
            can_build = (
                (shares > 0 and entry_price)
                if action in ("buy", "add")
                else (shares > 0)
            )
            if can_build:
                trade_data = {
                    "action": action,
                    "symbol": symbol,
                    "name": name,
                    "shares": shares,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "target_price": target_price,
                    "confidence": confidence,
                    "hold_days": decision.get("hold_days"),
                }

                # Reward/risk ratio gate for buy/add
                if action in ("buy", "add"):
                    ep = float(entry_price or 0)
                    sl = float(stop_loss or 0)
                    tp = float(target_price or 0)
                    if ep and sl and tp and ep > sl:
                        reward = (tp - ep) / ep
                        risk = (ep - sl) / ep
                        rr_ratio = reward / risk if risk > 0 else 0
                        trade_data["rr_ratio"] = round(rr_ratio, 1)
                        if rr_ratio < 1.5:
                            logger.info(
                                "Low R/R ratio %.1f for %s — downgrading to watch",
                                rr_ratio,
                                symbol,
                            )
                            action = "watch"
                            decision["action"] = "watch"
                            decision["summary"] = "[R/R<1.5] " + decision.get(
                                "summary", ""
                            )

                action_advice = (
                    f"{action} {shares}股 @{entry_price}"
                    f" 止损{stop_loss or '?'} 目标{target_price or '?'}"
                )
        elif action == "no_trade":
            # "no_trade" means "do nothing" — don't push any message
            logger.debug("Skipping no_trade for %s", symbol or "N/A")
            return False
        elif action in ("hold", "watch"):
            # Structured data for hold/watch — includes sell conditions
            trade_data = {
                "action": action,
                "symbol": symbol,
                "name": name,
                "confidence": confidence,
                "stop_loss": decision.get("stop_loss"),
                "target_price": decision.get("target_price"),
            }
            # Build informative action_advice for holds
            parts = []
            if decision.get("stop_loss"):
                parts.append(f"止损{decision['stop_loss']}")
            if decision.get("target_price"):
                parts.append(f"目标{decision['target_price']}")
            if parts:
                action_advice = f"持有 | {' | '.join(parts)}"

        # Thesis-anchored target price guard for holds
        if action == "hold" and symbol:
            try:
                from src.web.dependencies import get_redis

                _r = get_redis()
                if _r:
                    raw_thesis = _r.get(f"thesis:{symbol}")
                    if raw_thesis:
                        thesis = json.loads(raw_thesis)
                        orig_tp = thesis.get("target_price")
                        orig_sl = thesis.get("stop_loss")
                        new_tp = decision.get("target_price")
                        new_sl = decision.get("stop_loss")

                        # Guard: target must not drop below original thesis
                        # unless there's a fundamental reason (利空/业绩等)
                        if orig_tp and new_tp and float(new_tp) < float(orig_tp):
                            fundamental_keywords = [
                                "利空",
                                "业绩",
                                "暴雷",
                                "监管",
                                "退市",
                                "减持",
                                "基本面",
                                "恶化",
                                "下调",
                                "警告",
                            ]
                            has_reason = any(
                                kw in summary for kw in fundamental_keywords
                            )
                            if not has_reason:
                                logger.info(
                                    "Thesis guard: %s tp %.2f→%.2f restored "
                                    "to original %.2f (no fundamental reason)",
                                    symbol,
                                    float(new_tp),
                                    float(orig_tp),
                                    float(orig_tp),
                                )
                                decision["target_price"] = orig_tp
                                if trade_data:
                                    trade_data["target_price"] = orig_tp

                        # Guard: stop loss must NEVER get looser than original
                        # This is the iron rule — 止损铁律
                        if orig_sl and new_sl and float(new_sl) < float(orig_sl):
                            logger.info(
                                "Thesis guard: %s sl %.2f→%.2f restored "
                                "to original %.2f (止损不能放松)",
                                symbol,
                                float(new_sl),
                                float(orig_sl),
                                float(orig_sl),
                            )
                            decision["stop_loss"] = orig_sl
                            if trade_data:
                                trade_data["stop_loss"] = orig_sl
            except Exception:
                pass

        if not title and action and (symbol or name):
            labels = {
                "buy": "建议买入",
                "sell": "建议卖出",
                "add": "建议加仓",
                "reduce": "建议减仓",
                "hold": "继续持有",
            }
            title = f"{labels.get(action, action)} {name}"

        if not title and not summary:
            return False

        # Force CRITICAL push tier for buy/sell so Discord always delivers
        if trade_data and action in ("buy", "add"):
            store_type = "buy_signal"
        elif trade_data and action in ("sell", "reduce"):
            store_type = "sell_signal"
        elif trade_data and action in ("hold", "watch"):
            store_type = "hold_update"  # Always push holding updates
        elif trade_data:
            store_type = "trading_signal"
        else:
            store_type = msg_type
        now = datetime.now(UTC)

        msg_id = self._message_store.create_message(
            symbol=symbol,
            msg_type=store_type,
            title=title,
            summary=summary,
            content=summary,
            priority=priority,
            action_advice=action_advice or summary,
            risk_note=risk_note,
            stock_recommendations=(
                json.dumps([trade_data], ensure_ascii=False) if trade_data else None
            ),
            raw_data_ref={
                "source": "heartbeat_agent",
                "mission": source_name,
                "confidence": confidence,
                "action": action,
            },
            data_freshness="realtime",
            data_collected_at=now.isoformat(),
        )

        self._publish_to_redis(
            {
                "type": store_type,
                "symbol": symbol or "",
                "name": name,
                "title": title,
                "summary": summary,
                "priority": priority,
                "action_advice": action_advice or summary,
                "risk_note": risk_note,
                "confidence": confidence,
                "message_id": msg_id,
                **(trade_data or {}),
            }
        )

        state.add_decision(
            AgentDecision(
                timestamp=datetime.now(UTC).strftime("%H:%M"),
                action=action,
                symbol=symbol or "",
                summary=summary[:100],
                confidence=confidence,
                details={"mission": source_name, **(trade_data or {})},
            )
        )

        # Write to decisions.db for calibration feedback loop
        self._write_to_calibration_db(
            symbol=symbol or "",
            action=action,
            confidence=confidence,
            entry_price=decision.get("entry_price"),
        )

        # Write to long-term knowledge store
        self._write_to_memory_store(
            symbol=symbol or "",
            action=action,
            confidence=confidence,
            summary=summary,
            risk_note=risk_note,
        )

        # Register for T+1/3/5 outcome tracking (feedback loop)
        if action in ("buy", "sell", "add", "reduce") and symbol:
            self._track_outcome(
                symbol=symbol,
                action=action,
                confidence=confidence,
                entry_price=decision.get("entry_price"),
                name=name,
            )

        # Store thesis for buy/add so subsequent heartbeats can reference original plan
        if action in ("buy", "add") and symbol:
            self._store_thesis(symbol, decision)

        logger.info(
            "Decision: [%s] %s %s (confidence=%.2f)",
            msg_type,
            action,
            symbol or "N/A",
            confidence,
        )
        return True

    async def push_decisions(
        self,
        decisions: list[dict[str, Any]],
        state: AgentState,
        source_name: str,
    ) -> int:
        """Validate and publish decisions to MessageStore + Redis.

        Iterates over parsed decisions and delegates each to
        ``push_single_decision``.

        Args:
            decisions: Parsed decision dicts from ``parse_decisions``.
            state: Current agent state (decisions are appended).
            source_name: Mission key for attribution.

        Returns:
            Number of decisions successfully pushed.
        """
        if not decisions or not self._message_store:
            return 0

        pushed = 0
        for decision in decisions:
            try:
                if await self.push_single_decision(decision, state, source_name):
                    pushed += 1
            except Exception as exc:
                logger.error("Failed to push decision: %s", exc, exc_info=True)

        return pushed

    async def push_briefing(
        self,
        response_text: str,
        now_cst: datetime,
        state: AgentState,
        mission_key: str,
        msg_type_map: dict[str, str] | None = None,
    ) -> None:
        """Publish a mission briefing to MessageStore + Redis.

        Args:
            response_text: Full LLM response text (JSON blocks stripped).
            now_cst: Current time in CST.
            state: Current agent state.
            mission_key: Mission key for title and type mapping.
            msg_type_map: Optional mapping of mission_key -> message type.
        """
        if not self._message_store:
            return

        # Strip all JSON from briefing text — fenced blocks, decisions, fragments
        summary = re.sub(
            r"```json\s*\n?.*?\n?\s*```", "", response_text, flags=re.DOTALL
        )
        # Greedy match: entire {"decisions": [...]} block including nested objects
        summary = re.sub(r'\{\s*"decisions"\s*:.*\}', "", summary, flags=re.DOTALL)
        # Remove any remaining JSON-like fragments
        summary = re.sub(r"\{[^{}]*\}", "", summary)
        # Clean up leftover punctuation from stripped JSON
        summary = re.sub(r"[\[\],]+\s*", "", summary)
        summary = summary.strip()
        if not summary or len(summary) < 20:
            return

        # Import _MISSIONS lazily to avoid circular import
        from src.agent_loop.heartbeat_agent import _MISSIONS

        mission = _MISSIONS.get(mission_key, {})
        title = f"{mission.get('name', mission_key)} {now_cst.strftime('%H:%M')}"

        default_type_map = {
            "morning_plan": "pre_market",
            "close_review": "post_market",
            "decision_window": "late_session",
        }
        type_map = msg_type_map or default_type_map
        msg_type = type_map.get(mission_key, "market_insight")
        now = datetime.now(UTC)

        msg_id = self._message_store.create_message(
            msg_type=msg_type,
            title=title,
            summary=summary[:500],
            content=summary,
            priority="medium" if mission_key == "idle_check" else "high",
            action_advice=summary[:200],
            raw_data_ref={"source": "heartbeat_agent", "mission": mission_key},
            data_freshness="realtime",
            data_collected_at=now.isoformat(),
        )

        self._publish_to_redis(
            {
                "type": msg_type,
                "title": title,
                "summary": summary[:500],
                "action_advice": summary[:200],
                "priority": "medium" if mission_key == "idle_check" else "high",
                "message_id": msg_id,
            }
        )

        state.add_finding(summary[:200])

    # Class-level tool usage log — set by HeartbeatAgent after each run
    _last_tools_used: list[str] = []
    _last_tools_failed: list[str] = []

    @classmethod
    def set_tool_context(
        cls, tools_used: list[str], tools_failed: list[str] | None = None
    ) -> None:
        """Record which tools were called in the current agent run.

        Called by HeartbeatAgent after AgentLoop completes, before
        push_decisions. This context is saved alongside each decision
        for retrospective analysis of data availability vs accuracy.
        """
        cls._last_tools_used = tools_used or []
        cls._last_tools_failed = tools_failed or []

    @staticmethod
    def _write_to_calibration_db(
        symbol: str,
        action: str,
        confidence: float,
        entry_price: float | None = None,
    ) -> None:
        """Write decision to decisions.db for calibration feedback loop.

        Includes data_context: which tools were used/failed, so we can
        later analyze whether wrong decisions correlate with missing data.
        """
        try:
            import sqlite3
            import uuid
            from pathlib import Path

            db_path = Path("data/decisions.db")
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                """CREATE TABLE IF NOT EXISTS decisions (
                    proposal_id TEXT PRIMARY KEY, symbol TEXT, action TEXT,
                    confidence REAL, decided_at TEXT, entry_price REAL,
                    sector TEXT DEFAULT '', t1_price REAL, t3_price REAL,
                    t5_price REAL, t1_return_pct REAL, t3_return_pct REAL,
                    t5_return_pct REAL, direction_correct INTEGER,
                    data_context TEXT)"""
            )

            # Auto-add data_context column if table was created before this change
            try:
                conn.execute("SELECT data_context FROM decisions LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE decisions ADD COLUMN data_context TEXT")

            # Get current price as entry_price if not provided
            ep = entry_price
            if ep is None and symbol:
                try:
                    from src.data.realtime import RealtimeQuoteManager

                    mgr = RealtimeQuoteManager()
                    q = mgr.get_single_quote(symbol)
                    if q and q.get("price"):
                        ep = float(q["price"])
                except Exception:
                    pass

            # Build data context for retrospective analysis
            ctx = json.dumps(
                {
                    "tools_used": DecisionHandler._last_tools_used,
                    "tools_failed": DecisionHandler._last_tools_failed,
                    "tools_count": len(DecisionHandler._last_tools_used),
                    "has_fund_flow": any(
                        "fund_flow" in t for t in DecisionHandler._last_tools_used
                    ),
                    "has_global": any(
                        "global" in t for t in DecisionHandler._last_tools_used
                    ),
                    "has_intel": any(
                        "intel" in t or "news" in t
                        for t in DecisionHandler._last_tools_used
                    ),
                    "has_sector": any(
                        "sector" in t or "concept" in t
                        for t in DecisionHandler._last_tools_used
                    ),
                },
                ensure_ascii=False,
            )

            conn.execute(
                """INSERT OR IGNORE INTO decisions
                   (proposal_id, symbol, action, confidence, decided_at,
                    entry_price, data_context)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"live-{uuid.uuid4().hex[:8]}",
                    symbol,
                    action,
                    confidence,
                    datetime.now(UTC).isoformat(),
                    ep,
                    ctx,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("Failed to write to calibration DB: %s", exc)

    @staticmethod
    def _write_to_memory_store(
        symbol: str,
        action: str,
        confidence: float,
        summary: str,
        risk_note: str,
    ) -> None:
        """Write decision to MemoryStore for long-term knowledge retrieval."""
        if not symbol or not summary:
            return
        try:
            import time

            from src.intelligence.memory_store import MemoryStore

            ms = MemoryStore()
            content = f"{symbol} {action} (conf={confidence:.0%}): {summary}"
            if risk_note:
                content += f" 风险: {risk_note}"

            ms.store(
                content=content[:500],
                category="insight",
                symbol=symbol,
                metadata={
                    "symbol": symbol,
                    "action": action,
                    "confidence": confidence,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M"),
                },
            )
        except Exception:
            pass

    @staticmethod
    def _track_outcome(
        symbol: str,
        action: str,
        confidence: float,
        entry_price: float | None = None,
        name: str = "",
    ) -> None:
        """Register decision for T+1/3/5 outcome tracking.

        Feeds the core feedback loop: every buy/sell is tracked, then
        evaluated at T+1/3/5 to calibrate Bayesian tables.
        """
        try:
            from src.agent_loop.outcome_tracker import OutcomeTracker

            tracker = OutcomeTracker()
            tracker.track_decision(
                symbol=symbol,
                action=action,
                confidence=confidence,
                entry_price=float(entry_price) if entry_price else None,
                name=name,
            )
        except Exception as exc:
            logger.debug("OutcomeTracker registration failed: %s", exc)

    @staticmethod
    def _hard_risk_check(decision: dict[str, Any]) -> str:
        """Run hard risk constraints on a buy/add decision.

        Checks kill switch, circuit breaker, and preflight. Returns
        empty string if all pass, or a veto reason string if blocked.

        This is the mandatory risk gate — no buy/add can bypass it.
        """
        symbol = decision.get("symbol", "")
        shares = int(decision.get("shares", 0))
        entry_price = decision.get("entry_price")

        # 1. Kill switch
        try:
            from src.trading.kill_switch import KillSwitch

            ks = KillSwitch()
            if ks.is_active():
                return "杀手开关已激活，禁止一切买入"
        except Exception:
            pass

        # 2. Circuit breaker (persistent via Redis)
        try:
            from src.risk.circuit_breaker import CircuitBreaker

            cb = CircuitBreaker()
            if hasattr(cb, "is_halted") and cb.is_halted():
                return "熔断器触发：日亏损或周亏损超限"
            elif hasattr(cb, "check"):
                result = cb.check()
                if result and result.get("halted"):
                    return f"熔断器触发：{result.get('reason', '亏损超限')}"
        except Exception:
            pass

        # 3. Concentration + order size check
        try:
            from src.web.dependencies import get_capital_service, get_portfolio_store

            ps = get_portfolio_store()
            cs = get_capital_service()
            positions = ps.list_positions()
            balance = cs.get_balance()
            # get_balance() returns float (cash), not dict
            total_cash = float(balance) if isinstance(balance, (int, float)) else 0
            # Total assets = cash + sum of position values
            position_value = sum(
                float(p.get("shares", 0)) * float(p.get("cost_price", 0))
                for p in positions
            )
            total_assets = total_cash + position_value

            if total_assets > 0 and entry_price and shares > 0:
                order_value = float(entry_price) * shares
                # Existing position value for this symbol
                existing = sum(
                    float(p.get("market_value", 0))
                    for p in positions
                    if p.get("symbol") == symbol
                )
                new_concentration = (existing + order_value) / total_assets
                if new_concentration > 0.50:
                    return f"单只集中度 {new_concentration:.0%} 超过50%上限"
                # Daily new position cap: 40% of total assets
                # (simplified: just check this single order)
                if order_value / total_assets > 0.40:
                    return f"单笔下单 {order_value / total_assets:.0%} 超过40%日限"
        except Exception:
            pass

        return ""  # All checks passed

    def _check_convergence(self, decision: dict[str, Any]) -> bool:
        """Check if the prediction pipeline agrees with a buy/add decision.

        Returns True (pass) if:
        - Prediction pipeline says bullish/buy with confidence > 0.5
        - No prediction data available (pass through, don't block on missing data)
        Returns False (block) if prediction says bearish/sell.
        """
        symbol = decision.get("symbol", "")
        if not symbol or not self._redis:
            return True

        try:
            raw = self._redis.get(f"prediction:{symbol}")
            if not raw:
                return True  # No prediction data → pass through

            pred = json.loads(raw)
            signal = (pred.get("signal") or "").lower()
            confidence = float(pred.get("confidence", 0))

            if signal in ("buy", "strong_buy") and confidence > 0.5:
                return True
            if signal in ("hold", "watch") and confidence > 0.6:
                return True  # Neutral but confident → allow
            if signal in ("sell", "strong_sell"):
                return False  # Direct contradiction

            # Ambiguous → pass through (don't be overly restrictive)
            return True
        except Exception:
            return True  # Error → pass through

    def _publish_to_redis(self, payload: dict[str, Any]) -> None:
        """Publish a message payload to Redis pub/sub."""
        if not self._redis:
            return
        try:
            self._redis.publish(
                "assistant:messages",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
        except Exception as exc:
            logger.warning("Redis publish failed: %s", exc)
