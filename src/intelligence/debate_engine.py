"""Bull/Bear Debate Engine — adversarial analysis for investment decisions.

Per PRD v34.0 FR-AD001: Every investment decision passes through multi-perspective
debate before recommendation.

Flow:
  Trigger -> Bull Researcher (collect bullish arguments)
          -> Bear Researcher (collect bearish arguments)
          -> Arbiter (weigh evidence, decide)
          -> Risk Agent veto check
          -> Munger Checklist
          -> Final decision
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DebateArgument:
    """A single argument in the debate."""

    perspective: str  # "bull" | "bear"
    dimension: (
        str  # "technical" | "fundamental" | "macro" | "capital_flow" | "sentiment"
    )
    claim: str
    evidence: str
    strength: str  # "strong" | "moderate" | "weak"
    confidence: float  # 0-1

    def to_dict(self) -> dict[str, Any]:
        return {
            "perspective": self.perspective,
            "dimension": self.dimension,
            "claim": self.claim,
            "evidence": self.evidence,
            "strength": self.strength,
            "confidence": self.confidence,
        }


@dataclass
class DebateVerdict:
    """The arbiter's final verdict after weighing arguments."""

    action: str  # "buy" | "sell" | "hold" | "reduce" | "watch"
    conviction: str  # "high" | "medium" | "low"
    win_probability: float  # estimated probability of profit
    risk_reward_ratio: float  # expected gain / expected loss
    reasoning: str
    key_risk: str
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "conviction": self.conviction,
            "win_probability": self.win_probability,
            "risk_reward_ratio": self.risk_reward_ratio,
            "reasoning": self.reasoning,
            "key_risk": self.key_risk,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }


@dataclass
class DebateRecord:
    """Complete record of a bull/bear debate."""

    debate_id: str
    symbol: str
    name: str
    timestamp: datetime
    trigger: str  # what triggered this debate
    bull_arguments: list[DebateArgument] = field(default_factory=list)
    bear_arguments: list[DebateArgument] = field(default_factory=list)
    verdict: DebateVerdict | None = None
    risk_veto: bool = False
    risk_veto_reason: str = ""
    checklist_passed: bool = True
    checklist_warnings: list[str] = field(default_factory=list)
    final_action: str = "hold"  # may differ from verdict if vetoed

    @property
    def bull_score(self) -> float:
        if not self.bull_arguments:
            return 0.0
        strength_map = {"strong": 1.0, "moderate": 0.6, "weak": 0.3}
        total = sum(
            strength_map.get(a.strength, 0.5) * a.confidence
            for a in self.bull_arguments
        )
        return total / len(self.bull_arguments)

    @property
    def bear_score(self) -> float:
        if not self.bear_arguments:
            return 0.0
        strength_map = {"strong": 1.0, "moderate": 0.6, "weak": 0.3}
        total = sum(
            strength_map.get(a.strength, 0.5) * a.confidence
            for a in self.bear_arguments
        )
        return total / len(self.bear_arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "symbol": self.symbol,
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "trigger": self.trigger,
            "bull_arguments": [a.to_dict() for a in self.bull_arguments],
            "bear_arguments": [a.to_dict() for a in self.bear_arguments],
            "bull_score": round(self.bull_score, 3),
            "bear_score": round(self.bear_score, 3),
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "risk_veto": self.risk_veto,
            "risk_veto_reason": self.risk_veto_reason,
            "checklist_passed": self.checklist_passed,
            "checklist_warnings": self.checklist_warnings,
            "final_action": self.final_action,
        }


class DebateEngine:
    """Orchestrates bull/bear debates for investment decisions.

    Phase 1 (current): Rule-based argument collection from data.
    Phase 2 (future): LLM-powered argument generation with tool access.

    Usage:
        engine = DebateEngine()
        record = engine.run_debate(
            symbol="002155", name="湖南黄金",
            trigger="宏观轮动信号",
            market_data={...},
        )
        if record.final_action in ("buy", "add"):
            # proceed with recommendation
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._min_arguments = cfg.get("min_arguments_per_side", 2)
        self._veto_threshold = cfg.get("risk_veto_threshold", 0.7)
        logger.info("DebateEngine initialized")

    def collect_bull_arguments(
        self, market_data: dict[str, Any]
    ) -> list[DebateArgument]:
        """Collect bullish arguments from available market data.

        P1 audit fix: When ``_debate_independence_rules`` is present in
        market_data, bull arguments are filtered to exclude the signal's
        own domain, forcing independent corroboration.
        """
        args: list[DebateArgument] = []

        # Technical bullish signals
        rsi = market_data.get("rsi")
        if rsi is not None and rsi < 30:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="technical",
                    claim="RSI超卖反弹信号",
                    evidence=f"RSI={rsi:.1f}，处于超卖区间(<30)，反弹概率高",
                    strength="strong" if rsi < 20 else "moderate",
                    confidence=0.7,
                )
            )

        macd_cross = market_data.get("macd_golden_cross")
        if macd_cross:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="technical",
                    claim="MACD金叉确认",
                    evidence="MACD线上穿信号线，短期动量转多",
                    strength="moderate",
                    confidence=0.6,
                )
            )

        # Volume confirmation
        volume_ratio = market_data.get("volume_ratio")
        if volume_ratio is not None and volume_ratio > 1.5:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="technical",
                    claim="放量突破",
                    evidence=f"成交量为均量的{volume_ratio:.1f}倍，资金积极入场",
                    strength="moderate",
                    confidence=0.6,
                )
            )

        # Macro favorable
        macro_score = market_data.get("macro_score")
        if macro_score is not None and macro_score > 0.2:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="macro",
                    claim="宏观环境有利",
                    evidence=f"宏观综合评分{macro_score:.2f}，当前环境对该板块有利",
                    strength="strong" if macro_score > 0.5 else "moderate",
                    confidence=min(0.8, 0.5 + macro_score),
                )
            )

        # Capital inflow
        capital_flow = market_data.get("capital_net_inflow")
        if capital_flow is not None and capital_flow > 0:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="capital_flow",
                    claim="资金净流入",
                    evidence=f"近期资金净流入{capital_flow:.0f}万元，主力资金看多",
                    strength="moderate" if capital_flow > 5000 else "weak",
                    confidence=0.5,
                )
            )

        # Price trend (available in most conditions, not just extremes)
        price_chg = market_data.get("price_change_pct")
        if price_chg is not None and price_chg > 1.0:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="technical",
                    claim="股价上涨趋势",
                    evidence=f"当日涨幅{price_chg:.2f}%，短期动量偏多",
                    strength="strong"
                    if price_chg > 5.0
                    else "moderate"
                    if price_chg > 2.0
                    else "weak",
                    confidence=min(0.7, 0.4 + price_chg / 10),
                )
            )

        # RSI in healthy bull zone (not extreme, but trending up)
        if rsi is not None and 40 < rsi < 60:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="technical",
                    claim="RSI处于中性区间",
                    evidence=f"RSI={rsi:.1f}，既非超买也非超卖，存在上行空间",
                    strength="weak",
                    confidence=0.4,
                )
            )

        # Volume near average (market actively traded)
        if volume_ratio is not None and 0.8 < volume_ratio <= 1.5:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="technical",
                    claim="成交量正常活跃",
                    evidence=f"量比{volume_ratio:.2f}，交投活跃度正常",
                    strength="weak",
                    confidence=0.35,
                )
            )

        # Positive sentiment
        sentiment = market_data.get("sentiment_score")
        if sentiment is not None and sentiment > 0.3:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="sentiment",
                    claim="市场情绪偏多",
                    evidence=f"舆情评分{sentiment:.2f}，市场情绪偏正面",
                    strength="moderate" if sentiment > 0.5 else "weak",
                    confidence=min(0.7, 0.4 + sentiment),
                )
            )

        # Northbound inflow — DEPRECATED since Aug 2024, data no longer disclosed.
        # Removed from bull argument collection to avoid stale/zero data influence.

        # Sentiment cycle context (P1 audit: cross-domain evidence)
        sentiment_phase = market_data.get("sentiment_phase")
        if sentiment_phase in ("ignition", "acceleration"):
            phase_cn = market_data.get("sentiment_phase_cn", sentiment_phase)
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="sentiment",
                    claim=f"情绪周期处于{phase_cn}阶段",
                    evidence=f"市场情绪{phase_cn}，赚钱效应扩散，"
                    f"置信度{market_data.get('sentiment_confidence', 0):.0%}",
                    strength="moderate",
                    confidence=market_data.get("sentiment_confidence", 0.5),
                )
            )

        # P1 audit fix: filter out arguments from the same domain as the
        # triggering signal to force independent corroboration
        # v54 C6: Impact chain evidence as bull arguments
        for chain in market_data.get("impact_chain_signals", []):
            direction = str(chain.get("direction", "")).lower()
            if direction not in ("bullish", "buy", "long", "positive"):
                continue
            conf = float(chain.get("confidence", 0.5))
            meta = chain.get("metadata", {})
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="intelligence",
                    claim=f"事件影响链利多: {meta.get('impact', '')[:30]}",
                    evidence=(
                        f"事件: {meta.get('event', '')[:50]} → "
                        f"{meta.get('impact', '')} "
                        f"(置信度{conf:.0%})"
                    ),
                    strength="strong" if conf > 0.7 else "moderate",
                    confidence=conf,
                )
            )

        rules = market_data.get("_debate_independence_rules")
        if rules:
            excluded = rules.get("bull_excluded_domain", "")
            if excluded:
                before_count = len(args)
                args = [a for a in args if a.dimension != excluded]
                if before_count > len(args):
                    logger.debug(
                        "Bull debate: excluded %d args from domain '%s' "
                        "(independent evidence rule)",
                        before_count - len(args),
                        excluded,
                    )

        return args

    def collect_bear_arguments(
        self, market_data: dict[str, Any]
    ) -> list[DebateArgument]:
        """Collect bearish arguments from available market data.

        P1 audit fix: Bear arguments prioritize market microstructure and
        macro environment data.  When ``_debate_independence_rules`` is
        present, arguments are sorted so microstructure/macro evidence
        appears first and carries more weight.
        """
        args: list[DebateArgument] = []

        # Technical bearish signals (microstructure)
        rsi = market_data.get("rsi")
        if rsi is not None and rsi > 70:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="technical",
                    claim="RSI超买回调风险",
                    evidence=f"RSI={rsi:.1f}，处于超买区间(>70)，回调概率高",
                    strength="strong" if rsi > 80 else "moderate",
                    confidence=0.7,
                )
            )

        macd_cross = market_data.get("macd_death_cross")
        if macd_cross:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="technical",
                    claim="MACD死叉确认",
                    evidence="MACD线下穿信号线，短期动量转空",
                    strength="moderate",
                    confidence=0.6,
                )
            )

        # Volume divergence (microstructure)
        price_up = market_data.get("price_change_pct", 0) > 0
        volume_ratio = market_data.get("volume_ratio")
        if price_up and volume_ratio is not None and volume_ratio < 0.7:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="technical",
                    claim="量价背离",
                    evidence=f"价格上涨但成交量仅为均量的{volume_ratio:.1f}倍，上涨缺乏资金支撑",
                    strength="moderate",
                    confidence=0.6,
                )
            )

        # Macro unfavorable
        macro_score = market_data.get("macro_score")
        if macro_score is not None and macro_score < -0.2:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="macro",
                    claim="宏观环境不利",
                    evidence=f"宏观综合评分{macro_score:.2f}，当前环境对该板块不利",
                    strength="strong" if macro_score < -0.5 else "moderate",
                    confidence=min(0.8, 0.5 + abs(macro_score)),
                )
            )

        # Price declining (available in most conditions)
        price_chg = market_data.get("price_change_pct")
        if price_chg is not None and price_chg < -1.0:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="technical",
                    claim="股价下跌趋势",
                    evidence=f"当日跌幅{abs(price_chg):.2f}%，短期动量偏空",
                    strength="strong"
                    if price_chg < -5.0
                    else "moderate"
                    if price_chg < -2.0
                    else "weak",
                    confidence=min(0.7, 0.4 + abs(price_chg) / 10),
                )
            )

        # Capital outflow (macro/flow) — lower threshold for bear
        capital_flow = market_data.get("capital_net_inflow")
        if capital_flow is not None and capital_flow < 0:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="capital_flow",
                    claim="资金净流出",
                    evidence=f"近期资金净流出{abs(capital_flow):.0f}万元，主力资金撤离",
                    strength="moderate",
                    confidence=0.6,
                )
            )

        # Negative sentiment
        sentiment = market_data.get("sentiment_score")
        if sentiment is not None and sentiment < -0.3:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="sentiment",
                    claim="市场情绪偏空",
                    evidence=f"舆情评分{sentiment:.2f}，市场情绪偏负面",
                    strength="moderate" if sentiment < -0.5 else "weak",
                    confidence=min(0.7, 0.4 + abs(sentiment)),
                )
            )

        # High recent gain (chase risk — microstructure)
        recent_gain = market_data.get("recent_5d_gain_pct")
        if recent_gain is not None and recent_gain > 10:
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="technical",
                    claim="短期涨幅过大",
                    evidence=f"近5日涨幅{recent_gain:.1f}%，追高风险大，回调概率增加",
                    strength="strong" if recent_gain > 20 else "moderate",
                    confidence=0.7,
                )
            )

        # T+1 overnight risk (A-share macro constraint)
        if market_data.get("t_plus_1_risk"):
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="macro",
                    claim="T+1隔夜风险",
                    evidence="A股T+1规则下，买入后必须承受至少1个隔夜风险",
                    strength="weak",
                    confidence=0.5,
                )
            )

        # P1 audit fix: sentiment cycle deterioration as bear evidence
        sentiment_phase = market_data.get("sentiment_phase")
        if sentiment_phase in ("climax", "ebb"):
            phase_cn = market_data.get("sentiment_phase_cn", sentiment_phase)
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="macro",
                    claim=f"情绪周期处于{phase_cn}阶段",
                    evidence=f"市场情绪{phase_cn}，亏钱效应增加，"
                    f"置信度{market_data.get('sentiment_confidence', 0):.0%}",
                    strength="strong" if sentiment_phase == "ebb" else "moderate",
                    confidence=market_data.get("sentiment_confidence", 0.5),
                )
            )

        # v54 C6: Impact chain evidence as bear arguments
        for chain in market_data.get("impact_chain_signals", []):
            direction = str(chain.get("direction", "")).lower()
            if direction not in ("bearish", "sell", "short", "negative"):
                continue
            conf = float(chain.get("confidence", 0.5))
            meta = chain.get("metadata", {})
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="intelligence",
                    claim=f"事件影响链利空: {meta.get('impact', '')[:30]}",
                    evidence=(
                        f"事件: {meta.get('event', '')[:50]} → "
                        f"{meta.get('impact', '')} "
                        f"(置信度{conf:.0%})"
                    ),
                    strength="strong" if conf > 0.7 else "moderate",
                    confidence=conf,
                )
            )

        # P1 audit fix: when independence rules are active, prioritize
        # microstructure and macro arguments (sort them first so arbiter
        # gives them more attention in reasoning)
        rules = market_data.get("_debate_independence_rules")
        if rules:
            priority_dims = set(rules.get("bear_required_domains", []))
            if priority_dims:
                priority_args = [a for a in args if a.dimension in priority_dims]
                other_args = [a for a in args if a.dimension not in priority_dims]
                args = priority_args + other_args

        return args

    def arbiter_verdict(
        self,
        bull_args: list[DebateArgument],
        bear_args: list[DebateArgument],
        market_data: dict[str, Any],
    ) -> DebateVerdict:
        """Arbiter weighs bull vs bear arguments and renders verdict.

        Uses a weighted scoring system based on argument strength and confidence.
        """
        strength_map = {"strong": 1.0, "moderate": 0.6, "weak": 0.3}

        bull_total = (
            sum(strength_map.get(a.strength, 0.5) * a.confidence for a in bull_args)
            if bull_args
            else 0.0
        )

        bear_total = (
            sum(strength_map.get(a.strength, 0.5) * a.confidence for a in bear_args)
            if bear_args
            else 0.0
        )

        total = bull_total + bear_total
        if total == 0:
            return DebateVerdict(
                action="hold",
                conviction="low",
                win_probability=0.5,
                risk_reward_ratio=1.0,
                reasoning="多空论据均不足，建议观望",
                key_risk="信息不足",
            )

        bull_ratio = bull_total / total
        bear_ratio = bear_total / total
        net_score = bull_ratio - bear_ratio  # [-1, +1]

        # Determine action
        if net_score > 0.3:
            action = "buy"
            conviction = "high" if net_score > 0.5 else "medium"
        elif net_score > 0.1:
            action = "watch"
            conviction = "low"
        elif net_score > -0.1:
            action = "hold"
            conviction = "low"
        elif net_score > -0.3:
            action = "reduce"
            conviction = "medium"
        else:
            action = "sell"
            conviction = "high" if net_score < -0.5 else "medium"

        # Win probability estimate
        win_prob = max(0.1, min(0.9, 0.5 + net_score * 0.4))

        # Risk/reward ratio
        avg_bull_strength = bull_total / len(bull_args) if bull_args else 0
        avg_bear_strength = bear_total / len(bear_args) if bear_args else 0
        rr_ratio = (
            avg_bull_strength / avg_bear_strength if avg_bear_strength > 0 else 2.0
        )

        # Build reasoning
        reasoning_parts = []
        if bull_args:
            reasoning_parts.append(
                f"做多论据{len(bull_args)}条(评分{bull_total:.2f}): "
                + ", ".join(a.claim for a in bull_args[:3])
            )
        if bear_args:
            reasoning_parts.append(
                f"做空论据{len(bear_args)}条(评分{bear_total:.2f}): "
                + ", ".join(a.claim for a in bear_args[:3])
            )

        # Key risk = strongest bear argument
        key_risk = (
            max(bear_args, key=lambda a: a.confidence).claim
            if bear_args
            else "暂无明显风险"
        )

        # Stop loss / take profit for actionable verdicts
        stop_loss = None
        take_profit = None
        if action in ("buy", "watch"):
            stop_loss = market_data.get("stop_loss_pct", -3.0)
            take_profit = market_data.get("take_profit_pct", 5.0)

        return DebateVerdict(
            action=action,
            conviction=conviction,
            win_probability=round(win_prob, 2),
            risk_reward_ratio=round(rr_ratio, 2),
            reasoning="; ".join(reasoning_parts),
            key_risk=key_risk,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
        )

    def run_debate(
        self,
        symbol: str,
        name: str = "",
        trigger: str = "",
        market_data: dict[str, Any] | None = None,
        *,
        checklist_result: dict[str, Any] | None = None,
    ) -> DebateRecord:
        """Run a complete bull/bear debate for a stock.

        Args:
            symbol: Stock code.
            name: Stock name.
            trigger: What triggered this debate.
            market_data: Dict of market indicators for argument collection.
            checklist_result: Optional pre-computed Munger checklist result.

        Returns:
            Complete DebateRecord with arguments, verdict, and final action.
        """
        data = market_data or {}

        # Auto-inject independence rules: bull and bear must cite
        # different domains from the trigger signal's domain.
        # This prevents mirror-image technical arguments.
        if "_debate_independence_rules" not in data:
            trigger_lower = (trigger or "").lower()
            if any(
                kw in trigger_lower
                for kw in ("rsi", "macd", "breakout", "technical", "pattern")
            ):
                trigger_domain = "technical"
            elif any(kw in trigger_lower for kw in ("fund_flow", "capital", "north")):
                trigger_domain = "capital_flow"
            elif any(
                kw in trigger_lower for kw in ("news", "policy", "macro", "event")
            ):
                trigger_domain = "macro"
            else:
                trigger_domain = ""

            if trigger_domain:
                data["_debate_independence_rules"] = {
                    "bull_excluded_domain": trigger_domain,
                    "bear_required_domains": [
                        d
                        for d in ("macro", "capital_flow", "sentiment")
                        if d != trigger_domain
                    ],
                }

        # Collect arguments
        bull_args = self.collect_bull_arguments(data)
        bear_args = self.collect_bear_arguments(data)

        # Render verdict
        verdict = self.arbiter_verdict(bull_args, bear_args, data)

        # Risk veto check
        risk_veto = False
        risk_veto_reason = ""
        bear_strong_count = sum(
            1 for a in bear_args if a.strength == "strong" and a.confidence >= 0.7
        )
        if bear_strong_count >= 2 and verdict.action in ("buy", "watch"):
            risk_veto = True
            risk_veto_reason = (
                f"存在{bear_strong_count}个强力做空论据(置信度>=0.7)，风控否决买入建议"
            )

        # Integrate Munger checklist
        checklist_passed = True
        checklist_warnings: list[str] = []
        if checklist_result:
            checklist_passed = checklist_result.get("overall_passed", True)
            checklist_warnings = [
                c["finding"]
                for c in checklist_result.get("checks", [])
                if c.get("severity") in ("warn", "block")
            ]
            if not checklist_passed and verdict.action in ("buy", "watch"):
                risk_veto = True
                risk_veto_reason = (
                    risk_veto_reason + "; " if risk_veto_reason else ""
                ) + "芒格检查清单未通过"

        # Final action (may be overridden by veto)
        if risk_veto:
            final_action = "hold" if verdict.action == "buy" else verdict.action
        else:
            final_action = verdict.action

        record = DebateRecord(
            debate_id=str(uuid.uuid4()),
            symbol=symbol,
            name=name,
            timestamp=datetime.now(UTC),
            trigger=trigger,
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            verdict=verdict,
            risk_veto=risk_veto,
            risk_veto_reason=risk_veto_reason,
            checklist_passed=checklist_passed,
            checklist_warnings=checklist_warnings,
            final_action=final_action,
        )

        logger.info(
            "Debate for %s: bull=%d(%.2f) vs bear=%d(%.2f) -> %s (veto=%s)",
            symbol,
            len(bull_args),
            record.bull_score,
            len(bear_args),
            record.bear_score,
            final_action,
            risk_veto,
        )

        return record


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: LLM-driven multi-round debate (v55.0 FR-55-002)
# ═══════════════════════════════════════════════════════════════════════


class LLMDebateEngine:
    """Multi-round LLM adversarial debate with memory.

    Wraps the rule-based :class:`DebateEngine` as Phase 1 fallback.
    Each round: Bull LLM generates arguments → Bear LLM rebuts →
    after N rounds the Arbiter LLM synthesizes a verdict.

    Budget-aware: falls back to Phase 1 if LLM calls fail.
    """

    def __init__(
        self,
        gateway: Any,
        memory: Any | None = None,
        fallback_engine: DebateEngine | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._gateway = gateway
        self._memory = memory
        self._fallback = fallback_engine or DebateEngine(config)
        cfg = config or {}
        self._max_tokens = cfg.get("debate_max_tokens", 1024)
        self._bull_temp = cfg.get("bull_temperature", 0.4)
        self._bear_temp = cfg.get("bear_temperature", 0.3)
        self._arbiter_temp = cfg.get("arbiter_temperature", 0.2)

    def run_debate(
        self,
        symbol: str,
        name: str = "",
        trigger: str = "",
        market_data: dict[str, Any] | None = None,
        *,
        checklist_result: dict[str, Any] | None = None,
        max_rounds: int = 3,
    ) -> DebateRecord:
        """Run multi-round LLM debate with Phase 1 fallback.

        Args:
            symbol: Stock code.
            name: Stock name.
            trigger: What triggered the debate.
            market_data: Enriched market context dict.
            checklist_result: Munger checklist result.
            max_rounds: Number of Bull/Bear alternation rounds.

        Returns:
            DebateRecord with all arguments and verdict.
        """
        market_data = market_data or {}

        # Phase 1: Collect rule-based seed arguments
        seed_bull = self._fallback.collect_bull_arguments(market_data)
        seed_bear = self._fallback.collect_bear_arguments(market_data)

        # If max_rounds == 0 (CRITICAL urgency), use Phase 1 only
        if max_rounds == 0:
            return self._fallback.run_debate(
                symbol=symbol,
                name=name,
                trigger=trigger,
                market_data=market_data,
                checklist_result=checklist_result,
            )

        # Memory context
        memory_ctx = ""
        if self._memory:
            try:
                similar = self._memory.retrieve(
                    query=f"{name} {trigger}",
                    symbol=symbol,
                    top_k=3,
                )
                if similar:
                    lines = ["[相关历史辩论]"]
                    for s in similar:
                        lines.append(
                            f"- {s['name']}({s['symbol']}) "
                            f"决策={s['final_action']} "
                            f"(相似度{s['similarity']:.0%})"
                        )
                    memory_ctx = "\n".join(lines)

                reflection_ctx = self._memory.get_reflection_context(symbol)
                if reflection_ctx:
                    memory_ctx = (
                        f"{memory_ctx}\n\n{reflection_ctx}"
                        if memory_ctx
                        else reflection_ctx
                    )
            except Exception as exc:
                logger.warning("Debate memory retrieval failed: %s", exc)

        # Multi-round LLM debate
        all_bull: list[DebateArgument] = list(seed_bull)
        all_bear: list[DebateArgument] = list(seed_bear)

        market_summary = self._format_market_summary(market_data)

        try:
            for round_num in range(1, max_rounds + 1):
                # Bull rebuts bear arguments
                new_bull = self._generate_arguments(
                    perspective="bull",
                    symbol=symbol,
                    name=name,
                    round_num=round_num,
                    own_args=all_bull,
                    opponent_args=all_bear,
                    market_summary=market_summary,
                    memory_ctx=memory_ctx,
                )
                all_bull.extend(new_bull)

                # Bear rebuts bull arguments
                new_bear = self._generate_arguments(
                    perspective="bear",
                    symbol=symbol,
                    name=name,
                    round_num=round_num,
                    own_args=all_bear,
                    opponent_args=all_bull,
                    market_summary=market_summary,
                    memory_ctx=memory_ctx,
                )
                all_bear.extend(new_bear)

            # Arbiter LLM verdict
            verdict = self._arbiter_verdict_llm(
                symbol=symbol,
                name=name,
                bull_args=all_bull,
                bear_args=all_bear,
                market_data=market_data,
            )
        except Exception as exc:
            logger.warning(
                "LLM debate failed for %s, falling back to Phase 1: %s",
                symbol,
                exc,
            )
            return self._fallback.run_debate(
                symbol=symbol,
                name=name,
                trigger=trigger,
                market_data=market_data,
                checklist_result=checklist_result,
            )

        # Risk veto check (reuse Phase 1 logic)
        risk_veto = False
        risk_veto_reason = ""
        strong_bear = [
            a for a in all_bear if a.strength == "strong" and a.confidence >= 0.7
        ]
        if len(strong_bear) >= 2 and verdict.action in ("buy", "watch"):
            risk_veto = True
            risk_veto_reason = f"{len(strong_bear)}个强力空方论点触发风险否决"
            final_action = "hold"
        else:
            final_action = verdict.action

        # Checklist
        checklist_passed = True
        checklist_warnings: list[str] = []
        if checklist_result:
            checklist_passed = checklist_result.get("overall_passed", True)
            checklist_warnings = checklist_result.get("warnings", [])
            if not checklist_passed and final_action in ("buy", "watch"):
                final_action = "hold"

        record = DebateRecord(
            debate_id=str(uuid.uuid4()),
            symbol=symbol,
            name=name,
            timestamp=datetime.now(UTC),
            trigger=trigger,
            bull_arguments=all_bull,
            bear_arguments=all_bear,
            verdict=verdict,
            risk_veto=risk_veto,
            risk_veto_reason=risk_veto_reason,
            checklist_passed=checklist_passed,
            checklist_warnings=checklist_warnings,
            final_action=final_action,
        )

        # Store to memory
        if self._memory:
            try:
                self._memory.store(record.to_dict())
            except Exception as exc:
                logger.warning("Failed to store debate to memory: %s", exc)

        logger.info(
            "LLM debate for %s: %d rounds, bull=%d bear=%d -> %s (veto=%s)",
            symbol,
            max_rounds,
            len(all_bull),
            len(all_bear),
            final_action,
            risk_veto,
        )
        return record

    def _generate_arguments(
        self,
        perspective: str,
        symbol: str,
        name: str,
        round_num: int,
        own_args: list[DebateArgument],
        opponent_args: list[DebateArgument],
        market_summary: str,
        memory_ctx: str,
    ) -> list[DebateArgument]:
        """Use LLM to generate new arguments for one side."""
        from src.llm.base import LLMMessage

        side_cn = "多方(看涨)" if perspective == "bull" else "空方(看跌)"
        opp_cn = "空方" if perspective == "bull" else "多方"

        # Format existing arguments
        own_summary = "\n".join(
            f"- [{a.dimension}] {a.claim} (强度:{a.strength})" for a in own_args[-6:]
        )
        opp_summary = "\n".join(
            f"- [{a.dimension}] {a.claim} (强度:{a.strength})"
            for a in opponent_args[-6:]
        )

        system = (
            f"你是A股{side_cn}研究员。第{round_num}轮辩论。\n"
            f"针对{opp_cn}的论点提出反驳，并补充新的{side_cn}论据。\n"
            "输出JSON数组，每个元素: "
            '{"dimension":"technical/macro/capital_flow/sentiment",'
            '"claim":"核心论点(20字内)",'
            '"evidence":"支撑证据",'
            '"strength":"strong/moderate/weak",'
            '"confidence":0.0~1.0}\n'
            "输出1-3个论点，必须是新的（不重复已有论点）。仅输出JSON。"
        )

        user = f"## 股票: {name}({symbol})\n\n"
        if market_summary:
            user += f"## 市场数据\n{market_summary}\n\n"
        if memory_ctx:
            user += f"## 历史记忆\n{memory_ctx}\n\n"
        user += f"## 己方已有论点\n{own_summary}\n\n"
        user += f"## 对方论点（需反驳）\n{opp_summary}\n"

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

        caller = f"debate.{perspective}"
        temp = self._bull_temp if perspective == "bull" else self._bear_temp

        response = self._gateway.complete(
            messages=messages,
            caller=caller,
            max_tokens=self._max_tokens,
            temperature=temp,
            symbol=symbol,
            analysis_type="debate",
        )

        return self._parse_arguments(response.text, perspective)

    def _arbiter_verdict_llm(
        self,
        symbol: str,
        name: str,
        bull_args: list[DebateArgument],
        bear_args: list[DebateArgument],
        market_data: dict[str, Any],
    ) -> DebateVerdict:
        """LLM arbiter synthesizes final verdict from debate."""
        from src.llm.base import LLMMessage

        bull_text = "\n".join(
            f"- [{a.dimension}] {a.claim}: {a.evidence} "
            f"(强度:{a.strength}, 信心:{a.confidence:.0%})"
            for a in bull_args
        )
        bear_text = "\n".join(
            f"- [{a.dimension}] {a.claim}: {a.evidence} "
            f"(强度:{a.strength}, 信心:{a.confidence:.0%})"
            for a in bear_args
        )

        system = (
            "你是投资委员会仲裁者。综合多空双方论点做出最终裁决。\n"
            "输出严格JSON:\n"
            '{"action":"buy/sell/hold/reduce/watch",'
            '"conviction":"high/medium/low",'
            '"win_probability":0.0~1.0,'
            '"risk_reward_ratio":正数,'
            '"reasoning":"裁决理由(100字内)",'
            '"key_risk":"核心风险(30字内)",'
            '"stop_loss_pct":-0.03~-0.10,'
            '"take_profit_pct":0.03~0.15}\n'
            "仅输出JSON。"
        )

        user = (
            f"## {name}({symbol}) 辩论记录\n\n"
            f"### 多方论点 ({len(bull_args)}条)\n{bull_text}\n\n"
            f"### 空方论点 ({len(bear_args)}条)\n{bear_text}\n"
        )

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

        response = self._gateway.complete(
            messages=messages,
            caller="debate.arbiter",
            max_tokens=self._max_tokens,
            temperature=self._arbiter_temp,
            symbol=symbol,
            analysis_type="debate",
        )

        return self._parse_verdict(response.text, market_data)

    @staticmethod
    def _parse_arguments(text: str, perspective: str) -> list[DebateArgument]:
        """Parse LLM JSON output into DebateArgument list."""
        import json as _json
        import re

        if not text:
            return []

        # Extract JSON array from response
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return []

        try:
            items = _json.loads(match.group())
        except _json.JSONDecodeError:
            return []

        args: list[DebateArgument] = []
        for item in items[:3]:  # Max 3 per round
            if not isinstance(item, dict):
                continue
            args.append(
                DebateArgument(
                    perspective=perspective,
                    dimension=item.get("dimension", "technical"),
                    claim=item.get("claim", ""),
                    evidence=item.get("evidence", ""),
                    strength=item.get("strength", "moderate"),
                    confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
                )
            )
        return args

    @staticmethod
    def _parse_verdict(text: str, market_data: dict[str, Any]) -> DebateVerdict:
        """Parse LLM JSON output into DebateVerdict."""
        import json as _json
        import re

        defaults = DebateVerdict(
            action="hold",
            conviction="low",
            win_probability=0.5,
            risk_reward_ratio=1.0,
            reasoning="LLM裁决解析失败",
            key_risk="未知",
            stop_loss_pct=market_data.get("stop_loss_pct", -0.05),
            take_profit_pct=market_data.get("take_profit_pct", 0.08),
        )

        if not text:
            return defaults

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return defaults

        try:
            data = _json.loads(match.group())
        except _json.JSONDecodeError:
            return defaults

        return DebateVerdict(
            action=data.get("action", "hold"),
            conviction=data.get("conviction", "low"),
            win_probability=min(
                0.95, max(0.05, float(data.get("win_probability", 0.5)))
            ),
            risk_reward_ratio=max(0.1, float(data.get("risk_reward_ratio", 1.0))),
            reasoning=data.get("reasoning", ""),
            key_risk=data.get("key_risk", ""),
            stop_loss_pct=float(
                data.get("stop_loss_pct", market_data.get("stop_loss_pct", -0.05))
            ),
            take_profit_pct=float(
                data.get("take_profit_pct", market_data.get("take_profit_pct", 0.08))
            ),
        )

    @staticmethod
    def _format_market_summary(market_data: dict[str, Any]) -> str:
        """Format market_data dict into concise summary for LLM."""
        parts: list[str] = []

        price_chg = market_data.get("price_change_pct")
        if price_chg is not None:
            parts.append(f"涨跌幅: {price_chg:+.2f}%")

        rsi = market_data.get("rsi")
        if rsi is not None:
            parts.append(f"RSI: {rsi:.1f}")

        vol_ratio = market_data.get("volume_ratio")
        if vol_ratio is not None:
            parts.append(f"量比: {vol_ratio:.2f}")

        cap_flow = market_data.get("capital_net_inflow")
        if cap_flow is not None:
            parts.append(f"主力净流入: {cap_flow / 1e4:.0f}万")

        sentiment = market_data.get("sentiment_phase_cn")
        if sentiment:
            parts.append(f"情绪周期: {sentiment}")

        macro = market_data.get("macro_score")
        if macro is not None:
            parts.append(f"宏观评分: {macro:+.2f}")

        gain_5d = market_data.get("recent_5d_gain_pct")
        if gain_5d is not None:
            parts.append(f"近5日涨幅: {gain_5d:+.2f}%")

        return " | ".join(parts) if parts else "无市场数据"
