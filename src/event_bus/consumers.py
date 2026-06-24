"""Consumer group definitions for the Trading Agent OS event bus.

Per PRD v50.0 §17.3: each subsystem subscribes to relevant event streams
via named consumer groups for reliable, independent consumption.

Consumer groups and their stream subscriptions:

  signal_engine    - market + news events -> detect new trading signals
  portfolio_engine - signal + portfolio + regime -> manage positions
  risk_engine      - portfolio + market + regime -> monitor risk limits
  execution_team   - signal + risk -> execute approved trades
  evaluation_team  - portfolio + thesis -> track outcomes
  notification     - signal + risk + regime -> push alerts to users
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("event_bus.consumers")


@dataclass(frozen=True)
class ConsumerGroupDef:
    """Definition of a consumer group and its stream subscriptions."""

    name: str
    streams: list[str] = field(default_factory=list)
    description: str = ""


# Static definitions matching PRD §17.3 architecture
CONSUMER_GROUPS: list[ConsumerGroupDef] = [
    ConsumerGroupDef(
        name="signal_engine",
        streams=["events:market", "events:news"],
        description="Detects trading signals from market data and news events.",
    ),
    ConsumerGroupDef(
        name="portfolio_engine",
        streams=["events:signal", "events:portfolio", "events:regime"],
        description="Manages portfolio state from signals, fills, and regime changes.",
    ),
    ConsumerGroupDef(
        name="risk_engine",
        streams=["events:portfolio", "events:market", "events:regime"],
        description="Monitors risk limits from portfolio, market, and regime events.",
    ),
    ConsumerGroupDef(
        name="execution_team",
        streams=["events:signal", "events:risk"],
        description="Executes approved trades after risk clearance.",
    ),
    ConsumerGroupDef(
        name="evaluation_team",
        streams=["events:portfolio", "events:thesis"],
        description="Tracks trade outcomes and thesis lifecycle.",
    ),
    ConsumerGroupDef(
        name="notification",
        streams=["events:signal", "events:risk", "events:regime"],
        description="Pushes alerts to users via Discord and web UI.",
    ),
]


def get_consumer_groups_from_config(
    config_name: str = "event_bus",
) -> list[ConsumerGroupDef]:
    """Load consumer group definitions from YAML config.

    Falls back to static ``CONSUMER_GROUPS`` if config is missing the key.

    Args:
        config_name: Config file name (without .yaml extension).

    Returns:
        List of ConsumerGroupDef instances.
    """
    try:
        config = load_config(config_name)
    except FileNotFoundError:
        logger.warning("Config %s not found, using static consumer groups", config_name)
        return list(CONSUMER_GROUPS)

    raw_groups = config.get("consumer_groups", {})
    if not raw_groups:
        return list(CONSUMER_GROUPS)

    groups = []
    for name, streams in raw_groups.items():
        groups.append(
            ConsumerGroupDef(
                name=name,
                streams=streams if isinstance(streams, list) else [],
            )
        )
    return groups


def ensure_all_consumer_groups(bus: "EventBus") -> None:  # noqa: F821
    """Create all consumer groups on the event bus.

    Idempotent — skips groups that already exist.

    Args:
        bus: An EventBus instance.
    """
    from src.event_bus.bus import EventBus  # avoid circular import at module level

    if not isinstance(bus, EventBus):
        raise TypeError(f"Expected EventBus, got {type(bus)}")

    groups = get_consumer_groups_from_config()
    for group_def in groups:
        for stream in group_def.streams:
            bus.ensure_consumer_group(stream, group_def.name)
    logger.info("Ensured %d consumer groups across all streams", len(groups))
