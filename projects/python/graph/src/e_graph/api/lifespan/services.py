"""api.lifespan.services: assemble the engines that travel with the app — crypto and the processors.

Crypto and the readers over the adapters are pure in-process objects: this concern owns no resource to close. The
instrument and the logic mount their own branches, each in its lifespan (`instrument`, `logic`).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.state import ProcessorsState
from infra.logger import logger
from infra.settings import settings as st
from ops.crypto import Crypto
from processors.doc import DocProcessor


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Assemble the engines that travel with the app: crypto and the processors."""
    system = AppState.of(app).system
    system.crypto = Crypto(st.crypto)
    ### readers over the adapters: documents through liteparse and the docling edge, hybrid by page.
    system.infra.processors = ProcessorsState(doc=DocProcessor(system.infra.adapters.docling))
    logger.info("services ready", step="START")
    yield
