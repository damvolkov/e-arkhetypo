"""Test doubles shared across the unit tree: the ASGI lifespan driver and its handshake frames."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from mcp import Client

type Connect = Callable[[], AbstractAsyncContextManager[Client]]


@asynccontextmanager
async def lifespan(app: Callable[..., Coroutine[Any, Any, None]]) -> AsyncGenerator[None]:
    """Drive an ASGI app's lifespan protocol: startup before the block, shutdown after."""
    inbox: asyncio.Queue[dict] = asyncio.Queue()
    outbox: asyncio.Queue[dict] = asyncio.Queue()
    runner = asyncio.create_task(app({"type": "lifespan", "asgi": {"version": "3.0"}}, inbox.get, outbox.put))
    await inbox.put({"type": "lifespan.startup"})
    started = await outbox.get()
    assert started["type"] == "lifespan.startup.complete", started
    try:
        yield
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        await outbox.get()
        await runner
