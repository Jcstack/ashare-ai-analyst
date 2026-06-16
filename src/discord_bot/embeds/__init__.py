"""Discord embed builder utilities."""

from __future__ import annotations

import discord
from src.utils.logger import get_logger

logger = get_logger("discord.embeds")


def split_embed_fields(
    embed: discord.Embed, max_fields: int = 20
) -> list[discord.Embed]:
    """Split an embed into multiple embeds when fields exceed *max_fields*.

    Discord allows up to 25 fields per embed but readability drops fast.
    This helper creates continuation embeds that share the original colour
    and footer.
    """
    fields = embed.fields
    if len(fields) <= max_fields:
        if len(fields) > 20:
            logger.warning(
                "Embed '%s' has %d fields (>20), consider reducing",
                embed.title,
                len(fields),
            )
        return [embed]

    logger.info(
        "Splitting embed '%s' with %d fields into chunks of %d",
        embed.title,
        len(fields),
        max_fields,
    )

    embeds: list[discord.Embed] = []
    for i in range(0, len(fields), max_fields):
        chunk = fields[i : i + max_fields]
        if i == 0:
            # First embed keeps title, description, etc.
            new_embed = discord.Embed(
                title=embed.title,
                description=embed.description,
                color=embed.color,
            )
        else:
            new_embed = discord.Embed(
                title=f"{embed.title} (续)",
                color=embed.color,
            )
        for field in chunk:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        embeds.append(new_embed)

    # Set footer on last embed only
    if embed.footer.text:
        embeds[-1].set_footer(text=embed.footer.text)

    return embeds
