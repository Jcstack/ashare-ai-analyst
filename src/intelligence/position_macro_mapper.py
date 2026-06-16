"""Position-Macro Mapper — maps each portfolio holding to macro factor sensitivities.

Per PRD v34.0 FR-PA001: Automatic position-to-macro correlation matrix.

For each holding (e.g. 湖南黄金 002155), determines sensitivity to:
- gold_price, usd_index, fed_rate, oil_price, risk_aversion, etc.
Then computes a composite macro score [-1, +1] and rotation signal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Pre-defined sector -> macro sensitivity profiles
# Sensitivity range: [-1.0, +1.0] where positive = asset rises when factor rises
SECTOR_PROFILES: dict[str, dict[str, float]] = {
    "黄金": {
        "gold_price": 0.85,
        "usd_index": -0.72,
        "fed_rate": -0.45,
        "oil_price": 0.15,
        "risk_aversion": 0.80,
        "inflation": 0.60,
    },
    "贵金属": {
        "gold_price": 0.80,
        "usd_index": -0.65,
        "fed_rate": -0.40,
        "oil_price": 0.10,
        "risk_aversion": 0.70,
        "inflation": 0.55,
    },
    "石油": {
        "gold_price": 0.10,
        "usd_index": -0.30,
        "fed_rate": -0.20,
        "oil_price": 0.85,
        "risk_aversion": -0.10,
        "inflation": 0.40,
    },
    "航运": {
        "gold_price": 0.0,
        "usd_index": -0.15,
        "fed_rate": -0.10,
        "oil_price": -0.50,
        "risk_aversion": -0.20,
        "inflation": -0.15,
    },
    "银行": {
        "gold_price": -0.05,
        "usd_index": 0.10,
        "fed_rate": 0.35,
        "oil_price": -0.05,
        "risk_aversion": -0.30,
        "inflation": -0.10,
    },
    "消费": {
        "gold_price": 0.0,
        "usd_index": -0.10,
        "fed_rate": -0.15,
        "oil_price": -0.10,
        "risk_aversion": -0.20,
        "inflation": -0.25,
    },
    "科技": {
        "gold_price": 0.0,
        "usd_index": -0.20,
        "fed_rate": -0.50,
        "oil_price": -0.10,
        "risk_aversion": -0.40,
        "inflation": -0.30,
    },
    "新能源": {
        "gold_price": 0.0,
        "usd_index": -0.15,
        "fed_rate": -0.40,
        "oil_price": 0.25,
        "risk_aversion": -0.30,
        "inflation": -0.10,
    },
    "军工": {
        "gold_price": 0.10,
        "usd_index": 0.0,
        "fed_rate": -0.10,
        "oil_price": 0.10,
        "risk_aversion": 0.50,
        "inflation": 0.05,
    },
    "纺织服装": {
        "gold_price": 0.0,
        "usd_index": 0.40,  # export benefits from weak RMB
        "fed_rate": -0.10,
        "oil_price": -0.15,
        "risk_aversion": -0.10,
        "inflation": -0.15,
    },
    "航空": {
        "gold_price": 0.0,
        "usd_index": -0.50,  # USD debt + fuel cost
        "fed_rate": -0.15,
        "oil_price": -0.60,
        "risk_aversion": -0.30,
        "inflation": -0.20,
    },
    "房地产": {
        "gold_price": 0.0,
        "usd_index": -0.10,
        "fed_rate": -0.55,
        "oil_price": -0.05,
        "risk_aversion": -0.35,
        "inflation": -0.30,
    },
}

# Stock code -> sector mapping for known stocks
STOCK_SECTOR_MAP: dict[str, str] = {
    "002155": "黄金",  # 湖南黄金
    "600489": "黄金",  # 中金黄金
    "600547": "黄金",  # 山东黄金
    "600988": "黄金",  # 赤峰黄金
    "601857": "石油",  # 中国石油
    "600028": "石油",  # 中国石化
    "601919": "航运",  # 中远海控
    "601872": "航运",  # 招商轮船
    "600519": "消费",  # 贵州茅台
    "000858": "消费",  # 五粮液
    "601318": "银行",  # 中国平安 (insurance but correlated)
    "600036": "银行",  # 招商银行
    "601398": "银行",  # 工商银行
    "600115": "航空",  # 东方航空
    "601111": "航空",  # 中国国航
    "000726": "纺织服装",  # 鲁泰纺织
    "600398": "纺织服装",  # 海澜之家
    "601012": "新能源",  # 隆基绿能
    "600893": "军工",  # 航发动力
    "600111": "贵金属",  # 北方稀土
}


@dataclass
class MacroEnvironment:
    """Current state of macro factors, normalized to directional change."""

    gold_price: float = 0.0  # positive = gold rising
    usd_index: float = 0.0  # positive = USD strengthening
    fed_rate: float = 0.0  # positive = hawkish/tightening
    oil_price: float = 0.0  # positive = oil rising
    risk_aversion: float = 0.0  # positive = risk-off sentiment
    inflation: float = 0.0  # positive = inflation rising

    def to_dict(self) -> dict[str, float]:
        return {
            "gold_price": self.gold_price,
            "usd_index": self.usd_index,
            "fed_rate": self.fed_rate,
            "oil_price": self.oil_price,
            "risk_aversion": self.risk_aversion,
            "inflation": self.inflation,
        }


@dataclass
class PositionMacroProfile:
    """Macro sensitivity profile for a single portfolio position."""

    symbol: str
    name: str
    sector: str
    macro_sensitivities: dict[str, float] = field(default_factory=dict)
    current_macro_score: float = 0.0  # [-1, +1]
    rotation_signal: str = "hold"  # "hold" | "reduce" | "exit" | "add"
    rotation_reason: str = ""
    macro_environment: dict[str, float] = field(default_factory=dict)

    @property
    def top_factor(self) -> str:
        """Return the macro factor with highest absolute sensitivity."""
        if not self.macro_sensitivities:
            return "—"
        return max(self.macro_sensitivities, key=lambda k: abs(self.macro_sensitivities[k]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "macro_sensitivities": self.macro_sensitivities,
            "macro_score": round(self.current_macro_score, 3),
            "rotation_signal": self.rotation_signal,
            "rotation_reason": self.rotation_reason,
            "top_factor": self.top_factor,
        }


class PositionMacroMapper:
    """Maps portfolio positions to macro factor sensitivities and generates signals.

    Usage:
        mapper = PositionMacroMapper()
        env = MacroEnvironment(gold_price=-0.5, usd_index=0.8, ...)
        profiles = mapper.analyze_portfolio(positions, env)
        for p in profiles:
            if p.rotation_signal == "exit":
                print(f"Consider exiting {p.name}: {p.rotation_reason}")
    """

    ROTATION_THRESHOLDS = {
        "exit": -0.5,
        "reduce": -0.3,
        "add": 0.3,
    }

    def __init__(
        self,
        sector_profiles: dict[str, dict[str, float]] | None = None,
        stock_sector_map: dict[str, str] | None = None,
        rotation_thresholds: dict[str, float] | None = None,
    ) -> None:
        self._sector_profiles = sector_profiles or SECTOR_PROFILES
        self._stock_sector_map = stock_sector_map or STOCK_SECTOR_MAP
        if rotation_thresholds:
            self.ROTATION_THRESHOLDS = rotation_thresholds
        logger.info("PositionMacroMapper initialized")

    def get_sector(self, symbol: str) -> str:
        """Look up sector for a stock code."""
        return self._stock_sector_map.get(symbol, "unknown")

    def get_sensitivities(self, symbol: str) -> dict[str, float]:
        """Get macro sensitivities for a stock based on its sector."""
        sector = self.get_sector(symbol)
        return self._sector_profiles.get(sector, {})

    def compute_macro_score(
        self, sensitivities: dict[str, float], env: MacroEnvironment
    ) -> float:
        """Compute composite macro score for a position.

        Score = sum(sensitivity_i * environment_i) normalized to [-1, +1].
        Positive score = macro environment favorable for this position.
        """
        if not sensitivities:
            return 0.0

        env_dict = env.to_dict()
        raw_score = sum(
            sensitivities.get(factor, 0.0) * env_dict.get(factor, 0.0)
            for factor in env_dict
        )

        # Normalize by max possible score
        max_possible = sum(abs(v) for v in sensitivities.values())
        if max_possible == 0:
            return 0.0

        return max(min(raw_score / max_possible, 1.0), -1.0)

    def determine_rotation_signal(self, score: float) -> tuple[str, str]:
        """Determine rotation signal from macro score.

        Returns:
            (signal, reason) tuple.
        """
        if score <= self.ROTATION_THRESHOLDS["exit"]:
            return "exit", "宏观环境极度不利，建议考虑退出"
        if score <= self.ROTATION_THRESHOLDS["reduce"]:
            return "reduce", "宏观环境偏空，建议减仓"
        if score >= self.ROTATION_THRESHOLDS["add"]:
            return "add", "宏观环境有利，可考虑加仓"
        return "hold", "宏观环境中性，维持现有仓位"

    def analyze_position(
        self,
        symbol: str,
        name: str,
        env: MacroEnvironment,
    ) -> PositionMacroProfile:
        """Analyze a single position against current macro environment."""
        sector = self.get_sector(symbol)
        sensitivities = self.get_sensitivities(symbol)
        score = self.compute_macro_score(sensitivities, env)
        signal, reason = self.determine_rotation_signal(score)

        # Build detailed reason with top contributing factors
        if sensitivities and signal != "hold":
            env_dict = env.to_dict()
            contributions = sorted(
                [
                    (
                        factor,
                        sensitivities.get(factor, 0.0) * env_dict.get(factor, 0.0),
                    )
                    for factor in env_dict
                    if abs(sensitivities.get(factor, 0.0) * env_dict.get(factor, 0.0))
                    > 0.05
                ],
                key=lambda x: abs(x[1]),
                reverse=True,
            )
            if contributions:
                factor_names = {
                    "gold_price": "金价",
                    "usd_index": "美元",
                    "fed_rate": "利率",
                    "oil_price": "油价",
                    "risk_aversion": "避险",
                    "inflation": "通胀",
                }
                top_factors = [
                    f"{factor_names.get(f, f)}{'↑' if v > 0 else '↓'}"
                    for f, v in contributions[:3]
                ]
                reason = f"{reason} (主要因素: {', '.join(top_factors)})"

        return PositionMacroProfile(
            symbol=symbol,
            name=name,
            sector=sector,
            macro_sensitivities=sensitivities,
            current_macro_score=score,
            rotation_signal=signal,
            rotation_reason=reason,
            macro_environment=env.to_dict(),
        )

    def analyze_portfolio(
        self,
        positions: list[dict[str, Any]],
        env: MacroEnvironment,
    ) -> list[PositionMacroProfile]:
        """Analyze all portfolio positions against current macro environment.

        Args:
            positions: List of dicts with at least 'symbol' and 'name' keys.
            env: Current macro environment state.

        Returns:
            List of PositionMacroProfile, sorted by macro_score ascending
            (worst-positioned first).
        """
        profiles = [
            self.analyze_position(
                symbol=p["symbol"],
                name=p.get("name", p["symbol"]),
                env=env,
            )
            for p in positions
        ]
        profiles.sort(key=lambda p: p.current_macro_score)

        # Log summary
        exit_count = sum(1 for p in profiles if p.rotation_signal == "exit")
        reduce_count = sum(1 for p in profiles if p.rotation_signal == "reduce")
        if exit_count or reduce_count:
            logger.warning(
                "Portfolio macro scan: %d exit, %d reduce signals out of %d positions",
                exit_count,
                reduce_count,
                len(profiles),
            )

        return profiles

    def portfolio_macro_exposure(
        self,
        positions: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Calculate portfolio-level macro factor exposure (weighted by equal weight).

        Returns a dict of factor -> aggregate sensitivity for the portfolio.
        """
        if not positions:
            return {}

        aggregate: dict[str, float] = {}
        count = 0
        for p in positions:
            sens = self.get_sensitivities(p["symbol"])
            if sens:
                count += 1
                for factor, value in sens.items():
                    aggregate[factor] = aggregate.get(factor, 0.0) + value

        if count == 0:
            return {}

        return {k: round(v / count, 3) for k, v in aggregate.items()}
