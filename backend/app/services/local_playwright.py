"""Local Playwright browser service (no AgentBay dependency)."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class _BrowserSession:
    """In-memory browser session state."""

    playwright: object
    browser: object
    context: object
    page: object
    last_used: float


_SESSION_TTL_SECONDS = 15 * 60
_sessions: dict[tuple[str, str], _BrowserSession] = {}
_session_lock = asyncio.Lock()


def _session_key(agent_id: Optional[uuid.UUID], session_id: str) -> tuple[str, str]:
    aid = str(agent_id) if agent_id else "no-agent"
    sid = (session_id or "default").strip() or "default"
    return aid, sid


async def _close_session(session: _BrowserSession) -> None:
    """Close a single browser session safely."""
    try:
        await session.context.close()
    except Exception:
        pass
    try:
        await session.browser.close()
    except Exception:
        pass
    try:
        await session.playwright.stop()
    except Exception:
        pass


async def _cleanup_expired_sessions() -> None:
    """Close and remove expired sessions."""
    now = time.time()
    expired_keys: list[tuple[str, str]] = []
    for key, session in _sessions.items():
        if now - session.last_used > _SESSION_TTL_SECONDS:
            expired_keys.append(key)

    for key in expired_keys:
        session = _sessions.pop(key, None)
        if session:
            await _close_session(session)


async def _get_or_create_session(
    agent_id: Optional[uuid.UUID],
    session_id: str,
    headless: bool,
) -> _BrowserSession:
    """Get an existing session or create a new one."""
    key = _session_key(agent_id, session_id)

    async with _session_lock:
        await _cleanup_expired_sessions()

        existing = _sessions.get(key)
        if existing:
            existing.last_used = time.time()
            return existing

        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"
            ) from e

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        session = _BrowserSession(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            last_used=time.time(),
        )
        _sessions[key] = session
        return session


async def close_local_browser_session(
    agent_id: Optional[uuid.UUID],
    session_id: str = "default",
) -> bool:
    """Close local browser session by key."""
    key = _session_key(agent_id, session_id)
    async with _session_lock:
        session = _sessions.pop(key, None)
    if not session:
        return False
    await _close_session(session)
    return True


async def run_local_browser(
    agent_id: Optional[uuid.UUID],
    ws: Path,
    arguments: dict,
) -> str:
    """Execute local browser action with Playwright."""
    action = str(arguments.get("action", "")).strip().lower()
    session_id = str(arguments.get("session_id", "default")).strip() or "default"
    timeout_ms = int(arguments.get("timeout_ms", 15000))
    headless = bool(arguments.get("headless", True))

    if action not in {"goto", "click", "type", "screenshot", "close"}:
        return "Unsupported action. Use one of: goto, click, type, screenshot, close"

    if action == "close":
        closed = await close_local_browser_session(agent_id, session_id=session_id)
        return (
            f"Local browser session closed: {session_id}"
            if closed
            else f"No active local browser session: {session_id}"
        )

    session = await _get_or_create_session(agent_id, session_id, headless=headless)
    page = session.page
    session.last_used = time.time()

    try:
        if action == "goto":
            url = str(arguments.get("url", "")).strip()
            if not url:
                return "Missing required argument 'url' for action=goto"
            wait_for = str(arguments.get("wait_for", "domcontentloaded")).strip() or "domcontentloaded"
            await page.goto(url, wait_until=wait_for, timeout=timeout_ms)
            title = await page.title()
            return f"Navigated to: {page.url}\nTitle: {title}"

        if action == "click":
            selector = str(arguments.get("selector", "")).strip()
            if not selector:
                return "Missing required argument 'selector' for action=click"
            await page.click(selector, timeout=timeout_ms)
            return f"Clicked: {selector}\nCurrent URL: {page.url}"

        if action == "type":
            selector = str(arguments.get("selector", "")).strip()
            text = str(arguments.get("text", ""))
            if not selector:
                return "Missing required argument 'selector' for action=type"
            await page.fill(selector, text, timeout=timeout_ms)
            return f"Typed into: {selector}\nCharacters: {len(text)}"

        # action == "screenshot"
        save_to_workspace = bool(arguments.get("save_to_workspace", True))
        if not save_to_workspace:
            return "save_to_workspace=false is not supported in local_browser. Set true to save screenshot."

        shots_dir = ws / "workspace"
        shots_dir.mkdir(parents=True, exist_ok=True)
        file_path = shots_dir / f"local_browser_{int(time.time())}.png"
        await page.screenshot(path=str(file_path), full_page=False)
        rel_path = file_path.relative_to(ws)
        return f"Screenshot saved: `{rel_path.as_posix()}`"

    except Exception as e:
        logger.exception("[LocalBrowser] action failed")
        return f"Local browser action failed: {str(e)[:300]}"
