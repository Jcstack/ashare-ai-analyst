"""Always-on investment daemon — ``python -m openclaw.daemon``.

Persistent asyncio process that replaces cron-based heartbeat with
continuous Redis Streams event listening and scheduled missions.
"""

from __future__ import annotations
