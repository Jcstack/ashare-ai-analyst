"""Slash command: /ask — multi-turn agent conversation via Discord threads.

Handles both the initial /ask command and all follow-up messages in
Discord threads, backed by Redis-persisted thread mappings.
"""

from __future__ import annotations

import asyncio
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot import split_message
from src.discord_bot.thread_store import ThreadMapping, ThreadStore
from src.discord_bot.views import EndConversationView, FollowUpView
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.agent")

_AGENT_TIMEOUT = 600
_CLEANUP_INTERVAL = 300  # 5 min
_IDLE_TIMEOUT = 1800  # 30 min
_END_KEYWORDS = re.compile(r"^(结束|结束对话|关闭|bye|end)$", re.IGNORECASE)


class AgentCommandsCog(commands.Cog):
    """Free-form Q&A backed by AgentService with Redis-persisted thread follow-up."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._thread_locks: dict[int, asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _get_store() -> ThreadStore | None:
        from src.web.dependencies import get_redis

        r = get_redis()
        if r is None:
            return None
        return ThreadStore(r)

    def _get_lock(self, thread_id: int) -> asyncio.Lock:
        if thread_id not in self._thread_locks:
            self._thread_locks[thread_id] = asyncio.Lock()
        return self._thread_locks[thread_id]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _agent_create(
        message: str,
        context_kwargs: dict | None = None,
    ) -> tuple[str, str]:
        """Create a new agent thread and return (thread_id, reply_text)."""
        from src.web.dependencies import get_agent_service
        from src.web.schemas.chat import ThreadContext

        svc = get_agent_service()
        ctx = ThreadContext(**(context_kwargs or {"mode": "general"}))
        thread_id, reply = await svc.create_thread(message, ctx)
        return thread_id, reply.content

    @staticmethod
    async def _agent_reply(thread_id: str, message: str) -> str:
        """Continue an agent conversation and return reply text."""
        from src.web.dependencies import get_agent_service

        svc = get_agent_service()
        reply = await svc.send_message(thread_id, message)
        return reply.content

    # ------------------------------------------------------------------
    # Lifecycle — background cleanup
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        self._cleanup_task = self.bot.loop.create_task(self._idle_cleanup_loop())

    async def cog_unload(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

    async def _idle_cleanup_loop(self) -> None:
        """Periodically end threads that have been idle too long."""
        await self.bot.wait_until_ready()
        try:
            while True:
                await asyncio.sleep(_CLEANUP_INTERVAL)
                await self._cleanup_idle_threads()
        except asyncio.CancelledError:
            logger.info("Idle cleanup loop cancelled")

    async def _cleanup_idle_threads(self) -> None:
        store = self._get_store()
        if store is None:
            return
        try:
            active = await asyncio.to_thread(store.scan_active)
        except Exception:
            logger.warning("Failed to scan active threads", exc_info=True)
            return

        now = time.time()
        for discord_tid, mapping in active:
            if now - mapping.last_active_at < _IDLE_TIMEOUT:
                continue
            try:
                thread = self.bot.get_channel(discord_tid)
                if isinstance(thread, discord.Thread):
                    await self.end_conversation(thread, mapping)
                else:
                    # Thread not accessible, just mark ended in Redis
                    await asyncio.to_thread(store.mark_ended, discord_tid)
            except Exception:
                logger.debug(
                    "Cleanup: failed to end thread %s", discord_tid, exc_info=True
                )

    # ------------------------------------------------------------------
    # Slash command: /ask
    # ------------------------------------------------------------------

    @app_commands.command(name="ask", description="AI自由问答")
    @app_commands.describe(question="你的问题")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer()

        t0 = time.monotonic()
        try:
            agent_tid, reply_text = await asyncio.wait_for(
                self._agent_create(question),
                timeout=_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            logger.warning("Agent create_thread timed out after %.0fs", elapsed)
            await interaction.followup.send(
                "\u23f3 Agent 超时（等待超过5分钟），请稍后重试"
            )
            return
        except Exception as exc:
            logger.error("Agent create_thread failed: %s", exc, exc_info=True)
            await interaction.followup.send("\u26a0\ufe0f Agent 异常，请稍后重试")
            return

        elapsed = time.monotonic() - t0
        logger.info(
            "Agent create_thread completed in %.1fs, reply_len=%d",
            elapsed,
            len(reply_text),
        )

        # Build context for follow-up
        ctx_summary = f"自由问答: {question[:200]}"
        ctx_kwargs: dict = {"mode": "general"}

        chunks = split_message(reply_text)
        view = FollowUpView(
            source_command="ask",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )
        await interaction.followup.send(chunks[0], view=view)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    # ------------------------------------------------------------------
    # Thread follow-up listener
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.Thread):
            return

        store = self._get_store()
        if store is None:
            return

        mapping = await asyncio.to_thread(store.get, message.channel.id)
        if mapping is None:
            return
        if mapping.ended:
            await message.channel.send(
                "\U0001f4a4 对话已结束，请重新发起命令开始新对话。"
            )
            return

        # Check end keywords
        if _END_KEYWORDS.match(message.content.strip()):
            await self.end_conversation(message.channel, mapping)
            return

        # Serialize per-thread to prevent race conditions
        async with self._get_lock(message.channel.id):
            placeholder = await message.channel.send("\U0001f914 正在分析中\u2026")

            t0 = time.monotonic()
            try:
                reply_text = await asyncio.wait_for(
                    self._agent_reply(mapping.agent_thread_id, message.content),
                    timeout=_AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - t0
                logger.warning("Agent send_message timed out after %.0fs", elapsed)
                await placeholder.edit(
                    content="\u23f3 Agent 超时（等待超过5分钟），请稍后重试"
                )
                return
            except Exception as exc:
                logger.error("Agent send_message failed: %s", exc, exc_info=True)
                await placeholder.edit(content="\u26a0\ufe0f Agent 异常，请稍后重试")
                return

            elapsed = time.monotonic() - t0
            logger.info(
                "Agent send_message completed in %.1fs, reply_len=%d",
                elapsed,
                len(reply_text),
            )

            # Update Redis
            updated = await asyncio.to_thread(store.update_active, message.channel.id)
            round_num = updated.round_count if updated else 0

            # Send reply with end button + footer
            chunks = split_message(reply_text)
            view = EndConversationView(
                discord_thread_id=message.channel.id,
                round_number=round_num,
                bot=self.bot,
            )
            footer = f'\n\n_\U0001f4ac 对话中 \u00b7 第 {round_num} 轮 \u00b7 发送"结束"可关闭_'
            await placeholder.edit(content=chunks[0] + footer, view=view)
            for chunk in chunks[1:]:
                await message.channel.send(chunk)

    # ------------------------------------------------------------------
    # Thread archive / delete listener
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_thread_update(
        self, before: discord.Thread, after: discord.Thread
    ) -> None:
        """Auto-end conversation when a Discord thread is archived."""
        if before.archived or not after.archived:
            return

        store = self._get_store()
        if store is None:
            return

        mapping = await asyncio.to_thread(store.get, after.id)
        if mapping is None or mapping.ended:
            return

        logger.info("Thread %s archived by user, ending conversation", after.id)
        await asyncio.to_thread(store.mark_ended, after.id)
        self._thread_locks.pop(after.id, None)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        """Clean up Redis mapping when a thread is deleted."""
        store = self._get_store()
        if store is None:
            return

        mapping = await asyncio.to_thread(store.get, thread.id)
        if mapping is None:
            return

        logger.info("Thread %s deleted, removing mapping", thread.id)
        await asyncio.to_thread(store.delete, thread.id)
        self._thread_locks.pop(thread.id, None)

    # ------------------------------------------------------------------
    # End conversation
    # ------------------------------------------------------------------

    async def end_conversation(
        self,
        thread: discord.Thread,
        mapping: ThreadMapping | None = None,
    ) -> None:
        """End a multi-turn conversation: summarise, rename, persist."""
        store = self._get_store()
        if store is None:
            return

        if mapping is None:
            mapping = await asyncio.to_thread(store.get, thread.id)
        if mapping is None:
            return

        # Calculate summary
        duration = time.time() - mapping.created_at
        duration_min = int(duration / 60)
        summary = (
            f"\U0001f6d1 对话结束 \u00b7 共 {mapping.round_count} 轮 "
            f"\u00b7 持续 {duration_min} 分钟"
        )
        try:
            await thread.send(summary)
        except Exception:
            pass

        # Rename thread: 🟢 → ⚫
        try:
            new_name = thread.name.replace("\U0001f7e2", "\u26ab")
            if new_name == thread.name:
                new_name = f"\u26ab {thread.name}"
            await thread.edit(name=new_name[:100])
        except Exception:
            logger.debug("Could not rename thread %s", thread.id, exc_info=True)

        # Mark ended in Redis
        await asyncio.to_thread(store.mark_ended, thread.id)

        # Clean up lock
        self._thread_locks.pop(thread.id, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AgentCommandsCog(bot))
