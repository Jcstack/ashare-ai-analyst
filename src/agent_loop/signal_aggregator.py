"""Signal aggregator — merges multiple signal sources into one ranked pipeline.

Collects signals from recommendation, technical, rotation, black-swan, thesis,
and factor engines, normalizes them into AggregatedSignal, then ranks and
deduplicates for the trading loop's decision pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agent_loop.convergence_engine import ConvergenceEngine
from src.agent_loop.domain_adapter import (
    ConvergenceResult,
    DomainAdapter,
)
from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier
from src.agent_loop.reflexivity_detector import ReflexivityResult
from src.agent_loop.sentiment_cycle import SentimentPhase
from src.data.sector_correlation import CorrelationRegime
from src.quant.multi_timeframe import MtfConfirmation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_URGENCY_WEIGHTS: dict[UrgencyTier, float] = {
    UrgencyTier.CRITICAL: 10.0,
    UrgencyTier.HIGH: 5.0,
    UrgencyTier.NORMAL: 2.0,
    UrgencyTier.DEEP: 1.0,
}

_FRESHNESS_FULL_MINUTES = 15  # full score if signal age < 15 min
_FRESHNESS_DECAY_PER_HOUR = 0.1

# Minimum confidence threshold for recommendation signals.
_REC_CONFIDENCE_THRESHOLD = 0.3


class SignalAggregator:
    """Merge heterogeneous signal sources into a single ranked pipeline.

    Stateless between cycles — the trading loop calls :meth:`clear` at cycle
    start, feeds signals from each source, then calls
    :meth:`rank_and_deduplicate` to obtain the top-N actionable signals.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._dedup_window_hours: float = cfg.get("signal_dedup_window_hours", 1)
        self._max_signals: int = cfg.get("max_signals_per_cycle", 10)
        self._buffer: list[AggregatedSignal] = []

    # ------------------------------------------------------------------
    # Core buffer operations
    # ------------------------------------------------------------------

    def add_signal(self, signal: AggregatedSignal) -> None:
        """Add a signal to the current cycle's buffer."""
        signal.priority_score = self.compute_priority_score(signal)
        self._buffer.append(signal)
        logger.debug(
            "Buffered signal %s: %s %s (priority=%.2f)",
            signal.signal_id[:8],
            signal.direction.value,
            signal.symbol,
            signal.priority_score,
        )

    def clear(self) -> None:
        """Clear the signal buffer for next cycle."""
        self._buffer.clear()

    # ------------------------------------------------------------------
    # Source-specific converters
    # ------------------------------------------------------------------

    def add_from_recommendation(self, rec: dict) -> AggregatedSignal | None:
        """Convert a recommendation dict to *AggregatedSignal*.

        Expected keys: ``symbol``, ``name``, ``score``, ``confidence``,
        ``reasoning``, ``entry_price``, ``target_price``, ``stop_loss``.

        Returns ``None`` if confidence is below threshold.
        """
        confidence = float(rec.get("confidence", 0))
        if confidence < _REC_CONFIDENCE_THRESHOLD:
            return None

        signal = AggregatedSignal(
            symbol=rec["symbol"],
            name=rec.get("name", ""),
            direction=SignalDirection.BUY,
            source="recommendation",
            confidence=confidence,
            urgency=UrgencyTier.NORMAL,
            reason=rec.get("reasoning", ""),
            metadata={
                "score": rec.get("score"),
                "entry_price": rec.get("entry_price"),
                "target_price": rec.get("target_price"),
                "stop_loss": rec.get("stop_loss"),
            },
        )
        self.add_signal(signal)
        return signal

    def add_from_technical(self, signal_dict: dict) -> AggregatedSignal | None:
        """Convert a technical signal dict to *AggregatedSignal*.

        Expected keys: ``symbol``, ``name``, ``signal_type``, ``direction``,
        ``confidence``, ``summary_short``.
        """
        direction = self._parse_direction(signal_dict.get("direction", "hold"))
        confidence = float(signal_dict.get("confidence", 0))

        signal = AggregatedSignal(
            symbol=signal_dict["symbol"],
            name=signal_dict.get("name", ""),
            direction=direction,
            source="technical",
            confidence=confidence,
            urgency=UrgencyTier.NORMAL,
            reason=signal_dict.get("summary_short", ""),
            metadata={"signal_type": signal_dict.get("signal_type")},
        )
        self.add_signal(signal)
        return signal

    def add_from_rotation(self, profile: dict) -> AggregatedSignal | None:
        """Convert a rotation profile to *AggregatedSignal*.

        Expected keys: ``symbol``, ``name``, ``rotation_signal``,
        ``rotation_reason``, ``macro_score``.
        """
        rotation_signal = profile.get("rotation_signal", "hold")
        direction = self._parse_direction(rotation_signal)
        macro_score = float(profile.get("macro_score", 0.5))

        signal = AggregatedSignal(
            symbol=profile["symbol"],
            name=profile.get("name", ""),
            direction=direction,
            source="rotation",
            confidence=macro_score,
            urgency=UrgencyTier.NORMAL,
            reason=profile.get("rotation_reason", ""),
            metadata={"macro_score": macro_score},
        )
        self.add_signal(signal)
        return signal

    def add_from_black_swan(self, alert: dict) -> AggregatedSignal | None:
        """Convert a black-swan alert to *AggregatedSignal* instances.

        Always assigned ``CRITICAL`` urgency.  Creates one signal per
        affected symbol.  Returns the last created signal (or ``None``
        if no symbols are affected).

        Expected keys: ``alert_level``, ``message``, ``affected_symbols``
        (list of ``{"symbol": ..., "name": ...}`` dicts or plain strings).
        """
        affected = alert.get("affected_symbols", [])
        if not affected:
            return None

        last: AggregatedSignal | None = None
        for entry in affected:
            if isinstance(entry, dict):
                symbol = entry.get("symbol", "")
                name = entry.get("name", "")
            else:
                symbol = str(entry)
                name = ""

            signal = AggregatedSignal(
                symbol=symbol,
                name=name,
                direction=SignalDirection.SELL,
                source="black_swan",
                confidence=1.0,
                urgency=UrgencyTier.CRITICAL,
                reason=alert.get("message", "Black swan event detected"),
                metadata={"alert_level": alert.get("alert_level")},
            )
            self.add_signal(signal)
            last = signal

        return last

    def add_from_thesis_invalidation(
        self, symbol: str, name: str, reason: str
    ) -> AggregatedSignal:
        """Generate a SELL signal from thesis invalidation (HIGH urgency)."""
        signal = AggregatedSignal(
            symbol=symbol,
            name=name,
            direction=SignalDirection.SELL,
            source="thesis_invalidation",
            confidence=0.9,
            urgency=UrgencyTier.HIGH,
            reason=reason,
        )
        self.add_signal(signal)
        return signal

    def add_from_stop_loss(
        self, symbol: str, name: str, change_pct: float, stop_loss_pct: float
    ) -> AggregatedSignal:
        """Generate a CRITICAL SELL signal for stop-loss breach — no debate."""
        signal = AggregatedSignal(
            symbol=symbol,
            name=name,
            direction=SignalDirection.SELL,
            source="stop_loss",
            confidence=0.99,
            urgency=UrgencyTier.CRITICAL,
            reason=f"止损触发: 跌幅{change_pct:.1%} 超过止损线{stop_loss_pct:.1%}",
        )
        self.add_signal(signal)
        return signal

    def add_from_reflexivity(
        self, symbol: str, name: str, result: ReflexivityResult
    ) -> AggregatedSignal | None:
        """Convert a :class:`ReflexivityResult` to *AggregatedSignal*.

        Only emits signals when severity >= 0.5.  A "strengthening" loop
        in a bullish direction does not create a standalone signal — instead
        it attaches metadata to existing buffered signals for the same
        symbol (confidence boost via reflexivity confirmation).

        Returns ``None`` if no signal is emitted.
        """
        if result.severity < 0.5:
            logger.debug(
                "Reflexivity severity %.2f < 0.5 for %s, skipping",
                result.severity,
                symbol,
            )
            return None

        # Strengthening + bullish: boost existing signals, don't emit new one
        if result.loop_state == "strengthening" and result.direction == "bullish":
            boosted = 0
            for sig in self._buffer:
                if sig.symbol == symbol:
                    sig.metadata["reflexivity_boost"] = True
                    sig.metadata["reflexivity_loop_state"] = result.loop_state
                    sig.metadata["reflexivity_score"] = result.reflexivity_score
                    boosted += 1
            logger.info(
                "反身性增强确认: %s 循环加强中, 为 %d 个现有信号添加元数据",
                symbol,
                boosted,
            )
            return None

        # Breaking + bearish: SELL, HIGH urgency
        if result.loop_state == "breaking" and result.direction == "bearish":
            direction = SignalDirection.SELL
            urgency = UrgencyTier.HIGH
            reason = (
                f"反身性循环断裂({result.loop_state}), "
                f"反转概率{result.reversal_probability:.0%}, 建议卖出"
            )
        # Exhausting: REDUCE, NORMAL urgency
        elif result.loop_state == "exhausting":
            direction = SignalDirection.REDUCE
            urgency = UrgencyTier.NORMAL
            reason = (
                f"反身性循环衰竭({result.loop_state}), "
                f"反转概率{result.reversal_probability:.0%}, 建议减仓"
            )
        else:
            # Other combinations above threshold — emit with best-effort mapping
            direction = (
                SignalDirection.SELL
                if result.direction == "bearish"
                else SignalDirection.HOLD
            )
            urgency = UrgencyTier.NORMAL
            reason = (
                f"反身性信号: {result.loop_state}, "
                f"方向{result.direction}, "
                f"反转概率{result.reversal_probability:.0%}"
            )

        signal = AggregatedSignal(
            symbol=symbol,
            name=name,
            direction=direction,
            source="reflexivity",
            confidence=result.severity,
            urgency=urgency,
            reason=reason,
            metadata={
                "loop_state": result.loop_state,
                "reflexivity_score": result.reflexivity_score,
                "reversal_probability": result.reversal_probability,
                "direction": result.direction,
            },
        )
        self.add_signal(signal)
        return signal

    def apply_mtf_boost(self, symbol: str, confirmation: MtfConfirmation) -> int:
        """Apply multi-timeframe confidence adjustment to existing signals.

        MTF is a confidence *modifier*, not a standalone signal source.
        Call this **after** other signals for the symbol have been added.

        Returns the number of signals adjusted.
        """
        boost = confirmation.confidence_boost
        if abs(boost) < 0.001:
            logger.debug("MTF boost ~0 for %s, no adjustment needed", symbol)
            return 0

        adjusted = 0
        for sig in self._buffer:
            if sig.symbol != symbol:
                continue
            old_conf = sig.confidence
            sig.confidence = max(0.0, min(1.0, sig.confidence + boost))
            sig.metadata["mtf_boost"] = boost
            sig.metadata["mtf_alignment"] = confirmation.alignment_score
            sig.metadata["mtf_regime"] = confirmation.regime
            sig.metadata["mtf_direction"] = confirmation.confirmed_direction
            # Recompute priority after confidence change
            sig.priority_score = self.compute_priority_score(sig)
            adjusted += 1
            logger.info(
                "MTF调整 %s 信号置信度: %.2f → %.2f (boost=%.2f, 对齐度=%.2f)",
                symbol,
                old_conf,
                sig.confidence,
                boost,
                confirmation.alignment_score,
            )

        if adjusted == 0:
            logger.debug(
                "MTF: 未找到 %s 的现有信号, boost %.2f 未应用",
                symbol,
                boost,
            )

        return adjusted

    def add_from_sector_correlation(
        self,
        regime: CorrelationRegime,
        sector_symbols: dict[str, list[str]],
    ) -> AggregatedSignal | None:
        """Convert a :class:`CorrelationRegime` to *AggregatedSignal* instances.

        If ``crisis_signal`` is True, emits SELL signals for **all** symbols
        in affected sectors with CRITICAL urgency.  For individual breaks
        of type "divergence" or "reversal", emits signals for the affected
        sector's symbols.

        ``sector_symbols`` maps sector name → list of stock codes (e.g.
        ``{"半导体": ["688981", "603501"]}``) with names stored in metadata.

        Returns the last emitted signal, or ``None``.
        """
        if not regime.breaks and not regime.crisis_signal:
            return None

        last: AggregatedSignal | None = None

        # Crisis: all affected sectors get SELL signals
        if regime.crisis_signal:
            affected_sectors: set[str] = set()
            for brk in regime.breaks:
                affected_sectors.add(brk.sector_a)
                affected_sectors.add(brk.sector_b)
            # If no breaks but crisis, use all sectors in the mapping
            if not affected_sectors:
                affected_sectors = set(sector_symbols.keys())

            for sector in affected_sectors:
                symbols = sector_symbols.get(sector, [])
                for sym in symbols:
                    signal = AggregatedSignal(
                        symbol=sym,
                        name="",
                        direction=SignalDirection.SELL,
                        source="sector_correlation",
                        confidence=1.0,
                        urgency=UrgencyTier.CRITICAL,
                        reason=(
                            f"全市场相关性危机信号: "
                            f"平均相关性{regime.avg_cross_correlation:.2f}趋向1.0, "
                            f"流动性风险极高"
                        ),
                        metadata={
                            "regime": regime.regime,
                            "crisis_signal": True,
                            "sector": sector,
                        },
                    )
                    self.add_signal(signal)
                    last = signal

            logger.warning(
                "板块相关性危机: 为 %d 个板块的持仓发出卖出信号",
                len(affected_sectors),
            )
            return last

        # Individual breaks
        for brk in regime.breaks:
            if brk.break_type not in ("divergence", "reversal"):
                continue

            confidence = min(1.0, brk.severity)

            # Emit for both sectors in the break
            for sector in (brk.sector_a, brk.sector_b):
                symbols = sector_symbols.get(sector, [])
                for sym in symbols:
                    direction = (
                        SignalDirection.SELL
                        if brk.break_type == "reversal"
                        else SignalDirection.REDUCE
                    )
                    urgency = (
                        UrgencyTier.HIGH
                        if brk.break_type == "reversal"
                        else UrgencyTier.NORMAL
                    )

                    signal = AggregatedSignal(
                        symbol=sym,
                        name="",
                        direction=direction,
                        source="sector_correlation",
                        confidence=confidence,
                        urgency=urgency,
                        reason=(
                            f"板块相关性{brk.break_type}: "
                            f"{brk.sector_a}与{brk.sector_b}"
                            f"(当前{brk.current_correlation:.2f} "
                            f"vs 历史{brk.historical_correlation:.2f})"
                        ),
                        metadata={
                            "break_type": brk.break_type,
                            "sector_a": brk.sector_a,
                            "sector_b": brk.sector_b,
                            "deviation": brk.deviation,
                            "leading_sector": brk.leading_sector,
                        },
                    )
                    self.add_signal(signal)
                    last = signal

        return last

    def add_from_leader(self, leader_score: Any) -> AggregatedSignal | None:
        """Convert a :class:`LeaderScore` to *AggregatedSignal*.

        Only emits BUY signals for stocks identified as leaders
        (``is_leader=True``).  Non-leaders are ignored.

        Returns the created signal, or ``None``.
        """
        if not getattr(leader_score, "is_leader", False):
            return None

        # Map confidence_level to numeric confidence
        level = getattr(leader_score, "confidence_level", "low")
        conf_map = {"high": 0.85, "medium": 0.70, "low": 0.55}
        confidence = conf_map.get(level, 0.55)

        signal = AggregatedSignal(
            symbol=leader_score.symbol,
            name=leader_score.name,
            direction=SignalDirection.BUY,
            source="leader_detection",
            confidence=confidence,
            urgency=UrgencyTier.HIGH,
            reason=getattr(leader_score, "reason", "龙头股识别"),
            metadata={
                "total_score": getattr(leader_score, "total_score", 0),
                "scores": getattr(leader_score, "scores", {}),
                "sector": getattr(leader_score, "sector", ""),
            },
        )
        self.add_signal(signal)
        logger.info(
            "龙头信号: %s (%s) score=%.0f conf=%.2f",
            leader_score.symbol,
            leader_score.name,
            getattr(leader_score, "total_score", 0),
            confidence,
        )
        return signal

    def add_from_sentiment_phase(
        self,
        phase: SentimentPhase,
        portfolio_symbols: list[tuple[str, str]],
    ) -> AggregatedSignal | None:
        """Convert a :class:`SentimentPhase` to *AggregatedSignal* instances.

        ``portfolio_symbols`` is a list of ``(symbol, name)`` tuples for
        current portfolio holdings.

        * 退潮 (ebb) + confidence >= 0.6 → REDUCE for all holdings, HIGH urgency
        * 高潮 (climax) + confidence >= 0.7 → metadata flag only (no new signals)
        * 冰点 (freezing) + confidence >= 0.5 → BUY watchlist signal, DEEP urgency

        Returns the last emitted signal, or ``None``.
        """
        last: AggregatedSignal | None = None

        # 退潮 — reduce all positions
        if phase.phase == "ebb" and phase.confidence >= 0.6:
            for sym, sym_name in portfolio_symbols:
                signal = AggregatedSignal(
                    symbol=sym,
                    name=sym_name,
                    direction=SignalDirection.REDUCE,
                    source="sentiment_cycle",
                    confidence=phase.confidence,
                    urgency=UrgencyTier.HIGH,
                    reason=(
                        f"情绪周期进入退潮期(置信度{phase.confidence:.0%}), "
                        f"亏钱效应增加, 建议降低仓位"
                    ),
                    metadata={
                        "sentiment_phase": phase.phase,
                        "phase_cn": phase.phase_cn,
                        "max_position_pct": phase.max_position_pct,
                        "stop_loss_pct": phase.stop_loss_pct,
                    },
                )
                self.add_signal(signal)
                last = signal
            logger.info(
                "情绪退潮: 为 %d 个持仓发出减仓信号 (置信度 %.2f)",
                len(portfolio_symbols),
                phase.confidence,
            )
            return last

        # 高潮 — don't create buy signals, add climax warning to existing
        if phase.phase == "climax" and phase.confidence >= 0.7:
            flagged = 0
            for sig in self._buffer:
                if sig.direction == SignalDirection.BUY:
                    sig.metadata["climax_warning"] = True
                    sig.metadata["sentiment_phase"] = phase.phase
                    sig.metadata["phase_cn"] = phase.phase_cn
                    sig.metadata["sentiment_confidence"] = phase.confidence
                    flagged += 1
            logger.info(
                "情绪高潮警告: 为 %d 个买入信号添加高潮标记 (置信度 %.2f)",
                flagged,
                phase.confidence,
            )
            return None

        # 冰点 — potential opportunity, deep urgency watchlist signals
        if phase.phase == "freezing" and phase.confidence >= 0.5:
            for sym, sym_name in portfolio_symbols:
                signal = AggregatedSignal(
                    symbol=sym,
                    name=sym_name,
                    direction=SignalDirection.BUY,
                    source="sentiment_cycle",
                    confidence=phase.confidence,
                    urgency=UrgencyTier.DEEP,
                    reason=(
                        f"情绪周期处于冰点(置信度{phase.confidence:.0%}), "
                        f"超跌反弹机会, 可小仓位关注"
                    ),
                    metadata={
                        "sentiment_phase": phase.phase,
                        "phase_cn": phase.phase_cn,
                        "max_position_pct": phase.max_position_pct,
                        "stop_loss_pct": phase.stop_loss_pct,
                    },
                )
                self.add_signal(signal)
                last = signal
            logger.info(
                "情绪冰点机会: 为 %d 个标的发出观察信号 (置信度 %.2f)",
                len(portfolio_symbols),
                phase.confidence,
            )
            return last

        logger.debug(
            "情绪周期 %s (置信度 %.2f) 未触发信号阈值",
            phase.phase_cn,
            phase.confidence,
        )
        return None

    # ------------------------------------------------------------------
    # v54: Impact chain signals (intelligence → causal chain → trade)
    # ------------------------------------------------------------------

    def add_from_impact_chain(self, chain_signals: list[dict]) -> int:
        """Convert EventImpactEngine output into AggregatedSignals.

        This is THE bridge between intelligence (events/causal chains)
        and trading (signals/decisions). Without this, the intelligence
        pipeline's output never reaches the trading loop.

        Expected dict keys: symbol, direction, confidence, source,
        signal_type, metadata (with optional source_weight, impact, event).

        Returns:
            Number of signals added.
        """
        count = 0
        for sig in chain_signals:
            symbol = sig.get("symbol", "")
            if not symbol:
                continue

            direction_str = str(sig.get("direction", "hold")).lower()
            direction_map = {
                "bullish": SignalDirection.BUY,
                "buy": SignalDirection.BUY,
                "long": SignalDirection.BUY,
                "bearish": SignalDirection.SELL,
                "sell": SignalDirection.SELL,
                "short": SignalDirection.SELL,
                "reduce": SignalDirection.REDUCE,
                "watch": SignalDirection.WATCH,
            }
            direction = direction_map.get(direction_str, SignalDirection.WATCH)

            confidence = float(sig.get("confidence", 0.5))
            if confidence < 0.3:
                continue

            # Apply source weight from upstream (C4)
            meta = sig.get("metadata", {})
            source_weight = float(meta.get("source_weight", 1.0))
            weighted_confidence = min(1.0, confidence * min(source_weight, 2.0))

            urgency = (
                UrgencyTier.HIGH if weighted_confidence > 0.7 else UrgencyTier.NORMAL
            )

            impact_desc = meta.get("impact", "事件影响链信号")
            event_desc = meta.get("event", "")
            reason = f"{event_desc} → {impact_desc}" if event_desc else impact_desc

            signal = AggregatedSignal(
                symbol=symbol,
                name=sig.get("name", ""),
                direction=direction,
                source=f"impact_chain:{sig.get('source', 'event')}",
                confidence=weighted_confidence,
                urgency=urgency,
                reason=reason[:100],
                timestamp=datetime.now(UTC),
                metadata={
                    "signal_type": sig.get("signal_type", "causal_chain"),
                    "chain_id": meta.get("chain_id", ""),
                    "impact_order": meta.get("impact_order", 0),
                    "source_weight": source_weight,
                    "raw_confidence": confidence,
                },
            )
            self.add_signal(signal)
            count += 1

        if count:
            logger.info(
                "Impact chain → %d signals added (from %d candidates)",
                count,
                len(chain_signals),
            )
        return count

    # ------------------------------------------------------------------
    # Ranking & deduplication
    # ------------------------------------------------------------------

    def rank_and_deduplicate(self) -> list[AggregatedSignal]:
        """Rank buffered signals and deduplicate.

        Deduplication rule: same ``symbol`` + same ``direction`` within
        *dedup_window_hours* are merged — only the signal with the highest
        confidence is kept.

        Returns the top *max_signals_per_cycle* signals sorted descending
        by ``priority_score``.
        """
        # Recompute priority scores (timestamps may have shifted).
        for sig in self._buffer:
            sig.priority_score = self.compute_priority_score(sig)

        # Deduplicate: keep highest-confidence per (symbol, direction) within
        # the dedup window.  Track unique source domains per merged signal so
        # that source_count reflects convergence across independent domains.
        window = timedelta(hours=self._dedup_window_hours)
        deduped: dict[tuple[str, SignalDirection], AggregatedSignal] = {}
        source_sets: dict[tuple[str, SignalDirection], set[str]] = {}

        # Sort buffer by confidence descending so the first seen wins.
        for sig in sorted(self._buffer, key=lambda s: s.confidence, reverse=True):
            key = (sig.symbol, sig.direction)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = sig
                source_sets[key] = {sig.source}
            else:
                # Merge only if within the dedup window.
                delta = abs(sig.timestamp - existing.timestamp)
                if delta <= window:
                    # Already kept the higher-confidence one (sorted desc).
                    # Track the additional source domain for convergence.
                    source_sets[key].add(sig.source)
                    continue
                # Outside window — treat as distinct; use a unique key.
                alt_key = (f"{sig.symbol}:{sig.signal_id[:8]}", sig.direction)
                deduped[alt_key] = sig  # type: ignore[index]
                source_sets[alt_key] = {sig.source}  # type: ignore[index]

        # Populate source_count from tracked source domains
        for key, sig in deduped.items():
            sig.source_count = len(source_sets[key])

        ranked = sorted(deduped.values(), key=lambda s: s.priority_score, reverse=True)
        result = ranked[: self._max_signals]

        logger.info(
            "Ranked %d signals → %d after dedup → returning top %d",
            len(self._buffer),
            len(ranked),
            len(result),
        )
        return result

    # ------------------------------------------------------------------
    # Priority scoring
    # ------------------------------------------------------------------

    @staticmethod
    def compute_priority_score(signal: AggregatedSignal) -> float:
        """Compute priority score for ranking.

        ``priority_score = urgency_weight * confidence * freshness_decay``

        * Urgency weights: CRITICAL=10, HIGH=5, NORMAL=2, DEEP=1
        * Freshness: 1.0 if signal is < 15 min old, decays 0.1 per hour
          thereafter (floored at 0.1).
        """
        urgency_weight = _URGENCY_WEIGHTS.get(signal.urgency, 2.0)
        confidence = max(0.0, min(1.0, signal.confidence))

        age = datetime.now(UTC) - signal.timestamp
        age_minutes = age.total_seconds() / 60.0

        if age_minutes <= _FRESHNESS_FULL_MINUTES:
            freshness = 1.0
        else:
            hours_past = (age_minutes - _FRESHNESS_FULL_MINUTES) / 60.0
            freshness = max(0.1, 1.0 - _FRESHNESS_DECAY_PER_HOUR * hours_past)

        return urgency_weight * confidence * freshness

    # ------------------------------------------------------------------
    # Adapter-based aggregation (v50.0)
    # ------------------------------------------------------------------

    def aggregate_via_adapters(
        self,
        symbols: list[str],
        adapters: list[DomainAdapter],
        portfolio_context: dict | None = None,
    ) -> list[ConvergenceResult]:
        """Adapter-based aggregation with convergence invariant.

        Collects signals from all provided DomainAdapters, runs convergence
        analysis, and returns only actionable results: BUY signals that pass
        the convergence check (2+ independence groups), plus all SELL signals
        (which bypass convergence for risk management).

        This is a parallel path to the existing :meth:`add_signal` /
        :meth:`rank_and_deduplicate` workflow — it does not modify the
        internal buffer and can be adopted incrementally.
        """
        from src.agent_loop.domain_adapter import SignalEvidence

        all_signals: list[SignalEvidence] = []
        for adapter in adapters:
            try:
                signals = adapter.collect_signals(symbols, portfolio_context)
                all_signals.extend(signals)
            except Exception:
                logger.exception(
                    "Adapter %s failed during collect_signals",
                    getattr(adapter, "domain", "unknown"),
                )

        engine = ConvergenceEngine()
        results = engine.analyze(all_signals)

        # Only return converged results for BUY; SELL always passes
        return engine.filter_actionable(results)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_direction(raw: str) -> SignalDirection:
        """Best-effort parse of a direction string to :class:`SignalDirection`."""
        mapping: dict[str, SignalDirection] = {
            "buy": SignalDirection.BUY,
            "bullish": SignalDirection.BUY,
            "long": SignalDirection.BUY,
            "sell": SignalDirection.SELL,
            "bearish": SignalDirection.SELL,
            "short": SignalDirection.SELL,
            "hold": SignalDirection.HOLD,
            "neutral": SignalDirection.HOLD,
            "reduce": SignalDirection.REDUCE,
            "add": SignalDirection.ADD,
        }
        return mapping.get(raw.lower().strip(), SignalDirection.HOLD)
