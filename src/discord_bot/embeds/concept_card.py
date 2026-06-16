"""Build Discord embed for concept board hot rankings."""

from __future__ import annotations

from typing import Any

import discord


def build_concept_embed(
    boards: list[Any],
    limit: int = 10,
) -> discord.Embed:
    """Build a concept board ranking embed.

    Args:
        boards: List of ``ConceptBoardItem`` dataclass instances or dicts.
        limit: Max items to show.
    """
    embed = discord.Embed(title="🧩 概念板块热度", color=0xFF9100)

    if not boards:
        embed.description = "概念板块数据暂不可用"
        return embed

    lines: list[str] = []
    for i, board in enumerate(boards[:limit], 1):
        # Support both dataclass and dict
        if isinstance(board, dict):
            name = board.get("name", "")
            pct = board.get("pct_change", 0)
            zt = board.get("zt_count", 0)
            up = board.get("up_count", 0)
            down = board.get("down_count", 0)
        else:
            name = getattr(board, "name", "")
            pct = getattr(board, "pct_change", 0)
            zt = getattr(board, "zt_count", 0)
            up = getattr(board, "up_count", 0)
            down = getattr(board, "down_count", 0)

        try:
            pct_val = float(pct)
            pct_str = f"{pct_val:+.2f}%"
            emoji = "🔴" if pct_val > 2 else "🟢" if pct_val < -2 else "⚪"
        except (TypeError, ValueError):
            pct_str = str(pct)
            emoji = "⚪"

        meta_parts: list[str] = []
        if zt:
            meta_parts.append(f"涨停{zt}")
        if up or down:
            meta_parts.append(f"↑{up} ↓{down}")
        meta = " · ".join(meta_parts)
        meta_str = f" ({meta})" if meta else ""

        lines.append(f"{emoji} **{i}.** {name} {pct_str}{meta_str}")

    embed.description = "\n".join(lines)
    embed.set_footer(text="概念板块 | A股分析师")
    return embed
