"""Canonical A-share market constants — single source of truth.

The lot size, commission / stamp-duty rates, max-position cap, and board daily
price limits were previously re-declared as literal defaults in several modules
(``trading/constraints``, ``strategy/base``, ``backtest/engine``,
``risk/position_sizer``, ``agent_loop/ashare_constraints``). That duplication is
a drift hazard. Import these instead of re-hardcoding the values.

Scope (#47): this consolidates the shared *constants*. Each module's board
*detection* logic and rule application still live locally — unifying those is a
deeper, behavior-sensitive follow-up tracked on the same issue.
"""

from __future__ import annotations

# Minimum tradable unit: 1 lot = 100 shares (1 手 = 100 股).
LOT_SIZE: int = 100

# Transaction costs.
COMMISSION_RATE: float = 0.0003  # brokerage commission (both sides)
STAMP_DUTY_RATE: float = 0.001  # stamp duty (sell side only)

# Default max weight for a single position.
MAX_SINGLE_POSITION: float = 0.30

# Daily price-limit magnitude by board, as a decimal fraction.
#   main board       ±10%
#   ChiNext / STAR   ±20%
#   BSE              ±30%
PRICE_LIMITS: dict[str, float] = {
    "main": 0.10,
    "chinext": 0.20,
    "star": 0.20,
    "bse": 0.30,
}

# Board code prefixes (6-digit A-share codes).
CHINEXT_PREFIXES: tuple[str, ...] = ("300", "301")
STAR_PREFIXES: tuple[str, ...] = ("688", "689")
