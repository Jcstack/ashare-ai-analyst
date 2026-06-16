"""User configuration persistence — SQLite key-value store.

Stores user preferences such as available capital, risk tolerance, etc.
Shares the same agent.db as AgentService and TradeService.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import get_logger
from src.web.schemas.user_config import (
    InvestmentStyleConfig,
    NotificationPrefs,
    UserFollows,
)

logger = get_logger("web.user_config_service")

_DB_PATH = Path("data/agent.db")
ALLOWED_KEYS = {
    "risk_tolerance",
    "follows",
    "notification_prefs",
    "investment_style",
    "investment_style_config",
}


class UserConfigService:
    """User configuration key-value store backed by SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_db()

    def get(self, key: str) -> str | None:
        """Get a config value by key."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM user_config WHERE key = ?",
                (key,),
            ).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        """Set a config value (upsert). Only allowed keys are accepted."""
        if key not in ALLOWED_KEYS:
            raise ValueError(f"Invalid config key: {key!r}. Allowed: {ALLOWED_KEYS}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_config (key, value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?",
                (key, value, now, value, now),
            )

    def get_all(self) -> dict[str, str]:
        """Get all config key-value pairs."""
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM user_config").fetchall()
        return {row[0]: row[1] for row in rows}

    def delete(self, key: str) -> bool:
        """Delete a config entry."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM user_config WHERE key = ?", (key,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # v20.0 Phase 4 — follows & notification preferences
    # ------------------------------------------------------------------

    def get_follows(self) -> dict:
        """Get user follows configuration.

        Returns the stored follows dict, or defaults from UserFollows schema.
        """
        raw = self.get("follows")
        if raw is None:
            return UserFollows().model_dump()
        try:
            data = json.loads(raw)
            return UserFollows(**data).model_dump()
        except (json.JSONDecodeError, ValueError):
            logger.warning("Corrupt follows config, returning defaults")
            return UserFollows().model_dump()

    def update_follows(self, follows: dict) -> dict:
        """Update user follows. Merges with existing and returns full config."""
        current = self.get_follows()
        current.update(follows)
        validated = UserFollows(**current)
        self.set("follows", json.dumps(validated.model_dump(), ensure_ascii=False))
        return validated.model_dump()

    def get_notification_prefs(self) -> dict:
        """Get notification preferences.

        Returns the stored prefs dict, or defaults from NotificationPrefs schema.
        """
        raw = self.get("notification_prefs")
        if raw is None:
            return NotificationPrefs().model_dump()
        try:
            data = json.loads(raw)
            return NotificationPrefs(**data).model_dump()
        except (json.JSONDecodeError, ValueError):
            logger.warning("Corrupt notification_prefs config, returning defaults")
            return NotificationPrefs().model_dump()

    def update_notification_prefs(self, prefs: dict) -> dict:
        """Update notification preferences. Merges with existing and returns full config."""
        current = self.get_notification_prefs()
        current.update(prefs)
        validated = NotificationPrefs(**current)
        self.set(
            "notification_prefs", json.dumps(validated.model_dump(), ensure_ascii=False)
        )
        return validated.model_dump()

    # ------------------------------------------------------------------
    # v28.0 — investment style config
    # ------------------------------------------------------------------

    def get_investment_style_config(self) -> dict:
        """Get full investment style configuration.

        Returns the stored config dict, or defaults from InvestmentStyleConfig schema.
        """
        raw = self.get("investment_style_config")
        if raw is None:
            return InvestmentStyleConfig().model_dump()
        try:
            data = json.loads(raw)
            return InvestmentStyleConfig(**data).model_dump()
        except (json.JSONDecodeError, ValueError):
            logger.warning("Corrupt investment_style_config, returning defaults")
            return InvestmentStyleConfig().model_dump()

    def update_investment_style_config(self, config: dict) -> dict:
        """Update investment style configuration. Merges with existing and returns full config."""
        current = self.get_investment_style_config()
        current.update(config)
        validated = InvestmentStyleConfig(**current)
        self.set(
            "investment_style_config",
            json.dumps(validated.model_dump(), ensure_ascii=False),
        )
        return validated.model_dump()

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self) -> None:
        """Create user_config table if it doesn't exist."""
        with self._connect() as conn:
            # Flush stale WAL from previous container (macOS Docker bind-mount).
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
