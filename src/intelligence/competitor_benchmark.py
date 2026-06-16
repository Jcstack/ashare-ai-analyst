"""Competitor / peer benchmarking module (FR-IA003).

Provides rule-based peer comparison for A-share stocks using pre-defined
sector peer groups.  No LLM calls — purely deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Peer group definitions — extends rotation_engine.py SECTOR_REPRESENTATIVES
# ---------------------------------------------------------------------------

PEER_GROUPS: dict[str, list[dict[str, str]]] = {
    "黄金": [
        {"symbol": "002155", "name": "湖南黄金"},
        {"symbol": "600489", "name": "中金黄金"},
        {"symbol": "600547", "name": "山东黄金"},
        {"symbol": "600988", "name": "赤峰黄金"},
    ],
    "石油": [
        {"symbol": "601857", "name": "中国石油"},
        {"symbol": "600028", "name": "中国石化"},
        {"symbol": "601808", "name": "中海油服"},
        {"symbol": "600583", "name": "海油工程"},
    ],
    "银行": [
        {"symbol": "600036", "name": "招商银行"},
        {"symbol": "601398", "name": "工商银行"},
        {"symbol": "601166", "name": "兴业银行"},
        {"symbol": "601288", "name": "农业银行"},
        {"symbol": "601328", "name": "交通银行"},
    ],
    "消费": [
        {"symbol": "600519", "name": "贵州茅台"},
        {"symbol": "000858", "name": "五粮液"},
        {"symbol": "000568", "name": "泸州老窖"},
        {"symbol": "000596", "name": "古井贡酒"},
        {"symbol": "603369", "name": "今世缘"},
    ],
    "航运": [
        {"symbol": "601919", "name": "中远海控"},
        {"symbol": "601872", "name": "招商轮船"},
        {"symbol": "600026", "name": "中远海能"},
    ],
    "新能源": [
        {"symbol": "601012", "name": "隆基绿能"},
        {"symbol": "300750", "name": "宁德时代"},
        {"symbol": "002459", "name": "晶澳科技"},
        {"symbol": "600438", "name": "通威股份"},
    ],
    "军工": [
        {"symbol": "600893", "name": "航发动力"},
        {"symbol": "600760", "name": "中航沈飞"},
        {"symbol": "000768", "name": "中航西飞"},
        {"symbol": "601989", "name": "中国重工"},
    ],
    "纺织服装": [
        {"symbol": "000726", "name": "鲁泰纺织"},
        {"symbol": "600398", "name": "海澜之家"},
        {"symbol": "002563", "name": "森马服饰"},
    ],
    "航空": [
        {"symbol": "600115", "name": "东方航空"},
        {"symbol": "601111", "name": "中国国航"},
        {"symbol": "600029", "name": "南方航空"},
    ],
    "科技": [
        {"symbol": "002230", "name": "科大讯飞"},
        {"symbol": "000725", "name": "京东方A"},
        {"symbol": "600570", "name": "恒生电子"},
        {"symbol": "002415", "name": "海康威视"},
    ],
    "医药": [
        {"symbol": "600276", "name": "恒瑞医药"},
        {"symbol": "300760", "name": "迈瑞医疗"},
        {"symbol": "000538", "name": "云南白药"},
        {"symbol": "600196", "name": "复星医药"},
    ],
    "地产": [
        {"symbol": "001979", "name": "招商蛇口"},
        {"symbol": "000002", "name": "万科A"},
        {"symbol": "600048", "name": "保利发展"},
    ],
}

# Sector-level characteristic tags used for strengths/weaknesses comparison
_SECTOR_TRAITS: dict[str, dict[str, Any]] = {
    "黄金": {"cycle": "逆周期", "volatility": "高", "policy_sensitive": False},
    "石油": {"cycle": "顺周期", "volatility": "高", "policy_sensitive": True},
    "银行": {"cycle": "顺周期", "volatility": "低", "policy_sensitive": True},
    "消费": {"cycle": "弱周期", "volatility": "中", "policy_sensitive": False},
    "航运": {"cycle": "顺周期", "volatility": "高", "policy_sensitive": False},
    "新能源": {"cycle": "成长", "volatility": "高", "policy_sensitive": True},
    "军工": {"cycle": "独立", "volatility": "高", "policy_sensitive": True},
    "纺织服装": {"cycle": "弱周期", "volatility": "低", "policy_sensitive": False},
    "航空": {"cycle": "顺周期", "volatility": "中", "policy_sensitive": True},
    "科技": {"cycle": "成长", "volatility": "高", "policy_sensitive": True},
    "医药": {"cycle": "弱周期", "volatility": "中", "policy_sensitive": True},
    "地产": {"cycle": "顺周期", "volatility": "高", "policy_sensitive": True},
}

# Per-stock trait overrides (market cap tier + leadership flag)
_STOCK_TRAITS: dict[str, dict[str, Any]] = {
    "600519": {"tier": "mega", "leader": True, "brand_power": "极强"},
    "000858": {"tier": "large", "leader": True, "brand_power": "强"},
    "600036": {"tier": "mega", "leader": True, "brand_power": "强"},
    "601398": {"tier": "mega", "leader": True, "brand_power": "强"},
    "300750": {"tier": "mega", "leader": True, "brand_power": "强"},
    "601857": {"tier": "mega", "leader": True, "brand_power": "中"},
    "600028": {"tier": "mega", "leader": True, "brand_power": "中"},
    "002415": {"tier": "mega", "leader": True, "brand_power": "强"},
    "600276": {"tier": "large", "leader": True, "brand_power": "强"},
    "000002": {"tier": "large", "leader": True, "brand_power": "强"},
}


@dataclass
class PeerComparison:
    """Result of comparing a stock against its sector peers."""

    symbol: str
    name: str
    sector: str
    metrics: dict[str, Any] = field(default_factory=dict)
    rank_in_peers: int = 0
    peer_count: int = 0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "metrics": self.metrics,
            "rank_in_peers": self.rank_in_peers,
            "peer_count": self.peer_count,
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
        }


class CompetitorBenchmark:
    """Rule-based competitor / peer benchmarking engine.

    Uses pre-defined sector peer groups for comparison.
    No external data or LLM calls — deterministic results.
    """

    def __init__(self) -> None:
        self._peer_groups = PEER_GROUPS
        # Build reverse index: symbol -> sector
        self._symbol_to_sector: dict[str, str] = {}
        for sector, stocks in self._peer_groups.items():
            for stock in stocks:
                self._symbol_to_sector[stock["symbol"]] = sector
        logger.info(
            "CompetitorBenchmark initialized: %d sectors, %d stocks",
            len(self._peer_groups),
            len(self._symbol_to_sector),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_peers(self, symbol: str, name: str = "") -> list[dict[str, str]]:
        """Find same-sector peers for a given stock.

        Args:
            symbol: Stock code (e.g. ``"600519"``).
            name: Optional stock name, used for fuzzy sector matching.

        Returns:
            List of peer dicts with ``symbol``, ``name``, ``sector`` keys.
            Empty list if no sector match found.
        """
        sector = self._resolve_sector(symbol, name)
        if sector is None:
            return []

        peers: list[dict[str, str]] = []
        for stock in self._peer_groups.get(sector, []):
            if stock["symbol"] != symbol:
                peers.append({
                    "symbol": stock["symbol"],
                    "name": stock["name"],
                    "sector": sector,
                })
        return peers

    def compare(
        self,
        symbol: str,
        name: str = "",
        current_price: float | None = None,
    ) -> PeerComparison | None:
        """Compare a stock against its sector peers.

        Args:
            symbol: Stock code.
            name: Stock name (optional, helps sector resolution).
            current_price: Current price (optional, used in metrics).

        Returns:
            A ``PeerComparison`` or ``None`` if sector cannot be determined.
        """
        sector = self._resolve_sector(symbol, name)
        if sector is None:
            logger.debug("No sector match for %s (%s)", symbol, name)
            return None

        group = self._peer_groups.get(sector, [])
        peer_count = len(group)

        # Compute rank — leader stocks rank higher, then alphabetical
        ranked = self._rank_peers(sector, group)
        rank = 1
        for i, s in enumerate(ranked, start=1):
            if s["symbol"] == symbol:
                rank = i
                break

        # Build metrics dict
        traits = _STOCK_TRAITS.get(symbol, {})
        sector_traits = _SECTOR_TRAITS.get(sector, {})
        metrics: dict[str, Any] = {
            "sector_cycle": sector_traits.get("cycle", "未知"),
            "sector_volatility": sector_traits.get("volatility", "中"),
            "policy_sensitive": sector_traits.get("policy_sensitive", False),
            "tier": traits.get("tier", "mid"),
            "is_leader": traits.get("leader", False),
        }
        if current_price is not None:
            metrics["current_price"] = current_price

        # Derive strengths / weaknesses
        strengths, weaknesses = self._assess(symbol, sector, traits, sector_traits)

        comparison = PeerComparison(
            symbol=symbol,
            name=name or self._resolve_name(symbol, group),
            sector=sector,
            metrics=metrics,
            rank_in_peers=rank,
            peer_count=peer_count,
            strengths=strengths,
            weaknesses=weaknesses,
        )

        logger.info(
            "Peer comparison: %s (%s) — rank %d/%d in %s",
            symbol,
            name,
            rank,
            peer_count,
            sector,
        )
        return comparison

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_sector(self, symbol: str, name: str = "") -> str | None:
        """Resolve sector from symbol or name."""
        # Direct symbol lookup
        if symbol in self._symbol_to_sector:
            return self._symbol_to_sector[symbol]

        # Fuzzy name-based matching
        if name:
            name_lower = name.lower()
            for sector, stocks in self._peer_groups.items():
                for stock in stocks:
                    if stock["name"] in name_lower or name_lower in stock["name"]:
                        return sector
            # Try sector name in stock name
            for sector in self._peer_groups:
                if sector in name:
                    return sector

        return None

    def _resolve_name(self, symbol: str, group: list[dict[str, str]]) -> str:
        """Look up name from peer group."""
        for stock in group:
            if stock["symbol"] == symbol:
                return stock["name"]
        return symbol

    def _rank_peers(
        self, sector: str, group: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Rank peers within sector — leaders first, then by symbol."""

        def sort_key(stock: dict[str, str]) -> tuple[int, str]:
            traits = _STOCK_TRAITS.get(stock["symbol"], {})
            # Leaders rank first (0), non-leaders second (1)
            leader_rank = 0 if traits.get("leader", False) else 1
            # Mega > large > mid
            tier = traits.get("tier", "mid")
            tier_rank = {"mega": 0, "large": 1, "mid": 2}.get(tier, 2)
            return (leader_rank * 10 + tier_rank, stock["symbol"])

        return sorted(group, key=sort_key)

    def _assess(
        self,
        symbol: str,
        sector: str,
        traits: dict[str, Any],
        sector_traits: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        """Derive strengths and weaknesses from traits."""
        strengths: list[str] = []
        weaknesses: list[str] = []

        # Leadership
        if traits.get("leader", False):
            strengths.append(f"{sector}板块龙头企业")
        else:
            weaknesses.append("非板块龙头，市场关注度相对较低")

        # Market cap tier
        tier = traits.get("tier", "mid")
        if tier == "mega":
            strengths.append("超大市值，流动性充裕")
        elif tier == "large":
            strengths.append("大市值，流动性良好")
        else:
            weaknesses.append("中小市值，流动性风险较高")

        # Brand power
        brand = traits.get("brand_power")
        if brand in ("极强", "强"):
            strengths.append(f"品牌影响力{brand}")

        # Sector cycle
        cycle = sector_traits.get("cycle", "")
        if cycle == "弱周期":
            strengths.append("弱周期属性，防御性强")
        elif cycle == "逆周期":
            strengths.append("逆周期属性，市场下跌时有对冲价值")
        elif cycle == "顺周期":
            weaknesses.append("顺周期属性，经济下行时承压")

        # Volatility
        vol = sector_traits.get("volatility", "中")
        if vol == "高":
            weaknesses.append("板块波动性较高")
        elif vol == "低":
            strengths.append("板块波动性低，适合稳健配置")

        # Policy sensitivity
        if sector_traits.get("policy_sensitive", False):
            weaknesses.append("受政策影响较大")

        return strengths, weaknesses
