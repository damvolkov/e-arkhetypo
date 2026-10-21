"""api.lifespan.adapters: open every external edge on one exit stack.

The concern owns its subtree as a typed section: `AdaptersState` (declared beside the RunState that
exposes it to every node) names each edge by the Port the consumers (api.deps, routers, nodes)
may ask of it, so the graph carries contracts, not classes. Each
adapter is a singleton built here, enters the shared `AsyncExitStack` in field order, and they close
in reverse when the stack unwinds. Every edge is one line per block — its import, its field, its
construction — so an exported project that drops an adapter loses exactly those lines.

Every edge is pinged at once (`AdaptersState.ping`, each under PING_TIMEOUT, so the whole takes the slowest): right
after they open — one log event each, never a failed start — and on every `GET /ready`. Required is `store`, the
edge the app's records live on; every other edge is reported, never blocking."""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import fields
from typing import cast

from litestar import Litestar

from adapters.docling import DoclingAdapter
from adapters.http import HttpAdapter
from adapters.otel import OtelAdapter
from adapters.redis import RedisAdapter
from adapters.sqlite import SQLiteAdapter
from core.logger import logger
from core.settings import settings as st
from e_graph.api.state import AppState
from e_graph.instrument.state import AdaptersState


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open every external edge on the exit stack, then mount the typed section under `system.adapters`."""
    system = AppState.of(app).system
    edges = AdaptersState(
        store=SQLiteAdapter(),
        telemetry=OtelAdapter(),
        redis=RedisAdapter(),
        http=HttpAdapter(),
        docling=DoclingAdapter(),
    )
    async with AsyncExitStack() as stack:
        ### each field is a concrete adapter behind its port: it enters the stack as the context manager it is.
        roles = tuple(field.name for field in fields(edges))
        _ = [
            await stack.enter_async_context(cast("AbstractAsyncContextManager[object]", getattr(edges, role)))
            for role in roles
        ]
        system.adapters = edges
        logger.info("adapters ready", edges=sorted(roles), step="START")
        _ = [
            (logger.info if ping.ok else logger.warning)(
                "adapter ping", adapter=ping.name, ok=ping.ok, required=ping.required, latency_ms=ping.latency,
                reason=ping.reason, step="START",
            )
            for ping in await edges.ping(st.ping.timeout)
        ]  # fmt: skip
        yield
    logger.info("adapters closed", step="STOP")
