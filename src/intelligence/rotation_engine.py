"""Active Rotation Engine — generates portfolio rotation recommendations.

Per PRD v34.0 FR-PA002: When a position's macro score drops below threshold,
automatically search for benefiting sectors and recommend rotation targets.

Flow:
1. Detect position under macro pressure (score < -0.3)
2. Identify which macro factors are causing pressure
3. Find sectors that benefit from current macro environment
4. Filter candidates through TradingConstraintsEngine
5. Output complete rotation plan: sell X -> buy [Y1, Y2, Y3]
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.intelligence.impact_chain import ImpactChainEngine
from src.intelligence.position_macro_mapper import (
    MacroEnvironment,
    PositionMacroMapper,
    PositionMacroProfile,
    SECTOR_PROFILES,
)
from src.trading.constraints import TradingConstraintsEngine

logger = logging.getLogger(__name__)


@dataclass
class RotationCandidate:
    """A candidate stock to rotate into."""

    symbol: str
    name: str
    sector: str
    board: str
    macro_score: float
    reason: str
    constraint_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "board": self.board,
            "macro_score": round(self.macro_score, 3),
            "reason": self.reason,
            "constraint_warnings": self.constraint_warnings,
        }


@dataclass
class RotationPlan:
    """A complete rotation recommendation."""

    plan_id: str
    timestamp: datetime
    trigger_reason: str

    # Position to exit
    sell_symbol: str
    sell_name: str
    sell_macro_score: float
    sell_reason: str

    # Candidates to consider
    buy_candidates: list[RotationCandidate] = field(default_factory=list)

    # Blocked candidates (failed constraint check)
    blocked_candidates: list[dict[str, str]] = field(default_factory=list)

    # Risk note
    risk_note: str = ""
    overnight_warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "timestamp": self.timestamp.isoformat(),
            "trigger_reason": self.trigger_reason,
            "sell": {
                "symbol": self.sell_symbol,
                "name": self.sell_name,
                "macro_score": round(self.sell_macro_score, 3),
                "reason": self.sell_reason,
            },
            "buy_candidates": [c.to_dict() for c in self.buy_candidates],
            "blocked_candidates": self.blocked_candidates,
            "risk_note": self.risk_note,
            "overnight_warning": self.overnight_warning,
        }


# Sector -> representative stocks (main board only)
SECTOR_REPRESENTATIVES: dict[str, list[dict[str, str]]] = {
    "黄金": [
        {"symbol": "002155", "name": "湖南黄金"},
        {"symbol": "600489", "name": "中金黄金"},
        {"symbol": "600547", "name": "山东黄金"},
    ],
    "石油": [
        {"symbol": "601857", "name": "中国石油"},
        {"symbol": "600028", "name": "中国石化"},
    ],
    "银行": [
        {"symbol": "600036", "name": "招商银行"},
        {"symbol": "601398", "name": "工商银行"},
        {"symbol": "601166", "name": "兴业银行"},
    ],
    "消费": [
        {"symbol": "600519", "name": "贵州茅台"},
        {"symbol": "000858", "name": "五粮液"},
        {"symbol": "000568", "name": "泸州老窖"},
    ],
    "航运": [
        {"symbol": "601919", "name": "中远海控"},
        {"symbol": "601872", "name": "招商轮船"},
    ],
    "新能源": [
        {"symbol": "601012", "name": "隆基绿能"},
    ],
    "军工": [
        {"symbol": "600893", "name": "航发动力"},
        {"symbol": "600760", "name": "中航沈飞"},
    ],
    "纺织服装": [
        {"symbol": "000726", "name": "鲁泰纺织"},
        {"symbol": "600398", "name": "海澜之家"},
    ],
    "航空": [
        {"symbol": "600115", "name": "东方航空"},
        {"symbol": "601111", "name": "中国国航"},
    ],
}


class RotationEngine:
    """Generates portfolio rotation recommendations based on macro analysis.

    Integrates:
    - PositionMacroMapper: identifies which positions are under pressure
    - ImpactChainEngine: understands why (event chain)
    - TradingConstraintsEngine: filters candidates by A-share rules
    """

    def __init__(
        self,
        macro_mapper: PositionMacroMapper | None = None,
        constraints: TradingConstraintsEngine | None = None,
        impact_chain: ImpactChainEngine | None = None,
        rotation_threshold: float = -0.3,
    ) -> None:
        self._mapper = macro_mapper or PositionMacroMapper()
        self._constraints = constraints or TradingConstraintsEngine()
        self._impact_chain = impact_chain or ImpactChainEngine()
        self._rotation_threshold = rotation_threshold
        logger.info("RotationEngine initialized (threshold=%.2f)", rotation_threshold)

    def find_benefiting_sectors(self, env: MacroEnvironment) -> list[tuple[str, float]]:
        """Find sectors that benefit from current macro environment.

        Returns:
            List of (sector, score) tuples sorted by score descending.
        """
        sector_scores: list[tuple[str, float]] = []

        for sector, sensitivities in SECTOR_PROFILES.items():
            score = self._mapper.compute_macro_score(sensitivities, env)
            sector_scores.append((sector, score))

        sector_scores.sort(key=lambda x: x[1], reverse=True)
        return sector_scores

    def generate_rotation_plan(
        self,
        profile: PositionMacroProfile,
        env: MacroEnvironment,
        *,
        max_candidates: int = 5,
    ) -> RotationPlan:
        """Generate a rotation plan for a position under macro pressure.

        Args:
            profile: The position's macro profile (with negative score).
            env: Current macro environment.
            max_candidates: Max buy candidates to return.
        """
        # Find benefiting sectors (exclude the current one)
        sector_scores = self.find_benefiting_sectors(env)
        benefiting = [
            (sector, score)
            for sector, score in sector_scores
            if score > 0 and sector != profile.sector
        ]

        # Build candidate list from benefiting sectors
        raw_candidates: list[dict[str, Any]] = []
        for sector, sector_score in benefiting:
            reps = SECTOR_REPRESENTATIVES.get(sector, [])
            for rep in reps:
                raw_candidates.append(
                    {
                        "symbol": rep["symbol"],
                        "name": rep["name"],
                        "sector": sector,
                        "sector_macro_score": sector_score,
                    }
                )

        # Filter through constraints
        passed, rejected = self._constraints.filter_candidates(raw_candidates)

        # Build RotationCandidates
        buy_candidates: list[RotationCandidate] = []
        for c in passed[:max_candidates]:
            buy_candidates.append(
                RotationCandidate(
                    symbol=c["symbol"],
                    name=c["name"],
                    sector=c["sector"],
                    board=self._constraints.get_board(c["symbol"]),
                    macro_score=c["sector_macro_score"],
                    reason=f"{c['sector']}板块受益于当前宏观环境",
                    constraint_warnings=c.get("constraint_warnings", []),
                )
            )

        # Build blocked list
        blocked = [
            {
                "symbol": r.symbol,
                "name": r.name,
                "reason": r.violations[0].message if r.violations else "约束检查失败",
            }
            for r in rejected
        ]

        plan = RotationPlan(
            plan_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            trigger_reason=profile.rotation_reason,
            sell_symbol=profile.symbol,
            sell_name=profile.name,
            sell_macro_score=profile.current_macro_score,
            sell_reason=profile.rotation_reason,
            buy_candidates=buy_candidates,
            blocked_candidates=blocked,
            risk_note=(
                "轮动建议仅供参考。如判断错误，应设置止损位控制风险。"
                "超短线策略下建议次日确认趋势后再操作。"
            ),
            overnight_warning=self._constraints.overnight_risk_note(),
        )

        logger.info(
            "Rotation plan for %s: %d candidates, %d blocked",
            profile.symbol,
            len(buy_candidates),
            len(blocked),
        )
        return plan

    def scan_portfolio(
        self,
        positions: list[dict[str, Any]],
        env: MacroEnvironment,
    ) -> list[RotationPlan]:
        """Scan entire portfolio and generate rotation plans for stressed positions.

        Args:
            positions: List of position dicts with 'symbol' and 'name'.
            env: Current macro environment.

        Returns:
            List of RotationPlan for positions needing rotation.
        """
        profiles = self._mapper.analyze_portfolio(positions, env)
        plans: list[RotationPlan] = []

        for profile in profiles:
            if profile.current_macro_score <= self._rotation_threshold:
                plan = self.generate_rotation_plan(profile, env)
                plans.append(plan)

        if plans:
            logger.warning(
                "Portfolio rotation scan: %d positions need rotation", len(plans)
            )

        return plans
