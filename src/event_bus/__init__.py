"""Redis Streams-based event bus for the Trading Agent OS.

Provides publish/subscribe infrastructure across seven event streams:
  events:market    - price spikes, volume anomalies
  events:news      - intelligence pipeline outputs
  events:regime    - sentiment/HMM state changes
  events:signal    - new signals detected
  events:portfolio - position changes, fills
  events:thesis    - thesis state changes
  events:risk      - risk limit breaches

Per PRD v50.0 Section 17.3.
"""

from src.event_bus.bus import EventBus
from src.event_bus import producers

__all__ = ["EventBus", "producers"]
