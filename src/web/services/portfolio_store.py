"""SQLite-backed portfolio position store.

Manages user portfolio positions in ``data/agent.db``, replacing the
previous ``data/processed/portfolio.json`` file.  Integrates with
:class:`CapitalService` for buy-side capital validation and sell-side
capital recovery.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.web.services.capital_service import CapitalService

logger = get_logger("web.portfolio_store")

_DB_PATH = Path("data/agent.db")


class PortfolioStore:
    """CRUD operations for the ``portfolio_positions`` table."""

    def __init__(
        self,
        capital_service: CapitalService | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._capital = capital_service
        self._db_path = db_path or _DB_PATH
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_positions(self) -> list[dict]:
        """Return all positions ordered by ``created_at``."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM portfolio_positions ORDER BY created_at"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_position(self, position_id: str) -> dict | None:
        """Return a single position by ID, or None."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM portfolio_positions WHERE id = ?",
                (position_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_portfolio_data(self) -> dict:
        """Return portfolio in the legacy ``{version, updatedAt, positions}`` format."""
        positions = self.list_positions()
        # Convert to camelCase keys matching the frontend Portfolio type
        camel_positions = []
        for p in positions:
            camel_positions.append(
                {
                    "id": p["id"],
                    "symbol": p["symbol"],
                    "name": p["name"],
                    "board": p["board"],
                    "costPrice": p["cost_price"],
                    "shares": p["shares"],
                    "buyDate": p["buy_date"],
                    "note": p["note"],
                }
            )
        updated_at = ""
        if positions:
            updated_at = max(p["updated_at"] for p in positions)
        return {
            "version": 1,
            "updatedAt": updated_at,
            "positions": camel_positions,
        }

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_position(
        self,
        symbol: str,
        name: str,
        board: str = "main",
        cost_price: float = 0.0,
        shares: int = 0,
        buy_date: str = "",
        note: str = "",
        validate_capital: bool = True,
    ) -> dict:
        """Add a new position. Optionally validates and deducts capital.

        Raises:
            ValueError: If ``validate_capital`` is True and the user has
                insufficient cash to cover ``shares * cost_price + commission``.
        """
        if validate_capital and self._capital is not None:
            from src.web.services.capital_service import calculate_commission

            gross = shares * cost_price
            commission = calculate_commission(gross)
            total_cost = gross + commission
            balance = self._capital.get_balance()
            if total_cost > balance:
                raise ValueError(
                    f"资金不足：需要 {total_cost:.2f} 元"
                    f"（本金 {gross:.2f} + 佣金 {commission:.2f}），"
                    f"可用 {balance:.2f} 元"
                )
            # Deduct capital
            trade_id = str(uuid.uuid4())
            self._capital.record_trade_buy(
                trade_id=trade_id,
                symbol=symbol,
                shares=shares,
                price=cost_price,
            )

        now = datetime.now(timezone.utc).isoformat()
        position_id = f"{symbol}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO portfolio_positions "
                "(id, symbol, name, board, cost_price, shares, buy_date, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    position_id,
                    symbol,
                    name,
                    board,
                    round(cost_price, 2),
                    shares,
                    buy_date,
                    note,
                    now,
                    now,
                ),
            )

        logger.info(
            "Position added: %s %s %d shares @ %.2f",
            position_id,
            symbol,
            shares,
            cost_price,
        )
        return self.get_position(position_id)  # type: ignore[return-value]

    def update_position(self, position_id: str, updates: dict) -> dict | None:
        """Update an existing position. Returns the updated position or None."""
        existing = self.get_position(position_id)
        if not existing:
            return None

        allowed = {
            "symbol",
            "name",
            "board",
            "cost_price",
            "shares",
            "buy_date",
            "note",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return existing

        now = datetime.now(timezone.utc).isoformat()
        filtered["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [position_id]

        with self._connect() as conn:
            conn.execute(
                f"UPDATE portfolio_positions SET {set_clause} WHERE id = ?",
                values,
            )

        logger.info("Position updated: %s", position_id)
        return self.get_position(position_id)

    def remove_position(self, position_id: str) -> bool:
        """Remove a position by ID. Returns True if deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM portfolio_positions WHERE id = ?",
                (position_id,),
            )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Position removed: %s", position_id)
        return deleted

    def liquidate_position(self, position_id: str, current_price: float) -> dict:
        """Liquidate a position: credit capital and delete the row.

        Returns the capital transaction dict.

        Raises:
            ValueError: If the position does not exist.
        """
        pos = self.get_position(position_id)
        if not pos:
            raise ValueError(f"Position not found: {position_id}")

        tx_data: dict = {}
        if self._capital is not None:
            tx = self._capital.record_position_liquidation(
                symbol=pos["symbol"],
                stock_name=pos["name"],
                shares=pos["shares"],
                price=current_price,
            )
            tx_data = tx.model_dump()

        self.remove_position(position_id)
        logger.info(
            "Position liquidated: %s (%s) %d shares @ %.2f",
            position_id,
            pos["symbol"],
            pos["shares"],
            current_price,
        )
        return tx_data

    def save_portfolio_data(self, data: dict) -> None:
        """Full replacement from legacy ``{version, updatedAt, positions}`` format.

        Used by the ``PUT /portfolio`` endpoint during the transition period.
        """
        now = datetime.now(timezone.utc).isoformat()
        positions = data.get("positions", [])

        with self._connect() as conn:
            conn.execute("DELETE FROM portfolio_positions")
            for p in positions:
                conn.execute(
                    "INSERT INTO portfolio_positions "
                    "(id, symbol, name, board, cost_price, shares, buy_date, note, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        p.get(
                            "id",
                            f"{p.get('symbol', 'unk')}-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
                        ),
                        p.get("symbol", ""),
                        p.get("name", ""),
                        p.get("board", "main"),
                        round(float(p.get("costPrice", p.get("cost_price", 0))), 2),
                        int(p.get("shares", 0)),
                        p.get("buyDate", p.get("buy_date", "")),
                        p.get("note", ""),
                        now,
                        now,
                    ),
                )

        logger.info("Portfolio bulk-saved: %d positions", len(positions))

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def maybe_migrate_from_json(self) -> bool:
        """One-time migration from ``data/processed/portfolio.json``.

        Uses the ``_migrations`` table to track completion so the migration
        is never re-run — even if the user later clears all positions.

        Returns True if migration was performed.
        """
        migration_name = "portfolio_from_json"
        with self._connect() as conn:
            done = conn.execute(
                "SELECT 1 FROM _migrations WHERE name = ?", (migration_name,)
            ).fetchone()
            if done:
                return False

            # Upgrade path: existing DB already has data → set flag, skip import
            count = conn.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[
                0
            ]
            if count > 0:
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                    (migration_name, datetime.now(timezone.utc).isoformat()),
                )
                return False

        try:
            from src.utils.config import get_data_dir

            path = get_data_dir("processed") / "portfolio.json"
            if not path.exists():
                # No source file — record migration as done to avoid future checks
                with self._connect() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                        (migration_name, datetime.now(timezone.utc).isoformat()),
                    )
                return False

            data = json.loads(path.read_text("utf-8"))
            positions = data.get("positions", [])

            if positions:
                self.save_portfolio_data(data)
                logger.info("Migrated %d positions from portfolio.json", len(positions))

            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                    (migration_name, datetime.now(timezone.utc).isoformat()),
                )
            return bool(positions)
        except Exception:
            logger.warning("Failed to migrate portfolio from JSON", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a SQLite Row to a plain dict."""
        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "name": row["name"],
            "board": row["board"],
            "cost_price": row["cost_price"],
            "shares": row["shares"],
            "buy_date": row["buy_date"],
            "note": row["note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the shared SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables(self) -> None:
        """Create the ``portfolio_positions`` and ``_migrations`` tables if they don't exist."""
        with self._connect() as conn:
            # Flush stale WAL from previous container so _migrations flags
            # and user data survive Docker restarts (macOS bind-mount issue).
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    board TEXT NOT NULL DEFAULT 'main',
                    cost_price REAL NOT NULL,
                    shares INTEGER NOT NULL,
                    buy_date TEXT NOT NULL DEFAULT '',
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_positions_symbol "
                "ON portfolio_positions(symbol)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _migrations (
                    name TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL
                )
                """
            )
