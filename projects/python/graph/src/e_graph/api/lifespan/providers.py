"""api.lifespan.providers: open every provider on one exit stack.

The concern owns its subtree as a typed section: `ProvidersState` (declared beside the RunState that exposes it to
every node) names each provider by the port the consumers (api.deps, routers, processors, nodes) may ask of it, so the
graph carries contracts, not classes. This is the composition root's one place that names a concrete class: each
provider is a singleton built here, enters the shared `AsyncExitStack` in field order — the HTTP pool before the
docling driver that rides it — and they close in reverse when the stack unwinds. Every provider is one line per block —
its import, its field, its construction — so an exported project that drops one loses exactly those lines. Their health
is surveyed by the engine the services lifespan builds over them."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.state import ProvidersState
from infra.logger import logger
from providers.adapters.pages.liteparse import LiteparseAdapter
from providers.drivers.documents.docling import DoclingDriver
from providers.drivers.http.wreq import WreqDriver
from providers.drivers.store.redis import RedisDriver
from providers.drivers.store.sqlite import SqliteDriver
from providers.drivers.telemetry.otel import OtelDriver


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open every provider on the exit stack, then mount the typed section under `system.infra.providers`."""
    system = AppState.of(app).system
    async with AsyncExitStack() as stack:
        enter = stack.enter_async_context
        store = await enter(SqliteDriver())
        telemetry = await enter(OtelDriver())
        redis = await enter(RedisDriver())
        http = await enter(WreqDriver())
        docling = await enter(DoclingDriver(http))
        pages = await enter(LiteparseAdapter())
        providers = ProvidersState(
            store=store, telemetry=telemetry, redis=redis, http=http, docling=docling, pages=pages
        )
        system.infra.providers = providers
        logger.info("providers ready", providers=sorted(providers.named), step="START")
        yield
    logger.info("providers closed", step="STOP")
