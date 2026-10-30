"""api.lifespan.services: assemble what travels with the app over the providers — crypto, the engines, the processors.

Crypto, the health engine and the readers are pure in-process objects over the providers already open: this concern
owns no resource to close. The health engine surveys every provider at once (each under PING_TIMEOUT, so the whole
takes the slowest) right here — one log event each, never a failed start — and again on every `GET /ready`. Required
is `store`, the provider the app's records live on; every other one is reported, never blocking. The instrument and
the logic mount their own branches, each in its lifespan (`instrument`, `logic`)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.state import REQUIRED, EnginesState, ProcessorsState
from engines.health import HealthEngine
from infra.logger import logger
from infra.settings import settings as st
from ops.crypto import Crypto
from processors.doc import DocProcessor


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Assemble crypto, the engines and the processors, then log every provider's health once."""
    system = AppState.of(app).system
    providers = system.infra.providers
    system.crypto = Crypto(st.crypto)
    system.infra.engines = EnginesState(health=HealthEngine(providers.named, REQUIRED))
    ### readers over the providers: documents through liteparse and the docling driver, hybrid by page.
    system.infra.processors = ProcessorsState(doc=DocProcessor(providers.docling, providers.pages))
    _ = [
        (logger.info if health.ok else logger.warning)(
            "provider health", provider=health.name, ok=health.ok, required=health.required, latency_ms=health.latency,
            reason=health.reason, step="START",
        )
        for health in await system.infra.engines.health.survey()
    ]  # fmt: skip
    logger.info("services ready", step="START")
    yield
