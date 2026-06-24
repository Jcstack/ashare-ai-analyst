"""Capital management service — transaction ledger with running balance.

Manages the user's capital lifecycle:
- Initial deposit and subsequent deposits/withdrawals
- Automatic settlement on trade execution (buy deducts, sell credits)
- A-share fee calculation (commission + stamp tax)
- Balance queries and transaction history

Balance is derived from the latest transaction's ``balance_after`` field,
making the ledger the single source of truth (no mutable balance column).
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger
from src.web.schemas.capital import (
    CapitalBalance,
    CapitalBreakdown,
    CapitalTransaction,
    PositionCapital,
)

logger = get_logger("web.capital_service")

_DB_PATH = Path("data/agent.db")

# ---------------------------------------------------------------------------
# A-share fee constants
# ---------------------------------------------------------------------------
COMMISSION_RATE = 0.0003  # 0.03%, both buy and sell
COMMISSION_MIN = 5.0  # minimum ¥5 per trade
STAMP_TAX_RATE = 0.001  # 0.1%, sell-only


def calculate_commission(amount: float) -> float:
    """Calculate broker commission for a trade amount."""
    return max(amount * COMMISSION_RATE, COMMISSION_MIN)


def calculate_stamp_tax(amount: float) -> float:
    """Calculate stamp tax (sell-only) for a trade amount."""
    return amount * STAMP_TAX_RATE


class CapitalService:
    """Transaction-ledger capital service backed by SQLite.

    Shares the same ``data/agent.db`` database as TradeService/AgentService.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Balance queries
    # ------------------------------------------------------------------

    def get_balance(self) -> float:
        """Return the current available cash balance.

        Reads ``balance_after`` from the most recent transaction.
        Returns 0.0 if no transactions exist.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT balance_after FROM capital_transactions "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else 0.0

    def get_balance_info(self) -> CapitalBalance:
        """Return balance with metadata."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT balance_after FROM capital_transactions "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM capital_transactions").fetchone()
            has_initial = conn.execute(
                "SELECT COUNT(*) FROM capital_transactions WHERE type = 'initial_deposit'"
            ).fetchone()
        return CapitalBalance(
            available_cash=row[0] if row else 0.0,
            total_transactions=count[0] if count else 0,
            has_initial_deposit=bool(has_initial and has_initial[0] > 0),
        )

    def get_breakdown(self) -> CapitalBreakdown:
        """Return full capital breakdown (cash + position values)."""
        balance_info = self.get_balance_info()
        cash = balance_info.available_cash

        # Read portfolio positions — market_value uses realtime prices when available
        positions = self._read_positions()
        position_value = sum(p.market_value for p in positions)
        total = cash + position_value
        utilization = position_value / total if total > 0 else 0.0

        return CapitalBreakdown(
            available_cash=round(cash, 2),
            position_value=round(position_value, 2),
            total_assets=round(total, 2),
            utilization_rate=round(utilization, 4),
            positions=positions,
            has_initial_deposit=balance_info.has_initial_deposit,
        )

    # ------------------------------------------------------------------
    # Deposits / Withdrawals
    # ------------------------------------------------------------------

    def deposit(self, amount: float, description: str = "") -> CapitalTransaction:
        """Record a capital deposit.

        First deposit is stored as ``initial_deposit``; subsequent ones as ``deposit``.
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")

        balance_info = self.get_balance_info()
        tx_type = (
            "initial_deposit" if not balance_info.has_initial_deposit else "deposit"
        )
        new_balance = balance_info.available_cash + amount

        tx = self._insert_transaction(
            tx_type=tx_type,
            amount=amount,
            balance_after=new_balance,
            description=description
            or ("初始入金" if tx_type == "initial_deposit" else "增资"),
        )
        logger.info(
            "Capital %s: +%.2f → balance %.2f",
            tx_type,
            amount,
            new_balance,
        )
        return tx

    def withdraw(self, amount: float, description: str = "") -> CapitalTransaction:
        """Record a capital withdrawal. Raises ValueError if insufficient balance."""
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")

        current = self.get_balance()
        if amount > current:
            raise ValueError(
                f"Insufficient balance: requested {amount:.2f}, available {current:.2f}"
            )

        new_balance = current - amount
        tx = self._insert_transaction(
            tx_type="withdrawal",
            amount=-amount,
            balance_after=new_balance,
            description=description or "减资",
        )
        logger.info("Capital withdrawal: -%.2f → balance %.2f", amount, new_balance)
        return tx

    # ------------------------------------------------------------------
    # Trade settlement
    # ------------------------------------------------------------------

    def record_trade_buy(
        self,
        trade_id: str,
        symbol: str,
        shares: int,
        price: float,
    ) -> CapitalTransaction:
        """Deduct capital for a buy trade (amount + commission)."""
        gross = shares * price
        commission = calculate_commission(gross)
        total_cost = gross + commission

        current = self.get_balance()
        if total_cost > current:
            raise ValueError(
                f"Insufficient capital for buy: need {total_cost:.2f} "
                f"(gross {gross:.2f} + commission {commission:.2f}), "
                f"available {current:.2f}"
            )

        new_balance = current - total_cost
        desc = f"买入 {symbol} {shares}股 @{price:.2f} (佣金{commission:.2f})"
        tx = self._insert_transaction(
            tx_type="trade_buy",
            amount=-total_cost,
            balance_after=new_balance,
            trade_id=trade_id,
            symbol=symbol,
            description=desc,
        )
        logger.info(
            "Capital buy settlement: %s -%s → balance %.2f",
            symbol,
            total_cost,
            new_balance,
        )
        return tx

    def record_trade_sell(
        self,
        trade_id: str,
        symbol: str,
        shares: int,
        price: float,
    ) -> CapitalTransaction:
        """Credit capital for a sell trade (amount - commission - stamp tax)."""
        gross = shares * price
        commission = calculate_commission(gross)
        stamp_tax = calculate_stamp_tax(gross)
        net_proceeds = gross - commission - stamp_tax

        current = self.get_balance()
        new_balance = current + net_proceeds
        desc = (
            f"卖出 {symbol} {shares}股 @{price:.2f} "
            f"(佣金{commission:.2f}, 印花税{stamp_tax:.2f})"
        )
        tx = self._insert_transaction(
            tx_type="trade_sell",
            amount=net_proceeds,
            balance_after=new_balance,
            trade_id=trade_id,
            symbol=symbol,
            description=desc,
        )
        logger.info(
            "Capital sell settlement: %s +%.2f → balance %.2f",
            symbol,
            net_proceeds,
            new_balance,
        )
        return tx

    # ------------------------------------------------------------------
    # Position liquidation (manual removal with capital recovery)
    # ------------------------------------------------------------------

    def record_position_liquidation(
        self,
        symbol: str,
        stock_name: str,
        shares: int,
        price: float,
    ) -> CapitalTransaction:
        """Recover capital when a position is manually cleared.

        Credits ``shares * price`` back to available cash without
        commission or stamp tax (this is not a real trade).
        """
        amount = round(shares * price, 2)
        current = self.get_balance()
        new_balance = current + amount
        desc = f"持仓清除 {stock_name}({symbol}) {shares}股 @{price:.2f}"
        tx = self._insert_transaction(
            tx_type="position_liquidation",
            amount=amount,
            balance_after=new_balance,
            symbol=symbol,
            description=desc,
        )
        logger.info(
            "Capital position liquidation: %s +%.2f → balance %.2f",
            symbol,
            amount,
            new_balance,
        )
        return tx

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(
        self,
        limit: int = 50,
        offset: int = 0,
        tx_type: str | None = None,
    ) -> list[CapitalTransaction]:
        """Query transaction history, optionally filtered by type."""
        if tx_type:
            query = (
                "SELECT * FROM capital_transactions WHERE type = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
            )
            params: tuple[Any, ...] = (tx_type, limit, offset)
        else:
            query = (
                "SELECT * FROM capital_transactions "
                "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
            )
            params = (limit, offset)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [_row_to_transaction(row) for row in rows]

    def get_transaction_count(self, tx_type: str | None = None) -> int:
        """Count total transactions, optionally filtered by type."""
        with self._connect() as conn:
            if tx_type:
                row = conn.execute(
                    "SELECT COUNT(*) FROM capital_transactions WHERE type = ?",
                    (tx_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM capital_transactions"
                ).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Migration from user_config
    # ------------------------------------------------------------------

    def maybe_migrate_from_config(self, user_config_service: Any) -> bool:
        """Migrate available_capital from UserConfigService if present.

        Uses the ``_migrations`` table to track completion so the migration
        is never re-run — even if the user later withdraws all capital.

        Returns:
            True if migration was performed.
        """
        migration_name = "capital_from_config"
        with self._connect() as conn:
            done = conn.execute(
                "SELECT 1 FROM _migrations WHERE name = ?", (migration_name,)
            ).fetchone()
            if done:
                return False

            # Upgrade path: existing DB already has transactions → set flag, skip import
            count = conn.execute(
                "SELECT COUNT(*) FROM capital_transactions"
            ).fetchone()[0]
            if count > 0:
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                    (migration_name, datetime.now(timezone.utc).isoformat()),
                )
                return False

        try:
            capital_str = user_config_service.get("available_capital")
            if not capital_str:
                # No source value — record migration as done
                with self._connect() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                        (migration_name, datetime.now(timezone.utc).isoformat()),
                    )
                return False

            amount = float(capital_str)
            if amount <= 0:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                        (migration_name, datetime.now(timezone.utc).isoformat()),
                    )
                return False

            self.deposit(amount, "从设置迁移的初始资金")
            user_config_service.delete("available_capital")
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                    (migration_name, datetime.now(timezone.utc).isoformat()),
                )
            logger.info("Migrated available_capital=%.2f from user_config", amount)
            return True
        except Exception:
            logger.warning("Failed to migrate available_capital", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_transaction(
        self,
        tx_type: str,
        amount: float,
        balance_after: float,
        trade_id: str | None = None,
        symbol: str | None = None,
        description: str = "",
    ) -> CapitalTransaction:
        """Insert a new transaction into the ledger."""
        now = datetime.now(timezone.utc).isoformat()
        tx_id = str(uuid.uuid4())

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO capital_transactions "
                "(id, type, amount, balance_after, trade_id, symbol, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tx_id,
                    tx_type,
                    round(amount, 2),
                    round(balance_after, 2),
                    trade_id,
                    symbol,
                    description,
                    now,
                ),
            )

        return CapitalTransaction(
            id=tx_id,
            type=tx_type,
            amount=round(amount, 2),
            balance_after=round(balance_after, 2),
            trade_id=trade_id,
            symbol=symbol,
            description=description,
            created_at=now,
        )

    @staticmethod
    def _read_positions() -> list[PositionCapital]:
        """Read portfolio positions from PortfolioStore (SQLite) for breakdown.

        Attempts to fetch real-time prices for accurate market_value;
        falls back to cost_price when real-time data is unavailable.
        """
        try:
            from src.web.services.portfolio_store import PortfolioStore

            store = PortfolioStore(capital_service=None)
            raw_positions = store.list_positions()
            if not raw_positions:
                return []

            # Try to get realtime prices for accurate market value
            realtime_prices: dict[str, float] = {}
            try:
                from src.data.realtime import RealtimeQuoteManager

                symbols = [
                    p.get("symbol", "") for p in raw_positions if p.get("symbol")
                ]
                if symbols:
                    mgr = RealtimeQuoteManager()
                    df = mgr.get_quotes(symbols)
                    if (
                        not df.empty
                        and "symbol" in df.columns
                        and "price" in df.columns
                    ):
                        for _, row in df.iterrows():
                            sym = row.get("symbol", "")
                            price = row.get("price")
                            if (
                                sym
                                and price is not None
                                and not (isinstance(price, float) and math.isnan(price))
                            ):
                                realtime_prices[sym] = float(price)
            except Exception:
                pass  # fall back to cost_price

            positions = []
            for p in raw_positions:
                shares = p.get("shares", 0)
                cost_price = p.get("cost_price", 0)
                symbol = p.get("symbol", "")
                current_price = realtime_prices.get(symbol, cost_price)
                positions.append(
                    PositionCapital(
                        symbol=symbol,
                        stock_name=p.get("name", ""),
                        shares=shares,
                        cost_price=cost_price,
                        market_value=round(shares * current_price, 2),
                        cost_basis=round(shares * cost_price, 2),
                    )
                )
            return positions
        except Exception:
            return []

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the shared SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables(self) -> None:
        """Create capital_transactions and _migrations tables if they don't exist."""
        with self._connect() as conn:
            # Flush stale WAL from previous container so _migrations flags
            # and user data survive Docker restarts (macOS bind-mount issue).
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capital_transactions (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    trade_id TEXT,
                    symbol TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _migrations (
                    name TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL
                )
                """
            )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _row_to_transaction(row: sqlite3.Row) -> CapitalTransaction:
    """Convert a SQLite Row to a CapitalTransaction model."""
    return CapitalTransaction(
        id=row["id"],
        type=row["type"],
        amount=row["amount"],
        balance_after=row["balance_after"],
        trade_id=row["trade_id"],
        symbol=row["symbol"],
        description=row["description"] or "",
        created_at=row["created_at"],
    )
