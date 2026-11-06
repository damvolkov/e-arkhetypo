"""api.lifespan.providers: open every provider on one exit stack.

The concern owns its subtree as a typed section: `ProvidersState` (declared beside the RunState that exposes it to
every node) names each provider by the port the consumers (api.deps, routers, processors, nodes) may ask of it, so the
graph carries contracts, not classes. This is the composition root's one place that names a concrete class: each
provider is a singleton built here, enters the shared `AsyncExitStack` in field order — the HTTP pool before the
docling driver that rides it — and they close in reverse when the stack unwinds. Every provider is one line per block —
its import, its field, its construction — so an exported project that drops one loses exactly those lines. Their health
is surveyed by the engine the services lifespan builds over them.

docling is the one optional provider: `DoclingDriver.present` opens it only when DOCLING_URL names a docling-serve
that answers; when it does not, the section holds None in its place, said once — liteparse and anytomd read every
document, and nothing more is said per document. The CLI's rehearsal opens it the same way."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.infra.logger import logger
from e_graph.infra.settings import settings as st
from e_graph.instrument.state import ProvidersState
from e_graph.providers.adapters.markdown.anytomd import AnytomdAdapter
from e_graph.providers.adapters.pages.liteparse import LiteparseAdapter
from e_graph.providers.drivers.documents.docling import DoclingDriver
from e_graph.providers.drivers.http.wreq import WreqDriver
from e_graph.providers.drivers.store.redis import RedisDriver
from e_graph.providers.drivers.store.sqlite import SqliteDriver
from e_graph.providers.drivers.telemetry.otel import OTelDriver

if TYPE_CHECKING:
    from e_graph.ports.http import HTTPPort


##### ROOT — the readers every root opens: this lifespan and the cli's rehearsal #####
def wreq() -> WreqDriver:
    """The process's HTTP driver, HTTP_*."""
    return WreqDriver(base_url=st.HTTP_BASE_URL, timeout=st.HTTP_TIMEOUT, agent=st.HTTP_AGENT, headers=st.HTTP_HEADERS)


async def present(stack: AsyncExitStack, http: HTTPPort) -> DoclingDriver | None:
    """The docling driver open on `stack` when DOCLING_URL answers, DOCLING_*; None otherwise."""
    return await DoclingDriver.present(
        stack,
        http,
        url=st.DOCLING_URL,
        timeout=st.DOCLING_TIMEOUT,
        deadline=st.DOCLING_DEADLINE,
        poll=st.DOCLING_POLL,
        page_timeout=st.DOCLING_PAGE_TIMEOUT,
        formats=st.DOCLING_FORMATS,
        images=st.DOCLING_IMAGES,
        images_scale=st.DOCLING_IMAGES_SCALE,
        tables=st.DOCLING_TABLES,
        ocr=st.DOCLING_OCR,
        force_ocr=st.DOCLING_FORCE_OCR,
        ocr_engine=st.DOCLING_OCR_ENGINE,
        ocr_lang=st.DOCLING_OCR_LANG,
        backend=st.DOCLING_BACKEND,
        formulas=st.DOCLING_FORMULAS,
        pictures=st.DOCLING_PICTURES,
        charts=st.DOCLING_CHARTS,
        code=st.DOCLING_CODE,
    )


def liteparse() -> LiteparseAdapter:
    """The fast page reader, DOC_WORKERS / DOC_OCR / DOC_TESSDATA / DOC_OCR_LANGUAGE."""
    return LiteparseAdapter(
        workers=st.DOC_WORKERS, ocr=st.DOC_OCR, tessdata=st.DOC_TESSDATA, ocr_language=st.DOC_OCR_LANGUAGE
    )


def anytomd() -> AnytomdAdapter:
    """The any-format reader, MD_*."""
    return AnytomdAdapter(
        vision_base_url=st.MD_VISION_BASE_URL,
        vision_api_key=st.MD_VISION_API_KEY,
        vision_model=st.MD_VISION_MODEL,
        vision_prompt=st.MD_VISION_PROMPT,
        image_describe=st.MD_IMAGE_DESCRIBE,
        max_input_bytes=st.MD_MAX_INPUT_BYTES,
        pdf_workers=st.MD_PDF_WORKERS,
        pdf_ocr=st.MD_PDF_OCR,
        pdf_language=st.MD_PDF_LANGUAGE,
        strict=st.MD_STRICT,
        extract_comments=st.MD_EXTRACT_COMMENTS,
    )


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open every provider on the exit stack, then mount the typed section under `system.infra.providers`."""
    system = AppState.of(app).system
    async with AsyncExitStack() as stack:
        enter = stack.enter_async_context
        store = await enter(SqliteDriver(path=st.DB_PATH, timeout=st.DB_TIMEOUT))
        telemetry = await enter(
            OTelDriver(
                endpoint=st.OTEL_ENDPOINT,
                protocol=st.OTEL_PROTOCOL,
                headers=st.OTEL_HEADERS,
                timeout=st.OTEL_TIMEOUT,
                flush=st.OTEL_FLUSH,
                service=st.OTEL_SERVICE,
                attributes=st.OTEL_ATTRIBUTES,
                sample=st.OTEL_SAMPLE,
            )
        )
        redis = await enter(RedisDriver(url=st.REDIS_URL, pool=st.REDIS_POOL, timeout=st.REDIS_TIMEOUT))
        http = await enter(wreq())
        docling = await present(stack, http)
        pages = await enter(liteparse())
        markdown = await enter(anytomd())
        providers = ProvidersState(
            store=store, telemetry=telemetry, redis=redis, http=http, docling=docling, pages=pages, markdown=markdown
        )
        system.infra.providers = providers
        logger.info("providers ready", providers=sorted(providers.named), step="START")
        yield
    logger.info("providers closed", step="STOP")
