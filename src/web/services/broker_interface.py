"""Broker interface — abstract broker with simulation-first default.

Defines the contract for portfolio reads and trade execution,
with SimulationBroker as the default (reads from local portfolio.json,
writes are simulation records only).

LiveBroker is a stub requiring explicit config + gate verification.

Part of v18.0 Agent Spec Compliance — Phase 4.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("web.broker")


@dataclass
class Position:
    """A portfolio position."""

    symbol: str
    stock_name: str = ""
    shares: int = 0
    cost_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class Balance:
    """Account balance."""

    total_assets: float = 0.0
    available_cash: float = 0.0
    market_value: float = 0.0
    utilization_rate: float = 0.0


@dataclass
class OrderStatus:
    """Status of a submitted order."""

    order_id: str
    symbol: str
    action: str
    shares: int
    price: float
    status: str = "unknown"  # pending, filled, cancelled, rejected
    filled_at: str = ""
    message: str = ""


@dataclass
class SimulationOrder:
    """Record of a simulated order (not actually executed)."""

    order_id: str
    gate_request_id: str
    symbol: str
    action: str
    shares: int
    price: float
    status: str = "simulated"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")


class BrokerInterface(ABC):
    """Abstract broker interface.

    All concrete brokers must implement position reads.
    Trade execution is optional (SimulationBroker records but doesn't execute).
    """

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Get current portfolio positions."""

    @abstractmethod
    def get_balance(self) -> Balance:
        """Get account balance."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get status of a previously submitted order."""

    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        gate_request_id: str = "",
    ) -> OrderStatus:
        """Submit an order for execution.

        For SimulationBroker, this creates a simulation record.
        For LiveBroker, this would submit to a real exchange.
        """

    @property
    @abstractmethod
    def mode(self) -> str:
        """Return broker mode: 'simulation' or 'live'."""


class SimulationBroker(BrokerInterface):
    """Default broker — reads from SQLite PortfolioStore.

    No real trades are ever executed. All orders are recorded as
    simulation records for audit purposes.
    """

    def __init__(self) -> None:
        self._simulation_orders: list[SimulationOrder] = []

    def get_positions(self) -> list[Position]:
        """Read positions from SQLite (single source of truth)."""
        data = self._read_portfolio()
        positions = []
        for p in data.get("positions", []):
            positions.append(
                Position(
                    symbol=p.get("symbol", ""),
                    stock_name=p.get("name", p.get("stock_name", "")),
                    shares=int(p.get("shares", 0)),
                    cost_price=float(p.get("cost_price", p.get("costPrice", 0.0))),
                    current_price=float(p.get("current_price", 0.0)),
                    market_value=float(p.get("market_value", 0.0)),
                    pnl=float(p.get("pnl", 0.0)),
                    pnl_pct=float(p.get("pnl_pct", 0.0)),
                )
            )
        return positions

    def get_balance(self) -> Balance:
        """Read balance from capital service."""
        try:
            from src.web.services.capital_service import CapitalService

            svc = CapitalService()
            balance = svc.get_balance()
            return Balance(
                total_assets=balance,
                available_cash=balance,
            )
        except Exception:
            return Balance()

    def get_order_status(self, order_id: str) -> OrderStatus:
        """Look up a simulation order by ID."""
        for so in self._simulation_orders:
            if so.order_id == order_id:
                return OrderStatus(
                    order_id=so.order_id,
                    symbol=so.symbol,
                    action=so.action,
                    shares=so.shares,
                    price=so.price,
                    status=so.status,
                    filled_at=so.created_at,
                    message="模拟交易记录",
                )
        return OrderStatus(
            order_id=order_id,
            symbol="",
            action="",
            shares=0,
            price=0.0,
            status="not_found",
        )

    def submit_order(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        gate_request_id: str = "",
    ) -> OrderStatus:
        """Record a simulation order (no real execution)."""
        order_id = f"sim-{uuid.uuid4().hex[:8]}"
        sim = SimulationOrder(
            order_id=order_id,
            gate_request_id=gate_request_id,
            symbol=symbol,
            action=action,
            shares=shares,
            price=price,
        )
        self._simulation_orders.append(sim)
        logger.info(
            "Simulation order: %s %s %d @ %.2f (gate=%s)",
            action,
            symbol,
            shares,
            price,
            gate_request_id,
        )
        return OrderStatus(
            order_id=order_id,
            symbol=symbol,
            action=action,
            shares=shares,
            price=price,
            status="simulated",
            filled_at=sim.created_at,
            message="模拟交易已记录",
        )

    @property
    def mode(self) -> str:
        return "simulation"

    @staticmethod
    def _read_portfolio() -> dict[str, Any]:
        """Read from SQLite PortfolioStore (single source of truth)."""
        from src.web.services.portfolio_store import PortfolioStore

        try:
            store = PortfolioStore()
            return store.get_portfolio_data()
        except Exception:
            return {"positions": []}


class LiveBroker(BrokerInterface):
    """Stub for real broker integration.

    Requires:
    - config/broker.yaml: mode=live
    - Explicit user configuration
    - All trades must pass through ConfirmationGate with VERIFIED status

    NOT IMPLEMENTED — placeholder for future integration.
    """

    def __init__(self) -> None:
        logger.warning("LiveBroker instantiated — NOT IMPLEMENTED")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("LiveBroker not implemented")

    def get_balance(self) -> Balance:
        raise NotImplementedError("LiveBroker not implemented")

    def get_order_status(self, order_id: str) -> OrderStatus:
        raise NotImplementedError("LiveBroker not implemented")

    def submit_order(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        gate_request_id: str = "",
    ) -> OrderStatus:
        raise NotImplementedError("LiveBroker not implemented")

    @property
    def mode(self) -> str:
        return "live"


def create_broker() -> BrokerInterface:
    """Factory: create the appropriate broker based on config.

    Reads config/broker.yaml. Defaults to SimulationBroker.
    Supports modes: simulation, live, qmt.
    """
    try:
        cfg = load_config("broker")
    except Exception:
        cfg = {}

    mode = cfg.get("mode", "simulation")

    if mode == "qmt":
        try:
            from src.web.services.qmt_broker import QmtBroker

            return QmtBroker(config=cfg)
        except Exception as exc:
            logger.warning(
                "QmtBroker creation failed (%s), falling back to SimulationBroker",
                exc,
            )
            return SimulationBroker()

    if mode == "live":
        live_cfg = cfg.get("live", {})
        if not live_cfg.get("require_explicit_config", True):
            logger.warning("LiveBroker requested but require_explicit_config is false")
        return LiveBroker()

    return SimulationBroker()
