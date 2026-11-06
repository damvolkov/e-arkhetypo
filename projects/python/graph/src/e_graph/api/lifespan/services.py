"""api.lifespan.services: assemble what travels with the app over the providers — crypto, the engines, the processors.

Crypto, the health engine and the readers are pure in-process objects over the providers already open: this concern
owns no resource to close. The health engine surveys every provider at once (each under PING_TIMEOUT, so the whole
takes the slowest) right here — one log event each, never a failed start — and again on every `GET /ready`. Required
is `store`, the provider the app's records live on; every other one is reported, never blocking. The instrument and
the logic mount their own branches, each in its lifespan (`instrument`, `logic`)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.engines.health import HealthEngine
from e_graph.infra.logger import logger
from e_graph.infra.settings import settings as st
from e_graph.instrument.state import REQUIRED, EnginesState, ProcessorsState
from e_graph.ops.crypto import Crypto, CryptoKeys
from e_graph.processors.doc import DocProcessor

if TYPE_CHECKING:
    from e_graph.ports.documents import DocumentPort
    from e_graph.ports.markdown import MarkdownPort
    from e_graph.ports.pages import PagesPort


##### ROOT #####
def doc(markdown: MarkdownPort, pages: PagesPort, docling: DocumentPort | None) -> DocProcessor:
    """The document reader over its three providers, DOC_*."""
    return DocProcessor(
        markdown,
        pages,
        docling,
        concurrency=st.DOC_CONCURRENCY,
        span=st.DOC_SPAN,
        gap=st.DOC_GAP,
        mode=st.DOC_MODE,
        route=st.DOC_ROUTE,
        tables=st.DOC_TABLES,
        max_input_bytes=st.DOC_MAX_INPUT_BYTES,
    )


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Assemble crypto, the engines and the processors, then log every provider's health once."""
    system = AppState.of(app).system
    providers = system.infra.providers
    system.crypto = Crypto(
        CryptoKeys(
            secret=st.CRYPTO__SECRET,
            alg=st.CRYPTO__ALG,
            enc=st.CRYPTO__ENC,
            private_key=st.CRYPTO__PRIVATE_KEY.get_secret_value(),
            hasher=st.CRYPTO__HASHER,
            bcrypt_rounds=st.CRYPTO__BCRYPT_ROUNDS,
        )
    )
    system.infra.engines = EnginesState(health=HealthEngine(providers.named, REQUIRED, st.PING_TIMEOUT))
    ### readers over the providers: documents through anytomd, liteparse and — when present — the docling driver.
    system.infra.processors = ProcessorsState(doc=doc(providers.markdown, providers.pages, providers.docling))
    _ = [
        (logger.info if health.ok else logger.warning)(
            "provider health", provider=health.name, ok=health.ok, required=health.required, latency_ms=health.latency,
            reason=health.reason, step="START",
        )
        for health in await system.infra.engines.health.survey()
    ]  # fmt: skip
    logger.info("services ready", step="START")
    yield
