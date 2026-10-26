"""api.lifespan.adapters: open every external edge on one exit stack.

The concern owns its subtree as a typed section: `AdaptersState` names each edge by the Port the
consumers (api.deps, routers) may ask of it, so the graph carries contracts, not classes. Each
adapter is a singleton built here, enters the shared `AsyncExitStack` in field order, and they close
in reverse when the stack unwinds. Every edge is one line per block — its import, its field, its
construction — so an exported project that drops an adapter loses exactly those lines.

Every edge is pinged at once (`AdaptersState.ping`, each under PING_TIMEOUT, so the whole takes the slowest): right
after they open — one log event each, never a failed start — and on every `GET /ready`. Required is `store`, the
edge the app's records live on; every other edge is reported, never blocking."""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, fields
from datetime import timedelta
from typing import Final, cast

from litestar import Litestar

from adapters.base import AdapterPing, BaseAdapter
from adapters.http import HttpAdapter
from adapters.ports import HttpPort, StorePort
from adapters.redis import RedisAdapter
from adapters.sqlite import SQLiteAdapter
from e_api.api.state import AppState
from infra.logger import logger
from infra.settings import settings as st

### the edges a ready service cannot do without; a role not here is optional.
REQUIRED: Final[frozenset[str]] = frozenset({"store"})


##### SECTION #####
@dataclass(frozen=True, slots=True)
class AdaptersState:
    """The typed adapters section: fields named by role, typed by the port the role speaks.

    `store` is the KV edge the app's records live on; any further field is an optional edge the
    export may drop. The adapters are singletons — factory machinery comes later."""

    store: StorePort
    redis: StorePort
    http: HttpPort

    async def ping(self, limit: timedelta) -> tuple[AdapterPing, ...]:
        """Every edge pinged at once, each within `limit`, in field order; the REQUIRED ones decide readiness."""
        ### every field is a concrete adapter behind its port, and every adapter pings.
        named = {field.name: cast("BaseAdapter", getattr(self, field.name)) for field in fields(self)}
        return await BaseAdapter.survey(named, limit, REQUIRED)


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open every external edge on the exit stack, then mount the typed section under `system.adapters`."""
    system = AppState.of(app).system
    edges = AdaptersState(
        store=SQLiteAdapter(),
        redis=RedisAdapter(),
        http=HttpAdapter(),
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
