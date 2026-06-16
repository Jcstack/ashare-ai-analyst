"""Trade service — execute, record, and query simulated trades.

Manages the trade lifecycle:
- Agent-recommended trades (from TradeDecisionCard accept/reject)
- Manual trades (user-entered for portfolio sync)
- Trade history queries
- Recommendation decision tracking
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger
from src.web.schemas.chat import AgentRecommendation, Trade, TradingProfile

logger = get_logger("web.trade_service")

_DB_PATH = Path("data/agent.db")


class TradeService:
    """Service for trade execution and history management.

    Shares the same SQLite database as AgentService (data/agent.db),
    operating on the `trades` and `recommendations` tables.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        capital_service: Any | None = None,
        portfolio_store: Any | None = None,
    ) -> None:
        self._db_path = db_path or _DB_PATH
        self._capital_service = capital_service
        self._portfolio_store = portfolio_store
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    def execute_trade(
        self,
        symbol: str,
        stock_name: str,
        action: str,
        shares: int,
        price: float,
        reasoning: str = "",
        thread_id: str | None = None,
        recommendation_id: str | None = None,
        decision_feedback: str | None = None,
        gate_request_id: str | None = None,
    ) -> Trade:
        """Execute a simulated trade and persist the record.

        Args:
            gate_request_id: If provided, links trade to a ConfirmationGate
                request. The gate must be in USER_CONFIRMED stage.

        Returns:
            The created Trade record with status='executed'.
        """
        now = _now_iso()
        trade = Trade(
            id=str(uuid.uuid4()),
            symbol=symbol,
            stock_name=stock_name,
            action=action,
            shares=shares,
            price=price,
            amount=round(shares * price, 2),
            source="agent" if recommendation_id else "manual",
            reasoning=reasoning,
            agent_recommendation_id=recommendation_id,
            decision_feedback=decision_feedback,
            status="executed",
            executed_at=now,
            created_at=now,
            thread_id=thread_id,
            gate_request_id=gate_request_id,
        )

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trades "
                "(id, thread_id, symbol, stock_name, action, shares, price, "
                "amount, source, reasoning, agent_recommendation_id, "
                "decision_feedback, status, executed_at, created_at, "
                "gate_request_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trade.id,
                    trade.thread_id,
                    trade.symbol,
                    trade.stock_name,
                    trade.action,
                    trade.shares,
                    trade.price,
                    trade.amount,
                    trade.source,
                    trade.reasoning,
                    trade.agent_recommendation_id,
                    trade.decision_feedback,
                    trade.status,
                    trade.executed_at,
                    trade.created_at,
                    trade.gate_request_id,
                ),
            )

        logger.info(
            "Trade executed: %s %s %d shares @ %.2f (%s)",
            action,
            symbol,
            shares,
            price,
            trade.id,
        )

        # Note: portfolio.json sync removed — SQLite PortfolioStore is the
        # single source of truth.  See I-030 resolution.

        # Settle capital (deduct/credit)
        self._settle_capital(trade.id, symbol, action, shares, price)

        # Sync portfolio positions
        self._sync_position(symbol, stock_name, action, shares, price)

        return trade

    def record_manual_trade(
        self,
        symbol: str,
        stock_name: str,
        action: str,
        shares: int,
        price: float,
        reasoning: str = "",
        recommendation_id: str | None = None,
    ) -> Trade:
        """Record a manually-entered trade for portfolio sync.

        Returns:
            The created Trade record.
        """
        now = _now_iso()
        trade = Trade(
            id=str(uuid.uuid4()),
            symbol=symbol,
            stock_name=stock_name,
            action=action,
            shares=shares,
            price=price,
            amount=round(shares * price, 2),
            source="manual",
            reasoning=reasoning,
            agent_recommendation_id=recommendation_id,
            status="executed",
            executed_at=now,
            created_at=now,
        )

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trades "
                "(id, thread_id, symbol, stock_name, action, shares, price, "
                "amount, source, reasoning, agent_recommendation_id, "
                "decision_feedback, status, executed_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trade.id,
                    None,
                    trade.symbol,
                    trade.stock_name,
                    trade.action,
                    trade.shares,
                    trade.price,
                    trade.amount,
                    trade.source,
                    trade.reasoning,
                    trade.agent_recommendation_id,
                    None,
                    trade.status,
                    trade.executed_at,
                    trade.created_at,
                ),
            )

        logger.info(
            "Manual trade recorded: %s %s %d shares @ %.2f",
            action,
            symbol,
            shares,
            price,
        )

        # Settle capital (deduct/credit)
        self._settle_capital(trade.id, symbol, action, shares, price)

        # Sync portfolio positions
        self._sync_position(symbol, stock_name, action, shares, price)

        return trade

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------

    def get_trade_history(
        self,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Trade]:
        """Query trade history, optionally filtered by symbol.

        Returns:
            List of Trade records ordered by created_at desc.
        """
        if symbol:
            query = (
                "SELECT * FROM trades WHERE symbol = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?"
            )
            params: tuple[Any, ...] = (symbol, limit, offset)
        else:
            query = "SELECT * FROM trades ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params = (limit, offset)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [_row_to_trade(row) for row in rows]

    def get_trade_count(self, symbol: str | None = None) -> int:
        """Count total trades, optionally filtered by symbol."""
        with self._connect() as conn:
            if symbol:
                row = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE symbol = ?", (symbol,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Recommendation decisions
    # ------------------------------------------------------------------

    def save_recommendation(
        self,
        thread_id: str,
        symbol: str,
        action: str,
        confidence: float,
        reasoning: str,
        risk_warnings: list[str] | None = None,
        stop_loss: float | None = None,
    ) -> AgentRecommendation:
        """Save an AI-generated recommendation for later accept/reject.

        Returns:
            The created AgentRecommendation record.
        """
        now = _now_iso()
        rec = AgentRecommendation(
            id=str(uuid.uuid4()),
            thread_id=thread_id,
            symbol=symbol,
            action=action,
            confidence=confidence,
            reasoning=reasoning,
            risk_warnings=risk_warnings or [],
            stop_loss=stop_loss,
            user_decision="pending",
            created_at=now,
        )

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO recommendations "
                "(id, thread_id, symbol, action, confidence, reasoning, "
                "risk_warnings, stop_loss, user_decision, user_feedback, "
                "actual_outcome, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.id,
                    rec.thread_id,
                    rec.symbol,
                    rec.action,
                    rec.confidence,
                    rec.reasoning,
                    json.dumps(rec.risk_warnings, ensure_ascii=False),
                    rec.stop_loss,
                    rec.user_decision,
                    None,
                    None,
                    rec.created_at,
                ),
            )

        return rec

    def update_recommendation_decision(
        self,
        recommendation_id: str,
        decision: str,
        feedback: str | None = None,
    ) -> bool:
        """Update a recommendation with the user's accept/reject decision.

        Returns:
            True if the recommendation was found and updated.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE recommendations SET user_decision = ?, user_feedback = ? "
                "WHERE id = ?",
                (decision, feedback, recommendation_id),
            )
        return cursor.rowcount > 0

    def get_recommendation(self, recommendation_id: str) -> AgentRecommendation | None:
        """Load a single recommendation by ID."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM recommendations WHERE id = ?",
                (recommendation_id,),
            ).fetchone()

        if not row:
            return None
        return _row_to_recommendation(row)

    def get_recommendations(
        self,
        thread_id: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[AgentRecommendation]:
        """List recommendations, optionally filtered by thread or symbol."""
        conditions: list[str] = []
        params: list[Any] = []

        if thread_id:
            conditions.append("thread_id = ?")
            params.append(thread_id)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM recommendations{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [_row_to_recommendation(row) for row in rows]

    # ------------------------------------------------------------------
    # Trading profile
    # ------------------------------------------------------------------

    def compute_trading_profile(self) -> TradingProfile:
        """Compute a trading behavior profile from trade history.

        Returns:
            TradingProfile with aggregated stats including win rate,
            average holding days, preferred sectors, and common biases.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status = 'executed'"
            ).fetchone()[0]

            if total == 0:
                return TradingProfile(last_updated=_now_iso())

            # Agent adoption rate
            agent_count = conn.execute(
                "SELECT COUNT(*) FROM recommendations WHERE user_decision = 'accepted'"
            ).fetchone()[0]
            total_recs = conn.execute(
                "SELECT COUNT(*) FROM recommendations "
                "WHERE user_decision IN ('accepted', 'rejected')"
            ).fetchone()[0]
            adoption_rate = agent_count / total_recs if total_recs > 0 else 0.0

            # Action distribution for risk tolerance inference
            buy_count = conn.execute(
                "SELECT COUNT(*) FROM trades "
                "WHERE action IN ('buy', 'add') AND status = 'executed'"
            ).fetchone()[0]
            sell_count = conn.execute(
                "SELECT COUNT(*) FROM trades "
                "WHERE action IN ('sell', 'reduce') AND status = 'executed'"
            ).fetchone()[0]

            # Infer risk tolerance from buy/sell ratio
            if total < 5:
                risk_tolerance = "moderate"
            elif buy_count > sell_count * 2:
                risk_tolerance = "aggressive"
            elif sell_count > buy_count * 2:
                risk_tolerance = "conservative"
            else:
                risk_tolerance = "moderate"

            # Win rate + avg holding days via FIFO buy-sell pairing
            win_rate, avg_holding_days = self._compute_win_rate_and_holding(conn)

            # Preferred sectors from trade symbol frequency
            preferred_sectors = self._compute_preferred_sectors(conn)

            # Common biases from trade patterns
            common_biases = self._compute_biases(
                conn, total, buy_count, sell_count, adoption_rate
            )

        return TradingProfile(
            total_trades=total,
            win_rate=round(win_rate, 2),
            avg_holding_days=round(avg_holding_days, 1),
            risk_tolerance=risk_tolerance,
            common_biases=common_biases,
            preferred_sectors=preferred_sectors,
            agent_adoption_rate=round(adoption_rate, 2),
            last_updated=_now_iso(),
        )

    @staticmethod
    def _compute_win_rate_and_holding(
        conn: sqlite3.Connection,
    ) -> tuple[float, float]:
        """Pair buys with sells (FIFO) to compute win rate and holding days.

        Returns:
            Tuple of (win_rate, avg_holding_days). Both 0.0 if no pairs.
        """
        # Get all executed trades per symbol, ordered by time
        rows = conn.execute(
            "SELECT symbol, action, price, executed_at FROM trades "
            "WHERE status = 'executed' ORDER BY executed_at ASC"
        ).fetchall()

        # Group buys per symbol into FIFO queues
        buy_queues: dict[str, list[tuple[float, str]]] = {}  # symbol → [(price, date)]
        profitable = 0
        total_paired = 0
        total_holding_days = 0.0

        for row in rows:
            symbol = row["symbol"]
            action = row["action"]
            price = row["price"]
            executed_at = row["executed_at"]

            if action in ("buy", "add"):
                buy_queues.setdefault(symbol, []).append((price, executed_at))
            elif action in ("sell", "reduce") and buy_queues.get(symbol):
                buy_price, buy_date = buy_queues[symbol].pop(0)
                total_paired += 1
                if price > buy_price:
                    profitable += 1
                # Compute holding days
                days = _days_between(buy_date, executed_at)
                if days is not None:
                    total_holding_days += days

        if total_paired == 0:
            return 0.0, 0.0

        win_rate = profitable / total_paired
        avg_holding = total_holding_days / total_paired
        return win_rate, avg_holding

    @staticmethod
    def _compute_preferred_sectors(conn: sqlite3.Connection) -> list[str]:
        """Extract top 3 sectors from trade symbol frequency.

        Maps stock symbols to sectors using StockRegistry. Falls back to
        board name if registry unavailable.
        """
        rows = conn.execute(
            "SELECT symbol, COUNT(*) as cnt FROM trades "
            "WHERE status = 'executed' GROUP BY symbol ORDER BY cnt DESC"
        ).fetchall()

        if not rows:
            return []

        # Try to map symbols to sectors via StockRegistry
        sector_counts: dict[str, int] = {}
        try:
            from src.web.dependencies import get_stock_registry

            registry = get_stock_registry()
            for row in rows:
                info = registry.get_stock_info(row["symbol"])
                sector = (info or {}).get("industry", "")
                if sector:
                    sector_counts[sector] = sector_counts.get(sector, 0) + row["cnt"]
        except Exception:
            pass

        # Fallback: if no sectors found via registry, group by board type
        if not sector_counts:
            for row in rows:
                board = _detect_board(row["symbol"])
                sector_counts[board] = sector_counts.get(board, 0) + row["cnt"]

        sorted_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_sectors[:3]]

    @staticmethod
    def _compute_biases(
        conn: sqlite3.Connection,
        total: int,
        buy_count: int,
        sell_count: int,
        adoption_rate: float,
    ) -> list[str]:
        """Detect common trading biases from trade patterns.

        Rules (no external price data needed):
        - "频繁交易": >10 trades in last 30 days
        - "过度集中": >50% trades in top 1 symbol
        - "追涨倾向": >70% of trades are buys
        - "偏好观望": agent adoption rate < 30%
        """
        biases: list[str] = []

        # Rule 1: Overtrading — >10 trades in 30 days
        from datetime import timedelta

        cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent_count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE status = 'executed' AND created_at >= ?",
            (cutoff_30d,),
        ).fetchone()[0]
        if recent_count > 10:
            biases.append("频繁交易")

        # Rule 2: Concentration — >50% trades in top 1 symbol
        if total >= 5:
            top_symbol_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades "
                "WHERE status = 'executed' GROUP BY symbol "
                "ORDER BY cnt DESC LIMIT 1"
            ).fetchone()
            if top_symbol_count and top_symbol_count[0] > total * 0.5:
                biases.append("过度集中")

        # Rule 3: Chasing tendency — >70% buys
        if total >= 5 and buy_count > total * 0.7:
            biases.append("追涨倾向")

        # Rule 4: Low adoption — agent adoption rate < 30%
        if adoption_rate < 0.3 and total >= 5:
            biases.append("偏好观望")

        return biases

    # ------------------------------------------------------------------
    # Capital settlement
    # ------------------------------------------------------------------

    def _settle_capital(
        self,
        trade_id: str,
        symbol: str,
        action: str,
        shares: int,
        price: float,
    ) -> None:
        """Settle capital after trade execution (fire-and-forget)."""
        if not self._capital_service:
            return
        try:
            if action in ("buy", "add"):
                self._capital_service.record_trade_buy(trade_id, symbol, shares, price)
            elif action in ("sell", "reduce"):
                self._capital_service.record_trade_sell(trade_id, symbol, shares, price)
        except Exception:
            logger.warning(
                "Capital settlement failed for trade %s", trade_id, exc_info=True
            )

    # ------------------------------------------------------------------
    # Position sync (SQLite PortfolioStore)
    # ------------------------------------------------------------------

    def _sync_position(
        self,
        symbol: str,
        stock_name: str,
        action: str,
        shares: int,
        price: float,
    ) -> None:
        """After trade execution, atomically update portfolio_positions via PortfolioStore."""
        if not self._portfolio_store:
            return
        try:
            existing = self._find_position_by_symbol(symbol)

            if action in ("buy", "add"):
                if existing:
                    # Weighted average cost + accumulate shares
                    old_shares = existing["shares"]
                    old_cost = existing["cost_price"]
                    new_total = old_shares + shares
                    new_cost = (old_cost * old_shares + price * shares) / new_total
                    self._portfolio_store.update_position(
                        existing["id"],
                        {"shares": new_total, "cost_price": round(new_cost, 2)},
                    )
                else:
                    # New position — capital already settled by _settle_capital
                    self._portfolio_store.add_position(
                        symbol=symbol,
                        name=stock_name,
                        board=_detect_board(symbol),
                        cost_price=price,
                        shares=shares,
                        buy_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        validate_capital=False,
                    )
            elif action in ("sell", "reduce"):
                if existing:
                    remaining = existing["shares"] - shares
                    if remaining <= 0:
                        self._portfolio_store.remove_position(existing["id"])
                    else:
                        self._portfolio_store.update_position(
                            existing["id"],
                            {"shares": remaining},
                        )
        except Exception:
            logger.warning(
                "Position sync failed for %s %s", action, symbol, exc_info=True
            )

    def _find_position_by_symbol(self, symbol: str) -> dict | None:
        """Find an existing portfolio position by stock symbol."""
        if not self._portfolio_store:
            return None
        for pos in self._portfolio_store.list_positions():
            if pos["symbol"] == symbol:
                return pos
        return None

    # ------------------------------------------------------------------
    # Legacy portfolio.json sync (deprecated)
    # ------------------------------------------------------------------

    def _sync_portfolio(
        self,
        symbol: str,
        stock_name: str,
        action: str,
        shares: int,
        price: float,
    ) -> None:
        """After trade execution, update data/processed/portfolio.json."""
        from src.utils.config import get_data_dir

        path = get_data_dir("processed") / "portfolio.json"
        data: dict[str, Any] = {"version": 1, "updatedAt": "", "positions": []}
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        positions: list[dict[str, Any]] = data.get("positions", [])
        existing = next((p for p in positions if p.get("symbol") == symbol), None)

        if action in ("buy", "add"):
            if existing:
                total = existing.get("shares", 0) + shares
                old_cost = existing.get("costPrice", 0)
                old_shares = existing.get("shares", 0)
                new_cost = (old_cost * old_shares + price * shares) / total
                existing["shares"] = total
                existing["costPrice"] = round(new_cost, 2)
            else:
                positions.append(
                    {
                        "id": str(uuid.uuid4()),
                        "symbol": symbol,
                        "name": stock_name,
                        "board": _detect_board(symbol),
                        "costPrice": price,
                        "shares": shares,
                        "buyDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "note": "",
                    }
                )
        elif action in ("sell", "reduce"):
            if existing:
                if shares >= existing.get("shares", 0):
                    positions.remove(existing)
                else:
                    existing["shares"] = existing.get("shares", 0) - shares

        data["positions"] = positions
        data["updatedAt"] = _now_iso()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    # ------------------------------------------------------------------
    # Database internals
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the shared SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables(self) -> None:
        """Ensure trades and recommendations tables exist.

        These tables are also created by AgentService._ensure_db(),
        but we create them here too for standalone usage.
        """
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    symbol TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    source TEXT NOT NULL,
                    reasoning TEXT,
                    agent_recommendation_id TEXT,
                    decision_feedback TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    executed_at TEXT,
                    created_at TEXT NOT NULL,
                    gate_request_id TEXT
                );

                CREATE TABLE IF NOT EXISTS recommendations (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT NOT NULL,
                    risk_warnings TEXT,
                    stop_loss REAL,
                    user_decision TEXT DEFAULT 'pending',
                    user_feedback TEXT,
                    actual_outcome TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_trade(row: sqlite3.Row) -> Trade:
    """Convert a SQLite Row to a Trade model."""
    # gate_request_id may not exist in older schemas
    gate_id = None
    try:
        gate_id = row["gate_request_id"]
    except (IndexError, KeyError):
        pass

    return Trade(
        id=row["id"],
        symbol=row["symbol"],
        stock_name=row["stock_name"],
        action=row["action"],
        shares=row["shares"],
        price=row["price"],
        amount=row["amount"],
        source=row["source"],
        reasoning=row["reasoning"] or "",
        agent_recommendation_id=row["agent_recommendation_id"],
        decision_feedback=row["decision_feedback"],
        status=row["status"],
        executed_at=row["executed_at"],
        created_at=row["created_at"],
        thread_id=row["thread_id"],
        gate_request_id=gate_id,
    )


def _detect_board(symbol: str) -> str:
    """Detect stock board from symbol prefix."""
    if symbol.startswith("688"):
        return "科创板"
    if symbol.startswith("300") or symbol.startswith("301"):
        return "创业板"
    if symbol.startswith("60"):
        return "沪主板"
    if symbol.startswith("00"):
        return "深主板"
    return "其他"


def _days_between(date_str1: str, date_str2: str) -> float | None:
    """Compute days between two ISO date strings. Returns None on parse failure."""
    try:
        d1 = datetime.fromisoformat(date_str1)
        d2 = datetime.fromisoformat(date_str2)
        return abs((d2 - d1).total_seconds()) / 86400
    except (ValueError, TypeError):
        return None


def _row_to_recommendation(row: sqlite3.Row) -> AgentRecommendation:
    """Convert a SQLite Row to an AgentRecommendation model."""
    risk_warnings: list[str] = []
    if row["risk_warnings"]:
        try:
            risk_warnings = json.loads(row["risk_warnings"])
        except (json.JSONDecodeError, TypeError):
            pass

    actual_outcome: dict[str, Any] | None = None
    if row["actual_outcome"]:
        try:
            actual_outcome = json.loads(row["actual_outcome"])
        except (json.JSONDecodeError, TypeError):
            pass

    return AgentRecommendation(
        id=row["id"],
        thread_id=row["thread_id"],
        symbol=row["symbol"],
        action=row["action"],
        confidence=row["confidence"],
        reasoning=row["reasoning"],
        risk_warnings=risk_warnings,
        stop_loss=row["stop_loss"],
        user_decision=row["user_decision"] or "pending",
        user_feedback=row["user_feedback"],
        actual_outcome=actual_outcome,
        created_at=row["created_at"],
    )
