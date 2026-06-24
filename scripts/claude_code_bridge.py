"""Claude Code HTTP Bridge — wraps `claude -p` as a lightweight HTTP service.

Runs on the host machine (NOT Docker). Docker containers reach it via
``host.docker.internal:19821``.

Usage:
    .venv/bin/python scripts/claude_code_bridge.py          # foreground
    make bridge-start                                       # background (nohup)

Endpoints:
    POST /v1/chat   — send a message, get Claude Code reply
    GET  /health    — liveness + claude version
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from aiohttp import web

logger = logging.getLogger("claude_code_bridge")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ── Config ──────────────────────────────────────────────────────────
HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRIDGE_PORT", "19821"))
TIMEOUT = int(os.environ.get("BRIDGE_TIMEOUT", "900"))

# MCP config for Claude Code to access Docker API tools
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_CONFIG = PROJECT_ROOT / "research" / ".mcp.json"

# Session idle timeout — close sessions after 30 min of inactivity
SESSION_IDLE_TIMEOUT = int(os.environ.get("SESSION_IDLE_TIMEOUT", "1800"))

# Track active sessions: session_id -> last_active_timestamp
_active_sessions: dict[str, float] = {}

# Lock for session cleanup
_cleanup_lock = asyncio.Lock()


def _find_claude_bin() -> str:
    """Locate the claude CLI binary."""
    claude = shutil.which("claude")
    if claude:
        return claude
    # Common locations on macOS
    for path in ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError("claude CLI not found in PATH")


async def _get_claude_version() -> str:
    """Get claude CLI version string."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _find_claude_bin(),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout.decode().strip()
    except Exception:
        return "unknown"


async def _close_session(session_id: str) -> None:
    """Close a Claude Code session by removing it from tracking.

    Claude Code sessions are stateless from our side when using -p mode.
    We just need to stop tracking them so we don't resume stale sessions.
    """
    _active_sessions.pop(session_id, None)
    logger.info("Session closed: %s", session_id)


async def _cleanup_idle_sessions() -> None:
    """Close sessions that have been idle beyond SESSION_IDLE_TIMEOUT."""
    async with _cleanup_lock:
        now = time.time()
        expired = [
            sid
            for sid, last_active in _active_sessions.items()
            if now - last_active > SESSION_IDLE_TIMEOUT
        ]
        for sid in expired:
            await _close_session(sid)
        if expired:
            logger.info(
                "Cleaned up %d idle sessions (timeout=%ds)",
                len(expired),
                SESSION_IDLE_TIMEOUT,
            )


async def _periodic_cleanup(app: web.Application) -> None:
    """Background task to periodically clean up idle sessions."""
    try:
        while True:
            await asyncio.sleep(300)  # Check every 5 minutes
            await _cleanup_idle_sessions()
    except asyncio.CancelledError:
        pass


# ── Handlers ────────────────────────────────────────────────────────


async def handle_chat(request: web.Request) -> web.Response:
    """POST /v1/chat — call claude -p with the user message."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    message = body.get("message", "").strip()
    if not message:
        return web.json_response({"error": "message required"}, status=400)

    system_prompt = body.get("system_prompt", "")
    model = body.get("model", "opus")
    session_id = body.get("session_id")
    conversation_history = body.get("conversation_history", [])

    # Generate session_id for new conversations
    is_new_session = not session_id
    if is_new_session:
        session_id = str(uuid.uuid4())

    # Build the prompt — prepend conversation history for context
    prompt_parts: list[str] = []
    if conversation_history and is_new_session:
        # For first message in a session, include history as context
        prompt_parts.append("<conversation_history>")
        for msg in conversation_history[-10:]:  # Last 10 messages max
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"[{role}]: {content}")
        prompt_parts.append("</conversation_history>")
        prompt_parts.append("")
    prompt_parts.append(message)
    full_prompt = "\n".join(prompt_parts)

    # Build claude command
    claude_bin = _find_claude_bin()
    cmd = [
        claude_bin,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--permission-mode",
        "bypassPermissions",
    ]

    # System prompt
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    # Override tool-usage guidance: prefer lightweight MCP tools, avoid
    # multiple redundant calls.  Appended after the main system prompt.
    cmd.extend(
        [
            "--append-system-prompt",
            (
                "## MCP 工具使用优化\n"
                "- 你的数据工具是 MCP 服务（get_realtime_snapshot, get_bayesian_analysis, "
                "get_fund_flow, get_sentiment_data, get_market_overview, get_portfolio, "
                "get_intraday_patterns, get_minute_bars, get_intraday_overview）\n"
                "- 分析持仓股时，先调用 get_portfolio 获取持仓+实时盈亏（含现价/市值/盈亏金额/盈亏百分比），再逐股分析\n"
                "- 盘中分析使用 get_intraday_patterns + get_minute_bars 获取分时数据\n"
                "- 优先使用 get_realtime_snapshot 一次性获取行情+资金+成交\n"
                "- 每种工具最多调用 1 次，避免重复调用\n"
                "- 工具超时或失败时直接跳过，用已有数据完成分析\n"
                "- 总工具调用控制在 5 次以内\n\n"
                "## 数据来源铁律（不可违反）\n"
                "- 股票价格/成交量/涨跌幅/资金流向 只能来自 MCP 工具或本地 fetcher\n"
                "- 严禁使用 WebSearch/WebFetch 获取任何行情数据\n"
                "- MCP 失败时用本地 fetcher 数据，本地也失败时停止分析，返回错误\n"
                "- 违反此规则会导致用户基于错误数据做出交易决策，造成真实资金损失"
            ),
        ]
    )

    # MCP config for accessing Docker API tools
    if MCP_CONFIG.exists():
        cmd.extend(["--mcp-config", str(MCP_CONFIG)])

    # Allowed tools — read-only safe set + MCP tools
    # get_comprehensive_analysis is intentionally excluded here: it triggers
    # an 8-way data fetch + LLM synthesis (30-60s) which easily causes the
    # bridge to exceed its timeout. Claude should compose lighter individual
    # tools (realtime_snapshot, bayesian, fund_flow, sentiment) instead.
    # The research/ workspace retains full access via its own .mcp.json.
    cmd.extend(
        [
            "--allowedTools",
            (
                "Read,WebSearch,WebFetch,"
                "mcp__ashare-research__get_realtime_snapshot,"
                "mcp__ashare-research__get_bayesian_analysis,"
                "mcp__ashare-research__get_fund_flow,"
                "mcp__ashare-research__get_sentiment_data,"
                "mcp__ashare-research__get_market_overview,"
                "mcp__ashare-research__get_recommendations,"
                "mcp__ashare-research__get_portfolio,"
                "mcp__ashare-research__get_intraday_patterns,"
                "mcp__ashare-research__get_minute_bars,"
                "mcp__ashare-research__get_intraday_overview,"
                "mcp__ashare-research__get_data_health,"
                "mcp__ashare-research__push_message_to_user"
            ),
        ]
    )

    # Session management: resume existing or start new
    if not is_new_session and session_id in _active_sessions:
        cmd.extend(["--resume", session_id])
    else:
        cmd.extend(["--session-id", session_id])

    logger.info(
        "Calling claude: model=%s session=%s new=%s prompt_len=%d",
        model,
        session_id[:8],
        is_new_session,
        len(full_prompt),
    )

    # Strip CLAUDECODE env var so the child `claude` process doesn't
    # detect a parent session and refuse to start (nested-session guard).
    child_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    start = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env=child_env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=full_prompt.encode()),
            timeout=TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("claude process timed out after %ds", TIMEOUT)
        try:
            proc.kill()
        except Exception:
            pass
        return web.json_response(
            {"error": f"Claude Code 响应超时 ({TIMEOUT}s)", "session_id": session_id},
            status=504,
        )
    except FileNotFoundError:
        return web.json_response(
            {"error": "claude CLI not found — is Claude Code installed?"},
            status=503,
        )

    duration_ms = int((time.perf_counter() - start) * 1000)

    if proc.returncode != 0:
        err = stderr.decode()[:500] if stderr else "unknown error"
        logger.error("claude exited %d: %s", proc.returncode, err)
        return web.json_response(
            {"error": f"Claude Code error: {err}", "session_id": session_id},
            status=502,
        )

    # Parse JSON output
    raw_output = stdout.decode()
    try:
        result = json.loads(raw_output)
        text = result.get("result", raw_output)
    except json.JSONDecodeError:
        # Fallback: treat as plain text
        text = raw_output

    # Track session activity
    _active_sessions[session_id] = time.time()

    logger.info(
        "claude replied: session=%s duration=%dms text_len=%d",
        session_id[:8],
        duration_ms,
        len(text),
    )

    return web.json_response(
        {
            "session_id": session_id,
            "text": text,
            "model": model,
            "duration_ms": duration_ms,
        }
    )


async def handle_close_session(request: web.Request) -> web.Response:
    """POST /v1/sessions/{session_id}/close — explicitly close a session."""
    session_id = request.match_info.get("session_id", "")
    if not session_id:
        return web.json_response({"error": "session_id required"}, status=400)

    was_active = session_id in _active_sessions
    await _close_session(session_id)

    return web.json_response(
        {
            "session_id": session_id,
            "was_active": was_active,
            "status": "closed",
        }
    )


async def handle_health(request: web.Request) -> web.Response:
    """GET /health — liveness check."""
    version = await _get_claude_version()
    return web.json_response(
        {
            "status": "ok",
            "claude_version": version,
            "active_sessions": len(_active_sessions),
            "session_idle_timeout": SESSION_IDLE_TIMEOUT,
        }
    )


async def handle_sessions(request: web.Request) -> web.Response:
    """GET /v1/sessions — list active sessions."""
    now = time.time()
    sessions = [
        {
            "session_id": sid,
            "idle_seconds": int(now - last_active),
            "ttl_seconds": max(0, SESSION_IDLE_TIMEOUT - int(now - last_active)),
        }
        for sid, last_active in _active_sessions.items()
    ]
    return web.json_response(
        {
            "active_sessions": len(sessions),
            "sessions": sessions,
        }
    )


# ── App lifecycle ───────────────────────────────────────────────────


async def on_startup(app: web.Application) -> None:
    """Start background cleanup task."""
    app["cleanup_task"] = asyncio.create_task(_periodic_cleanup(app))
    logger.info(
        "Bridge started: host=%s port=%d idle_timeout=%ds",
        HOST,
        PORT,
        SESSION_IDLE_TIMEOUT,
    )


async def on_cleanup(app: web.Application) -> None:
    """Cancel background tasks on shutdown."""
    task = app.get("cleanup_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Close all active sessions
    for sid in list(_active_sessions):
        await _close_session(sid)
    logger.info("Bridge shutdown complete")


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_post("/v1/chat", handle_chat)
    app.router.add_post("/v1/sessions/{session_id}/close", handle_close_session)
    app.router.add_get("/v1/sessions", handle_sessions)
    app.router.add_get("/health", handle_health)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
