"""Discord bot package — A股分析师移动指挥中心."""

from __future__ import annotations

# Discord message character limit (with small safety margin)
_MSG_LIMIT = 1990


def split_message(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    """Split *text* into chunks that each fit within Discord's 2000-char limit.

    Splitting priority: paragraph boundary (``\\n\\n``) → line boundary
    (``\\n``) → hard cut.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Try paragraph boundary first
        cut = remaining.rfind("\n\n", 0, limit)
        if cut > limit // 4:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 2 :]  # skip the \n\n
            continue

        # Try line boundary
        cut = remaining.rfind("\n", 0, limit)
        if cut > limit // 4:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 1 :]
            continue

        # Hard cut at limit
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]

    return chunks
