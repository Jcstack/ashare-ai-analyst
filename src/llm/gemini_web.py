"""Gemini Web App LLM provider via Playwright CDP automation.

Connects to an existing Chrome instance (--remote-debugging-port=9222),
opens Gemini Web in a new tab per request, uses Temporary Chat + Thinking mode,
and extracts the response.

All Gemini-specific DOM interaction is isolated to this module.
"""

from __future__ import annotations

import asyncio
import atexit
import html
import heapq
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
)
from src.utils.logger import get_logger

logger = get_logger("llm.gemini_web")


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class GeminiWebError(LLMProviderError):
    """Base for all Gemini Web errors."""

    def __init__(self, msg: str, *, retryable: bool = True):
        super().__init__(msg, provider=ProviderName.GEMINI_WEB, retryable=retryable)


class ChromeConnectionError(GeminiWebError):
    """Chrome not running or CDP port unreachable."""

    pass


class NavigationError(GeminiWebError):
    """Gemini page failed to load."""

    pass


class AuthenticationError(GeminiWebError):
    """Google session expired — requires manual re-login."""

    def __init__(
        self, msg: str = "Google session expired — re-login required in Chrome"
    ):
        super().__init__(msg, retryable=False)


class SelectorDriftError(GeminiWebError):
    """All selector variants failed — Gemini UI may have changed."""

    def __init__(self, msg: str):
        super().__init__(msg, retryable=False)


class TemporaryChatError(GeminiWebError):
    """Cannot enable Temporary Chat."""

    pass


class ThinkingModeError(GeminiWebError):
    """Cannot select Thinking mode."""

    pass


class PromptInputError(GeminiWebError):
    """Cannot input prompt text into composer."""

    pass


class SubmitError(GeminiWebError):
    """Send button not clickable or generation did not start."""

    pass


class GenerationTimeoutError(GeminiWebError):
    """Response generation did not complete within timeout."""

    def __init__(self, msg: str):
        super().__init__(msg, retryable=False)


class ExtractionError(GeminiWebError):
    """Response container found but empty."""

    pass


class RateLimitError(GeminiWebError):
    """Gemini displayed a rate-limit message."""

    pass


class PageCrashedError(GeminiWebError):
    """Tab crashed or became unresponsive."""

    pass


# ---------------------------------------------------------------------------
# Selectors — SINGLE SOURCE OF TRUTH for Gemini DOM interaction
# ---------------------------------------------------------------------------


class _Sel:
    """Gemini Web App CSS/ARIA selectors. Update HERE when UI changes.

    Last verified: 2026-03-14 (Gemini 3 / Google One Pro).
    """

    PROMPT_INPUT = [
        '.ql-editor[contenteditable="true"]',
        'div[contenteditable="true"][aria-label*="prompt" i]',
        'div[contenteditable="true"][role="textbox"]',
        'rich-textarea div[contenteditable="true"]',
        'div[contenteditable="true"]',
    ]

    SEND_BUTTON = [
        'button[aria-label*="Send" i]',
        'button[aria-label*="send message" i]',
        "button.send-button",
        'button[data-test-id="send-button"]',
    ]

    STOP_BUTTON = [
        'button[aria-label*="Stop" i]',
        'button[aria-label*="stop generating" i]',
    ]

    RESPONSE_CONTAINER = [
        "message-content.model-response-text",
        ".model-response-text",
        '[data-message-author-role="model"] .message-content',
        ".response-container .markdown",
    ]

    # The speed/mode dropdown (shows "Fast" / "Thinking" / etc.)
    MODE_SELECTOR_TRIGGER = [
        'button:has-text("Fast")',
        'button:has-text("Thinking")',
        'button[aria-label*="model" i]',
        ".model-selector button",
        '[data-test-id="model-selector"]',
    ]

    THINKING_OPTION = [
        '[role="option"]:has-text("Think")',
        '[role="menuitem"]:has-text("Think")',
        '[role="listbox"] >> text=Think',
        'mat-option:has-text("Think")',
        # Fallback: any clickable item in the dropdown with "Think"
        'button:has-text("Think")',
    ]

    TEMP_CHAT_TOGGLE = [
        'button[data-test-id="temp-chat-button"]',
        'button[aria-label*="emporary" i]',
        'button[aria-label*="临时" i]',
        'button[tooltip*="emporary" i]',
        'button[mattooltip*="emporary" i]',
        # Dashed-bubble icon button near "New chat" (2026-03 UI)
        'button[jsname] > span.material-symbols-outlined:has-text("chat_bubble_outline")',
        ".temp-chat-toggle",
        ".temp-chat-button",
        '[data-test-id="temp-chat"]',
    ]

    # Selector to start a new temporary chat from the side-panel
    TEMP_CHAT_NEW = [
        'button:has-text("Temporary chat")',
        'button:has-text("临时对话")',
        'a[href*="temp"]',
        '[data-test-id="new-temp-chat"]',
    ]

    AUTH_WALL = [
        'form[action*="accounts.google.com"]',
        "[data-identifier]",
    ]

    # Overlay/dialog dismiss buttons — promos, cookie consent, etc.
    OVERLAY_DISMISS = [
        'button:has-text("Not now")',
        'button:has-text("No thanks")',
        'button:has-text("Dismiss")',
        'button:has-text("Got it")',
        'button:has-text("Skip")',
        'button[aria-label*="Close" i]',
        'button[aria-label*="Dismiss" i]',
    ]

    # The CDK overlay backdrop itself
    OVERLAY_BACKDROP = [
        ".cdk-overlay-backdrop-showing",
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _find_element(
    page: Any, selectors: list[str], timeout: float = 10_000
) -> Any:
    """Try selectors in order, return first visible match."""
    per_sel = max(1000, timeout // max(len(selectors), 1))
    for idx, sel in enumerate(selectors):
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=per_sel)
            if idx > 0:
                logger.info(
                    "gemini_web | selector_fallback | index=%d | sel=%s", idx, sel
                )
            return loc
        except Exception:
            continue
    raise SelectorDriftError(f"No selector matched: {selectors}")


async def _is_visible_safe(locator: Any, timeout: float = 500) -> bool:
    """Check visibility without raising."""
    try:
        await locator.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Chrome Connector (singleton per provider instance)
# ---------------------------------------------------------------------------


class _ConnectionPool:
    """Persistent Playwright + Chrome connection pool with tab reuse.

    Maintains a single Playwright instance and CDP browser connection.
    Uses ``asyncio.Semaphore`` to allow controlled concurrency (default 2
    concurrent tabs) instead of serializing all requests with a Lock.

    Must be used from the shared event loop managed by ``_LoopThread``.
    """

    def __init__(
        self, debug_url: str = "http://127.0.0.1:9222", max_concurrent: int = 2
    ):
        self._debug_url = debug_url
        self._max_concurrent = max_concurrent
        self._pw: Any = None
        self._browser: Any = None
        self._semaphore: asyncio.Semaphore | None = None
        self._connect_lock = asyncio.Lock()
        self._closed = False

    async def _ensure_connected(self) -> None:
        """Lazily create / reconnect the Playwright + CDP connection."""
        if self._browser is not None:
            # Quick health check — contexts list survives if connection is live
            try:
                _ = self._browser.contexts
                return
            except Exception:
                logger.warning("gemini_web | pool | stale_connection, reconnecting")
                await self._teardown()

        async with self._connect_lock:
            # Double-check after acquiring lock
            if self._browser is not None:
                try:
                    _ = self._browser.contexts
                    return
                except Exception:
                    await self._teardown()

            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            try:
                self._browser = await self._pw.chromium.connect_over_cdp(
                    self._debug_url, timeout=10_000
                )
                self._semaphore = asyncio.Semaphore(self._max_concurrent)
                logger.info(
                    "gemini_web | pool | status=connected | url=%s | max_concurrent=%d",
                    self._debug_url,
                    self._max_concurrent,
                )
            except Exception as e:
                await self._teardown()
                raise ChromeConnectionError(
                    f"Cannot connect to Chrome at {self._debug_url}: {e}"
                )

    async def acquire(self) -> Any:
        """Acquire a concurrency slot and return the browser.

        The caller gets the shared browser reference and must call
        ``release()`` when the tab is closed.
        """
        await self._ensure_connected()
        assert self._semaphore is not None
        await self._semaphore.acquire()
        # Re-verify after potential wait on semaphore
        try:
            await self._ensure_connected()
        except Exception:
            self._semaphore.release()
            raise
        return self._browser

    def release(self) -> None:
        """Release a concurrency slot."""
        if self._semaphore is not None:
            self._semaphore.release()

    async def _teardown(self) -> None:
        """Tear down Playwright + browser connection."""
        browser, pw = self._browser, self._pw
        self._browser = None
        self._pw = None
        self._semaphore = None
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass

    async def close(self) -> None:
        """Permanently shut down the pool."""
        self._closed = True
        await self._teardown()
        logger.info("gemini_web | pool | status=closed")


# ---------------------------------------------------------------------------
# Shared Event Loop Thread
# ---------------------------------------------------------------------------


class _LoopThread:
    """Runs a single asyncio event loop on a daemon thread.

    All Playwright interactions go through this loop so that:
    - The connection pool persists across calls (same loop = same objects).
    - ``complete()`` callers (which may be sync or in different async loops)
      use ``run_coro()`` to submit work without creating new event loops.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def ensure_running(self) -> asyncio.AbstractEventLoop:
        """Start the loop thread if it isn't running yet. Return the loop."""
        if self._loop is not None and self._loop.is_running():
            return self._loop
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="gemini-web-loop"
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        assert self._loop is not None
        return self._loop

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def run_coro(self, coro: Any) -> Any:
        """Submit a coroutine to the loop thread and block until done."""
        loop = self.ensure_running()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()  # blocks calling thread

    def stop(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None


# ---------------------------------------------------------------------------
# Request Priority Queue
# ---------------------------------------------------------------------------

# Priority levels (lower number = higher priority)
PRIORITY_HIGH = 0  # User-triggered: MCP, conversation
PRIORITY_NORMAL = 5  # Default
PRIORITY_LOW = 10  # Background scans: intraday, signal

# Callers that get high/low priority (prefix match)
_HIGH_PRIORITY_CALLERS = {"mcp", "conversation", "user", "chat", "assistant"}
_LOW_PRIORITY_CALLERS = {
    "intraday",
    "signal",
    "scan",
    "background",
    "pipeline",
    "schedule",
}

_request_counter = 0
_counter_lock = threading.Lock()


def _next_request_id() -> int:
    global _request_counter
    with _counter_lock:
        _request_counter += 1
        return _request_counter


def _caller_priority(caller: str) -> int:
    """Determine priority from caller name."""
    lower = caller.lower()
    for prefix in _HIGH_PRIORITY_CALLERS:
        if lower.startswith(prefix):
            return PRIORITY_HIGH
    for prefix in _LOW_PRIORITY_CALLERS:
        if lower.startswith(prefix):
            return PRIORITY_LOW
    return PRIORITY_NORMAL


@dataclass(order=True)
class _PrioritizedRequest:
    """A request in the priority queue."""

    priority: int
    seq: int = field(compare=True)  # tie-breaker: FIFO within same priority
    future: asyncio.Future = field(compare=False)
    coro_factory: Any = field(compare=False)  # callable returning coroutine


class _RequestQueue:
    """Priority queue that feeds requests to the connection pool.

    Higher priority requests are dequeued first. The queue itself does
    not limit concurrency — that is handled by ``_ConnectionPool``'s
    semaphore.
    """

    def __init__(self) -> None:
        self._heap: list[_PrioritizedRequest] = []
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
        self._running = False
        self._processor_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background processor."""
        if self._running:
            return
        self._running = True
        self._processor_task = asyncio.ensure_future(self._process_loop())

    async def stop(self) -> None:
        self._running = False
        self._not_empty.set()  # wake up processor
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except (asyncio.CancelledError, Exception):
                pass

    async def submit(self, coro_factory: Any, priority: int = PRIORITY_NORMAL) -> Any:
        """Submit a request and wait for its result.

        ``coro_factory`` is a zero-argument callable that returns a coroutine.
        This is needed because coroutines can't be restarted if they fail.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        seq = _next_request_id()
        item = _PrioritizedRequest(
            priority=priority, seq=seq, future=future, coro_factory=coro_factory
        )
        async with self._lock:
            heapq.heappush(self._heap, item)
        self._not_empty.set()
        logger.debug(
            "gemini_web | queue | enqueue | seq=%d | priority=%d | pending=%d",
            seq,
            priority,
            len(self._heap),
        )
        return await future

    async def _process_loop(self) -> None:
        """Dequeue and execute requests."""
        while self._running:
            # Wait for items
            if not self._heap:
                self._not_empty.clear()
                await self._not_empty.wait()
                if not self._running:
                    break

            async with self._lock:
                if not self._heap:
                    continue
                item = heapq.heappop(self._heap)

            # Execute in a fire-and-forget task so we can dequeue the next
            # request immediately (concurrency is bounded by the pool semaphore)
            asyncio.ensure_future(self._run_item(item))

    async def _run_item(self, item: _PrioritizedRequest) -> None:
        try:
            result = await item.coro_factory()
            if not item.future.done():
                item.future.set_result(result)
        except Exception as e:
            if not item.future.done():
                item.future.set_exception(e)


# ---------------------------------------------------------------------------
# Page Session
# ---------------------------------------------------------------------------


class _PageSession:
    """Manages a single Gemini tab lifecycle."""

    def __init__(self, browser: Any, gemini_url: str, page_load_timeout: float):
        self._browser = browser
        self._gemini_url = gemini_url
        self._page_load_timeout = page_load_timeout
        self.page: Any = None

    async def open(self) -> None:
        """Open new tab and navigate to Gemini."""
        try:
            context = self._browser.contexts[0]
            self.page = await context.new_page()
            await self.page.goto(
                self._gemini_url,
                wait_until="domcontentloaded",
                timeout=self._page_load_timeout * 1000,
            )
            logger.info("gemini_web | page_open | url=%s", self._gemini_url)

            # Wait for Gemini app to initialize
            await asyncio.sleep(2.0)

            # Check for auth wall
            for sel in _Sel.AUTH_WALL:
                if await self.page.locator(sel).count() > 0:
                    raise AuthenticationError()
        except AuthenticationError:
            raise
        except Exception as e:
            raise NavigationError(f"Failed to open Gemini page: {e}")

    async def close(self) -> None:
        """Close the tab."""
        if self.page and not self.page.is_closed():
            try:
                await self.page.close()
            except Exception:
                pass

    async def screenshot(self, name: str) -> None:
        """Save debug screenshot."""
        if self.page and not self.page.is_closed():
            try:
                debug_dir = Path("data/debug/gemini_screenshots")
                debug_dir.mkdir(parents=True, exist_ok=True)
                path = debug_dir / f"{int(time.time())}_{name}.png"
                await self.page.screenshot(path=str(path))
                logger.info("gemini_web | screenshot | path=%s", path)
            except Exception:
                logger.debug("Failed to save screenshot", exc_info=True)


# ---------------------------------------------------------------------------
# UI Controllers
# ---------------------------------------------------------------------------


class _OverlayDismisser:
    """Dismiss any popup/promo overlays that block interaction."""

    @staticmethod
    async def dismiss_all(page: Any, max_attempts: int = 3) -> None:
        """Try to dismiss overlays. Safe to call even when none exist."""
        for attempt in range(max_attempts):
            # Check if there is an active overlay
            has_overlay = False
            for sel in _Sel.OVERLAY_BACKDROP:
                if await page.locator(sel).count() > 0:
                    has_overlay = True
                    break

            if not has_overlay:
                return

            # Try dismiss buttons
            dismissed = False
            for sel in _Sel.OVERLAY_DISMISS:
                try:
                    btn = page.locator(sel).first
                    if await _is_visible_safe(btn, timeout=1000):
                        await btn.click(force=True)
                        await asyncio.sleep(0.8)
                        dismissed = True
                        logger.info(
                            "gemini_web | overlay_dismiss | selector=%s | attempt=%d",
                            sel,
                            attempt + 1,
                        )
                        break
                except Exception:
                    continue

            if not dismissed:
                # Last resort: click the backdrop itself or press Escape
                try:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                    logger.info(
                        "gemini_web | overlay_dismiss | method=escape | attempt=%d",
                        attempt + 1,
                    )
                except Exception:
                    pass

        # Log if overlay still present after all attempts
        for sel in _Sel.OVERLAY_BACKDROP:
            if await page.locator(sel).count() > 0:
                logger.warning("gemini_web | overlay_dismiss | status=still_present")
                return
        logger.info("gemini_web | overlay_dismiss | status=clear")


class _TemporaryChatController:
    """Ensure Temporary Chat mode is active.

    Strategy (2026-03):
    1. Try the toggle button (aria-pressed based)
    2. Try the "Temporary chat" / "临时对话" button in sidebar/menu
    3. If both fail, screenshot for debugging and raise
    """

    @staticmethod
    async def ensure(page: Any) -> None:
        # Strategy 1: toggle button with aria-pressed
        try:
            toggle = await _find_element(page, _Sel.TEMP_CHAT_TOGGLE, timeout=5_000)
            pressed = await toggle.get_attribute("aria-pressed")
            if pressed == "true":
                logger.info("gemini_web | temp_chat | status=already_enabled")
                return
            await toggle.click(force=True)
            await asyncio.sleep(0.5)
            logger.info("gemini_web | temp_chat | status=enabled_via_toggle")
            return
        except SelectorDriftError:
            logger.info("gemini_web | temp_chat | toggle_not_found | trying_menu")

        # Strategy 2: look for "Temporary chat" button/link in sidebar
        try:
            btn = await _find_element(page, _Sel.TEMP_CHAT_NEW, timeout=3_000)
            await btn.click(force=True)
            await asyncio.sleep(1.0)
            logger.info("gemini_web | temp_chat | status=enabled_via_menu")
            return
        except SelectorDriftError:
            pass

        # Strategy 3: JS-based — look for any element containing "emporary"
        try:
            found = await page.evaluate("""() => {
                const els = document.querySelectorAll('button, a, [role="button"]');
                for (const el of els) {
                    const text = (el.textContent || '').toLowerCase();
                    const label = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (text.includes('emporary') || label.includes('emporary')
                        || text.includes('临时') || label.includes('临时')) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if found:
                await asyncio.sleep(1.0)
                logger.info("gemini_web | temp_chat | status=enabled_via_js_scan")
                return
        except Exception:
            pass

        # All strategies failed — save debug screenshot
        try:
            debug_dir = Path("data/debug/gemini_screenshots")
            debug_dir.mkdir(parents=True, exist_ok=True)
            path = debug_dir / f"{int(time.time())}_temp_chat_failed.png"
            await page.screenshot(path=str(path), full_page=True)
            logger.error("gemini_web | temp_chat | status=FAILED | screenshot=%s", path)
        except Exception:
            pass
        raise TemporaryChatError(
            "Cannot find Temporary Chat toggle — UI may have changed. "
            "Check data/debug/gemini_screenshots/ for a screenshot."
        )


class _ThinkingModeSelector:
    """Select Thinking model/mode in Gemini.

    Current Gemini UI (2026-03): A dropdown button showing "Fast" or
    "Thinking" near the prompt input area. Clicking opens a listbox
    with mode options.
    """

    @staticmethod
    async def ensure(page: Any) -> None:
        # First check if "Thinking" is already selected (button text)
        try:
            thinking_btn = page.locator('button:has-text("Thinking")').first
            if await _is_visible_safe(thinking_btn, timeout=2000):
                logger.info("gemini_web | thinking_mode | status=already_selected")
                return
        except Exception:
            pass

        try:
            trigger = await _find_element(
                page, _Sel.MODE_SELECTOR_TRIGGER, timeout=8_000
            )
            await trigger.click(force=True)
            await asyncio.sleep(0.8)

            option = await _find_element(page, _Sel.THINKING_OPTION, timeout=5_000)
            await option.click(force=True)
            await asyncio.sleep(0.5)
            logger.info("gemini_web | thinking_mode | status=selected")
        except SelectorDriftError:
            raise ThinkingModeError("Cannot select Thinking mode — UI may have changed")


# ---------------------------------------------------------------------------
# Prompt Handling
# ---------------------------------------------------------------------------


class _PromptComposer:
    """Compile LLMMessage list into a single prompt string for Gemini."""

    @staticmethod
    def compile(messages: list[LLMMessage]) -> str:
        parts: list[str] = []
        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if msg.role == "system":
                parts.append(f"<system>\n{content}\n</system>\n")
            elif msg.role == "user":
                parts.append(content)
            elif msg.role == "assistant":
                parts.append(f"[Assistant previous response]\n{content}\n")
        return "\n".join(parts)


class _PromptInputter:
    """Input prompt text into Gemini's composer and submit."""

    @staticmethod
    async def input_and_submit(page: Any, text: str) -> None:
        editor = await _find_element(page, _Sel.PROMPT_INPUT, timeout=10_000)

        # Strategy 1: Clipboard paste (fast for long prompts)
        input_ok = False
        try:
            await editor.click()
            await page.evaluate(
                """async (text) => {
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    const el = document.querySelector('[contenteditable="true"]');
                    if (el) {
                        el.focus();
                        const evt = new ClipboardEvent('paste', {
                            clipboardData: dt, bubbles: true, cancelable: true
                        });
                        el.dispatchEvent(evt);
                    }
                }""",
                text,
            )
            await asyncio.sleep(0.3)
            content = await editor.inner_text()
            if len(content.strip()) >= min(20, len(text) // 4):
                input_ok = True
                logger.info(
                    "gemini_web | prompt_input | method=clipboard | chars=%d", len(text)
                )
        except Exception as e:
            logger.debug("gemini_web | clipboard_paste_failed: %s", e)

        # Strategy 2: fill() fallback
        if not input_ok:
            try:
                await editor.fill(text)
                input_ok = True
                logger.info(
                    "gemini_web | prompt_input | method=fill | chars=%d", len(text)
                )
            except Exception as e:
                logger.debug("gemini_web | fill_failed: %s", e)

        # Strategy 3: type() last resort (slow)
        if not input_ok:
            try:
                await editor.click()
                await editor.type(text, delay=1)
                input_ok = True
                logger.info(
                    "gemini_web | prompt_input | method=type | chars=%d", len(text)
                )
            except Exception as e:
                raise PromptInputError(f"All input methods failed: {e}")

        await asyncio.sleep(0.5)

        # Submit
        try:
            send_btn = await _find_element(page, _Sel.SEND_BUTTON, timeout=5_000)
            await send_btn.click()
            logger.info("gemini_web | submit | method=send_button")
        except SelectorDriftError:
            # Fallback: press Enter
            await editor.press("Enter")
            logger.info("gemini_web | submit | method=enter_key")


# ---------------------------------------------------------------------------
# Generation Watcher
# ---------------------------------------------------------------------------


class _GenerationWatcher:
    """Wait for Gemini to finish generating."""

    @staticmethod
    async def wait(page: Any, timeout: float = 300.0) -> None:
        start = time.monotonic()
        last_text = ""
        stable_count = 0
        STABLE_THRESHOLD = 5  # 5 × 2s = 10s stable before declaring done
        POLL_INTERVAL = 2.0

        # Phase 1: Wait for generation to START
        generation_started = False
        while time.monotonic() - start < 30:
            for sel in _Sel.STOP_BUTTON:
                if await _is_visible_safe(page.locator(sel).first, timeout=300):
                    generation_started = True
                    break
            if generation_started:
                break
            for sel in _Sel.RESPONSE_CONTAINER:
                try:
                    if await page.locator(sel).count() > 0:
                        generation_started = True
                        break
                except Exception:
                    continue
            if generation_started:
                break
            await asyncio.sleep(0.5)

        if not generation_started:
            raise SubmitError("Generation did not start within 30s after submit")

        logger.info(
            "gemini_web | generation_start | elapsed_ms=%d",
            int((time.monotonic() - start) * 1000),
        )

        # Phase 2: Wait for completion
        while time.monotonic() - start < timeout:
            # Signal 1: Stop button gone
            stop_visible = False
            for sel in _Sel.STOP_BUTTON:
                if await _is_visible_safe(page.locator(sel).first, timeout=300):
                    stop_visible = True
                    break

            if not stop_visible:
                # Double-check: wait 2s then verify stop button is still
                # gone. Gemini Thinking mode may briefly hide the button
                # between thinking and output phases.
                await asyncio.sleep(2.0)
                still_gone = True
                for sel in _Sel.STOP_BUTTON:
                    if await _is_visible_safe(page.locator(sel).first, timeout=500):
                        still_gone = False
                        break
                if still_gone:
                    elapsed = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "gemini_web | generation_complete | signal=stop_gone | elapsed_ms=%d",
                        elapsed,
                    )
                    return

            # Signal 2: Content stabilization (backup)
            current = await _ResponseExtractor.extract_safe(page)
            if current and current == last_text and len(current) > 10:
                stable_count += 1
                if stable_count >= STABLE_THRESHOLD:
                    elapsed = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "gemini_web | generation_complete | signal=content_stable | elapsed_ms=%d",
                        elapsed,
                    )
                    return
            else:
                stable_count = 0
                last_text = current

            await asyncio.sleep(POLL_INTERVAL)

        raise GenerationTimeoutError(f"Generation did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# HTML → Markdown converter (zero-dependency)
# ---------------------------------------------------------------------------


class _HtmlToMarkdown(HTMLParser):
    """Lightweight converter for Gemini's rendered HTML back to Markdown.

    Handles the subset of HTML that Gemini actually produces:
    headings, bold/italic, code/pre, lists, links, paragraphs, br.
    """

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._tag_stack: list[str] = []
        self._list_stack: list[str] = []  # "ul" or "ol"
        self._ol_counter: list[int] = []
        self._in_pre = False
        self._in_code = False
        self._pre_lang = ""

    def _push(self, text: str) -> None:
        self._parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        self._tag_stack.append(tag)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self._push("\n\n" + "#" * level + " ")
        elif tag == "strong" or tag == "b":
            self._push("**")
        elif tag == "em" or tag == "i":
            self._push("*")
        elif tag == "code":
            if self._in_pre:
                # Code block language hint
                self._pre_lang = attr_dict.get("class", "").replace("language-", "")
            else:
                self._in_code = True
                self._push("`")
        elif tag == "pre":
            self._in_pre = True
            self._pre_lang = ""
            self._push("\n\n```")
        elif tag == "ul":
            self._list_stack.append("ul")
            self._push("\n")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._ol_counter.append(0)
            self._push("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ol_counter[-1] += 1
                self._push(f"{indent}{self._ol_counter[-1]}. ")
            else:
                self._push(f"{indent}- ")
        elif tag == "br":
            self._push("\n")
        elif tag == "p":
            self._push("\n\n")
        elif tag == "a":
            self._push("[")
        elif tag == "blockquote":
            self._push("\n\n> ")
        elif tag == "hr":
            self._push("\n\n---\n\n")
        elif tag == "table":
            self._push("\n\n")
        elif tag == "tr":
            self._push("| ")
        elif tag == "th" or tag == "td":
            pass  # Content handled in data
        elif tag == "div":
            # Generic div — just ensure separation
            pass

    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._push("\n\n")
        elif tag == "strong" or tag == "b":
            self._push("**")
        elif tag == "em" or tag == "i":
            self._push("*")
        elif tag == "code":
            if self._in_pre:
                pass  # Closing code inside pre
            else:
                self._in_code = False
                self._push("`")
        elif tag == "pre":
            self._in_pre = False
            self._push("```\n\n")
        elif tag == "ul":
            if self._list_stack:
                self._list_stack.pop()
            self._push("\n")
        elif tag == "ol":
            if self._list_stack:
                self._list_stack.pop()
            if self._ol_counter:
                self._ol_counter.pop()
            self._push("\n")
        elif tag == "li":
            self._push("\n")
        elif tag == "p":
            self._push("\n")
        elif tag == "a":
            self._push("]")  # href lost, but preserves text
        elif tag == "blockquote":
            self._push("\n")
        elif tag == "th":
            self._push(" | ")
        elif tag == "td":
            self._push(" | ")
        elif tag == "tr":
            self._push("\n")
        elif tag == "thead":
            # Add separator row after header
            self._push("|---|\n")

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            # First data in pre block — add language hint
            if self._pre_lang and self._parts and self._parts[-1].endswith("```"):
                self._parts[-1] += self._pre_lang
                self._pre_lang = ""
            self._push(data)
        else:
            self._push(data)

    def handle_entityref(self, name: str) -> None:
        self._push(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self._push(html.unescape(f"&#{name};"))

    def get_markdown(self) -> str:
        text = "".join(self._parts)
        # Clean up excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_markdown(html_content: str) -> str:
    """Convert HTML to Markdown. Falls back to plain text on error."""
    try:
        parser = _HtmlToMarkdown()
        parser.feed(html_content)
        result = parser.get_markdown()
        if result:
            return result
    except Exception:
        pass
    # Fallback: strip tags manually
    clean = re.sub(r"<[^>]+>", "", html_content)
    return html.unescape(clean).strip()


# ---------------------------------------------------------------------------
# Response Extraction
# ---------------------------------------------------------------------------


_JS_EXTRACT_MARKDOWN = """
(container) => {
    // Convert Gemini's rendered HTML DOM back to Markdown.
    // Handles Angular custom components (code-block, response-element).
    function walk(node) {
        if (node.nodeType === 3) return node.textContent;
        if (node.nodeType !== 1) return '';

        const tag = node.tagName.toLowerCase();
        const children = () => Array.from(node.childNodes).map(walk).join('');

        // Skip UI buttons (copy, share, etc.)
        if (tag === 'button') return '';
        if (tag === 'mat-icon') return '';

        // Code blocks: extract from data-test-id="code-content" or <pre>
        if (tag === 'code-block' || tag === 'response-element') {
            const codeEl = node.querySelector('[data-test-id="code-content"]')
                        || node.querySelector('pre code')
                        || node.querySelector('pre');
            if (codeEl) {
                // Get language from header
                const header = node.querySelector('.code-block-decoration span');
                const lang = header ? header.textContent.trim().toLowerCase() : '';
                return '\\n\\n```' + lang + '\\n' + codeEl.textContent.trim() + '\\n```\\n\\n';
            }
            return children();
        }

        // Standard HTML elements
        switch (tag) {
            case 'h1': return '\\n\\n# ' + children() + '\\n\\n';
            case 'h2': return '\\n\\n## ' + children() + '\\n\\n';
            case 'h3': return '\\n\\n### ' + children() + '\\n\\n';
            case 'h4': return '\\n\\n#### ' + children() + '\\n\\n';
            case 'h5': case 'h6': return '\\n\\n##### ' + children() + '\\n\\n';
            case 'strong': case 'b': return '**' + children() + '**';
            case 'em': case 'i': return '*' + children() + '*';
            case 'code':
                // Inline code (not inside pre/code-block)
                if (!node.closest('pre') && !node.closest('code-block'))
                    return '`' + node.textContent + '`';
                return node.textContent;
            case 'pre': return '\\n\\n```\\n' + node.textContent.trim() + '\\n```\\n\\n';
            case 'p': return '\\n\\n' + children() + '\\n';
            case 'br': return '\\n';
            case 'ul': return '\\n' + children() + '\\n';
            case 'ol': return '\\n' + children() + '\\n';
            case 'li': {
                const list = node.closest('ol');
                if (list) {
                    const idx = Array.from(list.children).indexOf(node) + 1;
                    return idx + '. ' + children().trim() + '\\n';
                }
                return '- ' + children().trim() + '\\n';
            }
            case 'a': return '[' + children() + '](' + (node.href || '') + ')';
            case 'blockquote': return '\\n> ' + children().trim() + '\\n';
            case 'hr': return '\\n\\n---\\n\\n';
            case 'table': return '\\n\\n' + children() + '\\n';
            case 'tr': return '| ' + children() + '\\n';
            case 'th': case 'td': return children().trim() + ' | ';
            case 'thead': return children() + '|---|\\n';
            // Skip decorative/structural elements
            case 'message-content': case 'div': case 'span':
                return children();
            default:
                return children();
        }
    }
    const raw = walk(container);
    // Clean up excessive whitespace
    return raw.replace(/\\n{3,}/g, '\\n\\n').trim();
}
"""


class _ResponseExtractor:
    """Extract response text from Gemini page as Markdown.

    Uses page.evaluate() with a JS DOM walker to handle Gemini's
    complex Angular HTML (custom components like code-block, response-element).
    """

    @staticmethod
    async def extract(page: Any) -> str:
        container = await _find_element(page, _Sel.RESPONSE_CONTAINER, timeout=5_000)
        text = await container.evaluate(_JS_EXTRACT_MARKDOWN)
        if not text or not text.strip():
            raise ExtractionError("Response container found but empty")
        return text.strip()

    @staticmethod
    async def extract_safe(page: Any) -> str:
        """Extract without raising — returns empty string on failure."""
        try:
            for sel in _Sel.RESPONSE_CONTAINER:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    last = elements.nth(count - 1)
                    text = await last.evaluate(_JS_EXTRACT_MARKDOWN)
                    if text and text.strip():
                        return text.strip()
        except Exception:
            pass
        return ""


# ---------------------------------------------------------------------------
# Result Normalizer
# ---------------------------------------------------------------------------


class _ResultNormalizer:
    """Convert raw text to LLMResponse."""

    ARTIFACT_PATTERNS = [
        re.compile(r"^Thinking\.{0,3}\s*\n", re.MULTILINE),
        re.compile(r"\n\s*(Copy|Share|More|Sources|Retry)\s*$", re.MULTILINE),
        re.compile(r"^\s*\d+\s*tokens?\s*$", re.MULTILINE),
    ]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count with CJK-aware heuristic.

        CJK characters average ~1.5 chars per token (each ideograph is
        typically its own token). Latin/ASCII text averages ~4 chars per
        token. We count CJK vs non-CJK characters and weight accordingly.
        """
        cjk_chars = 0
        latin_chars = 0
        for ch in text:
            if unicodedata.category(ch).startswith("Lo"):
                # "Lo" = Letter, other — covers CJK unified ideographs,
                # Hiragana, Katakana, Hangul, Thai, etc.
                cjk_chars += 1
            elif ch.strip():
                latin_chars += 1
            # whitespace/punctuation is roughly free (merged into adjacent tokens)

        tokens = cjk_chars / 1.5 + latin_chars / 4.0
        return max(1, int(tokens))

    @classmethod
    def normalize(
        cls, raw_text: str, elapsed_ms: float, prompt_chars_text: str
    ) -> LLMResponse:
        cleaned = raw_text
        for pat in cls.ARTIFACT_PATTERNS:
            cleaned = pat.sub("", cleaned)
        cleaned = cleaned.strip()

        return LLMResponse(
            text=cleaned,
            provider=ProviderName.GEMINI_WEB,
            model="gemini-3.0-thinking-web",
            input_tokens=cls._estimate_tokens(prompt_chars_text),
            output_tokens=cls._estimate_tokens(cleaned),
            latency_ms=elapsed_ms,
            cost_usd=0.0,
            finish_reason="stop",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Provider (public interface)
# ---------------------------------------------------------------------------


class GeminiWebProvider(BaseLLMProvider):
    """LLM provider that automates Gemini Web App via Playwright CDP.

    Implements BaseLLMProvider so it plugs directly into LLMRouter's
    existing fallback/strategy system. Upper-layer consumers are unaware
    this provider uses browser automation.

    Architecture (v2 — connection pool):
    - A shared ``_LoopThread`` runs a persistent asyncio event loop.
    - A ``_ConnectionPool`` maintains one Playwright + CDP connection
      with ``asyncio.Semaphore``-controlled concurrency (default 2 tabs).
    - A ``_RequestQueue`` orders requests by priority (user > default > background).
    - ``complete()`` submits work to the queue via the shared loop — no
      ``asyncio.run()`` per call, no ``threading.Lock`` serialization.
    """

    # Class-level shared resources (one loop/pool/queue for all instances,
    # since there's only one Chrome to talk to anyway)
    _loop_thread: _LoopThread | None = None
    _pool: _ConnectionPool | None = None
    _queue: _RequestQueue | None = None
    _init_lock = threading.Lock()
    _initialized = False

    def __init__(
        self,
        chrome_debug_url: str = "http://127.0.0.1:9222",
        gemini_url: str = "https://gemini.google.com/app",
        default_model: str = "gemini-3.0-thinking",
        timeout: float = 300.0,
        page_load_timeout: float = 15.0,
        max_retries: int = 2,
        retry_delay: float = 3.0,
        use_temporary_chat: bool = True,
        use_thinking_mode: bool = True,
        max_concurrent: int = 2,
    ):
        self._chrome_debug_url = chrome_debug_url
        self._gemini_url = gemini_url
        self._default_model_name = default_model
        self._timeout = timeout
        self._page_load_timeout = page_load_timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._use_temp_chat = use_temporary_chat
        self._use_thinking = use_thinking_mode
        self._max_concurrent = max_concurrent

        self._ensure_infra()

    def _ensure_infra(self) -> None:
        """Initialize class-level shared infrastructure (once)."""
        if GeminiWebProvider._initialized:
            return
        with GeminiWebProvider._init_lock:
            if GeminiWebProvider._initialized:
                return

            GeminiWebProvider._loop_thread = _LoopThread()
            GeminiWebProvider._pool = _ConnectionPool(
                self._chrome_debug_url, self._max_concurrent
            )
            GeminiWebProvider._queue = _RequestQueue()

            # Start the queue processor on the shared loop
            lt = GeminiWebProvider._loop_thread
            lt.ensure_running()
            lt.run_coro(GeminiWebProvider._queue.start())

            GeminiWebProvider._initialized = True
            atexit.register(GeminiWebProvider._shutdown_class)
            logger.info(
                "gemini_web | infra_init | max_concurrent=%d", self._max_concurrent
            )

    @classmethod
    def _shutdown_class(cls) -> None:
        """Clean shutdown on interpreter exit."""
        if cls._loop_thread and cls._queue:
            try:
                cls._loop_thread.run_coro(cls._queue.stop())
            except Exception:
                pass
        if cls._loop_thread and cls._pool:
            try:
                cls._loop_thread.run_coro(cls._pool.close())
            except Exception:
                pass
        if cls._loop_thread:
            cls._loop_thread.stop()
        cls._initialized = False

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.GEMINI_WEB

    @property
    def default_model(self) -> str:
        return self._default_model_name

    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute a completion request via Gemini Web App.

        Submits the request to the shared priority queue and blocks until
        the result is ready. Multiple callers can be in-flight concurrently
        (up to ``max_concurrent`` tabs).
        """
        caller = kwargs.get("caller", "unknown")
        priority = _caller_priority(caller)

        compiled = _PromptComposer.compile(messages)
        logger.info(
            "gemini_web | request_start | caller=%s | priority=%d | chars=%d",
            caller,
            priority,
            len(compiled),
        )

        assert self._loop_thread is not None
        assert self._queue is not None

        # Build a factory that creates the coroutine (so retries get a fresh one)
        def coro_factory():
            return self._complete_async(compiled, caller)

        return self._loop_thread.run_coro(
            self._queue.submit(coro_factory, priority=priority)
        )

    async def _complete_async(
        self,
        compiled: str,
        caller: str,
    ) -> LLMResponse:
        """Async implementation with retries."""
        last_error: GeminiWebError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._execute(compiled, caller)
            except (AuthenticationError, SelectorDriftError, GenerationTimeoutError):
                raise
            except GeminiWebError as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._retry_delay * (attempt + 1)
                    logger.warning(
                        "gemini_web | retry | attempt=%d | error=%s | delay=%.1fs",
                        attempt + 1,
                        type(e).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

    async def _execute(self, compiled_prompt: str, caller: str) -> LLMResponse:
        """Single execution attempt using the connection pool."""
        assert self._pool is not None
        start_ms = time.monotonic() * 1000
        browser = await self._pool.acquire()
        session = _PageSession(browser, self._gemini_url, self._page_load_timeout)

        try:
            await session.open()

            # Dismiss any promo/consent overlays before interacting
            await _OverlayDismisser.dismiss_all(session.page)

            if self._use_temp_chat:
                await _TemporaryChatController.ensure(session.page)

            # Dismiss again in case temp_chat triggered a new overlay
            await _OverlayDismisser.dismiss_all(session.page)

            if self._use_thinking:
                await _ThinkingModeSelector.ensure(session.page)

            await _PromptInputter.input_and_submit(session.page, compiled_prompt)
            await _GenerationWatcher.wait(session.page, timeout=self._timeout)

            raw_text = await _ResponseExtractor.extract(session.page)
            elapsed_ms = time.monotonic() * 1000 - start_ms

            result = _ResultNormalizer.normalize(raw_text, elapsed_ms, compiled_prompt)
            logger.info(
                "gemini_web | request_complete | caller=%s | chars=%d | latency_ms=%d",
                caller,
                len(result.text),
                int(elapsed_ms),
            )
            return result

        except GeminiWebError:
            await session.screenshot(f"{caller}_error")
            raise
        except Exception as e:
            await session.screenshot(f"{caller}_unexpected")
            raise PageCrashedError(f"Unexpected error: {e}")
        finally:
            await session.close()
            self._pool.release()

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMToolResponse:
        """Not supported — Gemini Web does not support structured tool_use."""
        raise NotImplementedError(
            "Gemini Web App does not support structured tool_use. "
            "Use complete() with tool instructions in the prompt."
        )

    def check_balance(self) -> dict[str, Any]:
        return {
            "provider": "gemini_web",
            "balance": "unlimited",
            "plan": "Google One Pro",
            "status": "ok",
        }

    def list_models(self) -> list[str]:
        return ["gemini-3.0-thinking-web"]
