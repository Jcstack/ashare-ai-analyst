"""Discord UI Views for multi-turn conversation buttons."""

from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord.ext import commands

from src.discord_bot import split_message
from src.discord_bot.config import get_timeout
from src.discord_bot.thread_store import ThreadMapping, ThreadStore
from src.utils.logger import get_logger

logger = get_logger("discord.views")

_VIEW_TIMEOUT = 1800  # 30 min


class FollowUpView(discord.ui.View):
    """Attaches a "深入讨论" button to any command response."""

    def __init__(
        self,
        *,
        source_command: str,
        context_summary: str,
        thread_context_kwargs: dict[str, Any],
        bot: commands.Bot,
    ) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT)
        self.source_command = source_command
        self.context_summary = context_summary
        self.thread_context_kwargs = thread_context_kwargs
        self.bot = bot

    @discord.ui.button(
        label="深入讨论",
        style=discord.ButtonStyle.primary,
        emoji="\U0001f4ac",
    )
    async def follow_up(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            from src.web.dependencies import get_agent_service, get_redis
            from src.web.schemas.chat import ThreadContext

            # 1. Create Agent thread with context
            initial_msg = (
                f"[系统上下文]\n{self.context_summary}\n\n"
                "请基于以上结果，询问用户想深入了解哪些方面。"
            )
            svc = get_agent_service()
            ctx = ThreadContext(**self.thread_context_kwargs)
            agent_tid, reply = await asyncio.wait_for(
                svc.create_thread(initial_msg, ctx),
                timeout=get_timeout("follow_up_timeout", 600),
            )
            reply_text = reply.content

            # 2. Create Discord Thread on the original message
            info = self.context_summary.split("\n")[0][:40]
            thread_name = f"\U0001f7e2 [{self.source_command}] {info}"
            thread = await interaction.message.create_thread(
                name=thread_name[:100],
                auto_archive_duration=60,
            )

            # 3. Save mapping to Redis
            redis_client = get_redis()
            if redis_client:
                store = ThreadStore(redis_client)
                mapping = ThreadMapping(
                    agent_thread_id=agent_tid,
                    source_command=self.source_command,
                    context_summary=self.context_summary,
                )
                await asyncio.to_thread(store.save, thread.id, mapping)

            # 4. Send agent reply in thread with EndConversationView
            chunks = split_message(reply_text)
            end_view = EndConversationView(
                discord_thread_id=thread.id,
                round_number=0,
                bot=self.bot,
            )
            footer = '\n\n_\U0001f4ac 对话已开始 \u00b7 发送消息继续 \u00b7 发送"结束"可关闭_'
            await thread.send(chunks[0] + footer, view=end_view)
            for chunk in chunks[1:]:
                await thread.send(chunk)

            # 5. Ephemeral confirmation
            await interaction.followup.send(
                "\u2705 已在上方创建对话 Thread",
                ephemeral=True,
            )

            # Disable the button after use
            button.disabled = True
            button.label = "对话进行中"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

        except asyncio.TimeoutError:
            await interaction.followup.send(
                "\u23f3 Agent 超时，请稍后重试",
                ephemeral=True,
            )
        except Exception as exc:
            logger.error("FollowUpView callback failed: %s", exc, exc_info=True)
            await interaction.followup.send(
                "\u26a0\ufe0f 创建对话失败，请稍后重试",
                ephemeral=True,
            )


class EndConversationView(discord.ui.View):
    """Attaches a "结束对话" button to each reply in a thread."""

    def __init__(
        self,
        *,
        discord_thread_id: int,
        round_number: int,
        bot: commands.Bot,
    ) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT)
        self.discord_thread_id = discord_thread_id
        self.round_number = round_number
        self.bot = bot

    @discord.ui.button(
        label="结束对话",
        style=discord.ButtonStyle.secondary,
        emoji="\U0001f51a",
    )
    async def end_conversation(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            cog = self.bot.get_cog("AgentCommandsCog")
            if cog is not None:
                thread = interaction.channel
                if isinstance(thread, discord.Thread):
                    await cog.end_conversation(thread, mapping=None)
                    await interaction.followup.send(
                        "\u2705 对话已结束",
                        ephemeral=True,
                    )
                    return

            await interaction.followup.send(
                "\u26a0\ufe0f 无法结束对话",
                ephemeral=True,
            )
        except Exception as exc:
            logger.error("EndConversationView failed: %s", exc, exc_info=True)
            await interaction.followup.send(
                "\u26a0\ufe0f 结束对话失败",
                ephemeral=True,
            )
