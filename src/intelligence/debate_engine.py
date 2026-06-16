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
        """Collect bullish arguments from available market data."""
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

        # Northbound inflow
        nb_flow = market_data.get("northbound_inflow")
        if nb_flow is not None and nb_flow > 0:
            args.append(
                DebateArgument(
                    perspective="bull",
                    dimension="capital_flow",
                    claim="北向资金流入",
                    evidence=f"北向资金净流入{nb_flow:.0f}亿元，外资看好",
                    strength="moderate",
                    confidence=0.6,
                )
            )

        return args

    def collect_bear_arguments(
        self, market_data: dict[str, Any]
    ) -> list[DebateArgument]:
        """Collect bearish arguments from available market data."""
        args: list[DebateArgument] = []

        # Technical bearish signals
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

        # Volume divergence
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

        # Capital outflow
        capital_flow = market_data.get("capital_net_inflow")
        if capital_flow is not None and capital_flow < -5000:
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

        # High recent gain (chase risk)
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

        # T+1 overnight risk
        if market_data.get("t_plus_1_risk"):
            args.append(
                DebateArgument(
                    perspective="bear",
                    dimension="technical",
                    claim="T+1隔夜风险",
                    evidence="A股T+1规则下，买入后必须承受至少1个隔夜风险",
                    strength="weak",
                    confidence=0.5,
                )
            )

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
