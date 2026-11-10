"""providers/drivers/documents/docling: document conversion on docling-serve — any source in, the DoclingDocument out.

The service, not the library: docling's models (layout, TableFormer, OCR) live in their own container
and process, so the app carries no torch. Conversions run as server tasks — submit, long-poll the
status, fetch the result — because the synchronous endpoint is cut off by the server's wait limit,
and a hundred-page filing outlives it. docling-serve answers a status poll at once (its `wait` is
not held), so the driver paces the polls itself. It speaks through an `HTTPPort` received by constructor, absolute
URLs on the `url` it is given: the process holds one HTTP pool, not one per service.

A source is a URL (`str`, fetched by the server), raw `bytes` (sent inline, base64) or a local `Path`
(read here, sent inline). The conversion options are the `DoclingOptions` it is built with; `options` overrides
them per call, in docling-serve's own names. The whole conversion is bounded by `deadline`, carried as
each request's own timeout (what is left of it), never as a cancellation of a request in flight.

docling is optional to whoever reads documents: `present` is how a composition root opens it — the driver, entered on
the root's exit stack, when `url` names a server that answers; None otherwise, said once and why."""

import base64
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Self, TypedDict, Unpack

import anyio
import msgspec

from e_infra.infra.config.providers import DoclingImages
from e_infra.infra.errors import DocumentError, HTTPError, HTTPTimeoutError, ProviderError
from e_infra.infra.logger import logger
from e_infra.ports.documents import Document, DocumentConversion
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from contextlib import AsyncExitStack

    from pydantic import HttpUrl

    from e_infra.infra.config.providers import DoclingBackend, DoclingFormat, DoclingTables
    from e_infra.infra.payload import JSON
    from e_infra.ports.http import HTTPPort

DONE: Final[frozenset[str]] = frozenset({"success", "partial_success"})
FAILED: Final[frozenset[str]] = frozenset({"failure", "skipped"})


##### WIRE #####
class DoclingContent(msgspec.Struct, frozen=True, kw_only=True):
    """The forms of a converted document, under docling-serve's own names; the ones not asked for are absent."""

    filename: str | None = None
    md_content: str | None = None
    json_content: Document | None = None
    html_content: str | None = None
    text_content: str | None = None
    doctags_content: str | None = None


class DoclingResult(msgspec.Struct, frozen=True, kw_only=True):
    """The slice of a task's result this driver reads; every other field is ignored."""

    status: str | None = None
    document: DoclingContent | None = None
    errors: tuple[Document, ...] | None = None
    processing_time: float | None = None


##### OPTIONS #####
class DoclingOptions(TypedDict):
    """The driver's keyword arguments past its URL: bounds first, then the conversion in the settings' own names."""

    timeout: timedelta
    deadline: timedelta
    poll: timedelta
    page_timeout: timedelta | None
    formats: tuple[DoclingFormat, ...]
    images: DoclingImages
    images_scale: float
    tables: DoclingTables
    ocr: bool
    force_ocr: bool
    ocr_engine: str
    ocr_lang: tuple[str, ...]
    backend: DoclingBackend
    formulas: bool
    pictures: bool
    charts: bool
    code: bool


##### DRIVER #####
class DoclingDriver:
    """docling-serve behind `DocumentPort`: conversions as server tasks, options from DoclingSettings."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "docling-serve", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, fork_safe=True
    )

    def __init__(self, http: HTTPPort, *, url: HttpUrl | None, **options: Unpack[DoclingOptions]) -> None:
        self._http = http
        self._conf = options
        match url:
            case None:
                msg = "DOCLING_URL is unset: there is no docling-serve to speak to"
                raise DocumentError(msg)
            case _:
                self._url = str(url).rstrip("/")

    ##### PRIVATE METHODS #####

    async def _convert_source(self, source: str | bytes | Path, filename: str | None) -> dict[str, JSON]:
        """The source as docling-serve takes it: a URL it fetches, or the bytes inline."""
        match source:
            case str():
                return {"kind": "http", "url": source}
            case Path():
                raw = await anyio.Path(source).read_bytes()
                return self._convert_inline(raw, filename or source.name)
            case bytes():
                return self._convert_inline(source, filename or "document")
            case other:
                msg = f"a document source is a URL (str), bytes or a Path, not {type(other).__name__}"
                raise TypeError(msg)

    @staticmethod
    def _convert_inline(raw: bytes, filename: str) -> dict[str, JSON]:
        return {"kind": "file", "base64_string": base64.b64encode(raw).decode(), "filename": filename}

    def _convert_options(self, overrides: Mapping[str, JSON] | None) -> dict[str, JSON]:
        """The configured conversion in docling-serve's names, the call's overrides on top."""
        conf = self._conf
        timeout = conf["page_timeout"]
        configured: dict[str, JSON] = {
            "to_formats": [str(form) for form in conf["formats"]],
            "image_export_mode": str(conf["images"]),
            "include_images": conf["images"] is not DoclingImages.PLACEHOLDER,
            "images_scale": conf["images_scale"],
            "table_mode": str(conf["tables"]),
            "do_ocr": conf["ocr"],
            "force_ocr": conf["force_ocr"],
            "ocr_engine": conf["ocr_engine"],
            "pdf_backend": str(conf["backend"]),
            "do_formula_enrichment": conf["formulas"],
            "do_picture_classification": conf["pictures"],
            "do_chart_extraction": conf["charts"],
            "do_code_enrichment": conf["code"],
            "document_timeout": timeout.total_seconds() if timeout is not None else None,
            **({"ocr_lang": list(conf["ocr_lang"])} if conf["ocr_lang"] else {}),
        }
        return configured | dict(overrides or {})

    async def _convert_wait(self, task: str, deadline: float) -> None:
        """Poll the task until it settles, DOCLING_POLL apart (also sent as `wait`, for servers that hold the poll),
        never past the deadline."""
        interval = self._conf["poll"].total_seconds()
        ### a real loop: polling is iteration over time, and recursion here would grow the stack once per poll.
        while True:
            status = await self._common_call("GET", f"/v1/status/poll/{task}?wait={interval}", deadline)
            match status.get("task_status"):
                case state if state in DONE:
                    return
                case state if state in FAILED:
                    msg = f"docling task {task} {state}: {status.get('error_message') or 'no reason given'}"
                    logger.error("docling task failed", task=task, state=state, reason=status.get("error_message"))
                    raise DocumentError(msg)
                case _:
                    await anyio.sleep(min(interval, self._common_remaining(deadline)))

    @staticmethod
    def _convert_result(body: Mapping[str, JSON]) -> DocumentConversion:
        result = msgspec.convert(body, DoclingResult, strict=False)
        document = result.document or DoclingContent()
        return DocumentConversion(
            filename=document.filename,
            status=result.status,
            markdown=document.md_content,
            document=document.json_content or {},
            html=document.html_content,
            text=document.text_content,
            doctags=document.doctags_content,
            errors=result.errors or (),
            seconds=result.processing_time or 0.0,
        )

    async def _common_call(
        self, method: str, path: str, deadline: float | None = None, payload: JSON = None
    ) -> Mapping[str, JSON]:
        """One call to the server, JSON both ways, bounded by DOCLING_TIMEOUT and what is left of the deadline.

        The bound travels as the request's own timeout, never as a cancellation: a Rust future cancelled
        mid-flight surfaces as a bare CancelledError, which would cancel the caller's whole task group."""
        url = f"{self._url}{path}"
        limit = self._conf["timeout"].total_seconds()
        within = timedelta(seconds=min(limit, self._common_remaining(deadline)) if deadline is not None else limit)
        try:
            body = await (
                self._http.post(url, payload, within=within) if method == "POST" else self._http.get(url, within=within)
            )
        except HTTPTimeoutError as error:
            msg = f"docling {method} {path} timed out after {within.total_seconds():.1f}s"
            logger.error("docling timed out", method=method, path=path, seconds=within.total_seconds())
            raise HTTPTimeoutError(msg) from error
        match body:
            case Mapping():
                return body
            case _:
                msg = f"docling {method} {path} answered a body that is not an object"
                raise HTTPError(msg)

    @staticmethod
    def _common_remaining(deadline: float) -> float:
        """Seconds left before the deadline; none left is a TimeoutError, raised here, before any call."""
        match deadline - anyio.current_time():
            case left if left > 0:
                return left
            case _:
                msg = "docling conversion passed its DOCLING_DEADLINE"
                raise TimeoutError(msg)

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        """Nothing to open: the HTTP pool is the lifespan's, opened before this driver."""
        logger.info("docling opened", url=self._url)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""
        logger.info("docling closed")

    async def convert(
        self, source: str | bytes | Path, *, filename: str | None = None, options: Mapping[str, JSON] | None = None
    ) -> DocumentConversion:
        """Convert one document as a server task, within DOCLING_DEADLINE: submit, wait, fetch."""
        request = {
            "sources": [await self._convert_source(source, filename)],
            "options": self._convert_options(options),
            "target": {"kind": "inbody"},
        }
        deadline = anyio.current_time() + self._conf["deadline"].total_seconds()
        match await self._common_call("POST", "/v1/convert/source/async", deadline, request):
            case {"task_id": str() as task}:
                logger.debug("docling submitted", task=task, filename=filename)
                await self._convert_wait(task, deadline)
                return self._convert_result(await self._common_call("GET", f"/v1/result/{task}", deadline))
            case submitted:
                msg = f"docling accepted the conversion without a task id: {dict(submitted)}"
                raise DocumentError(msg)

    @classmethod
    async def present(
        cls, stack: AsyncExitStack, http: HTTPPort, *, url: HttpUrl | None, **options: Unpack[DoclingOptions]
    ) -> DoclingDriver | None:
        """The driver open on `stack` when DOCLING_URL names a docling-serve that answers its readiness route; None
        otherwise, with one warning that says why — what reads documents then is the caller's, never this driver's."""
        match url:
            case None:
                reason = "DOCLING_URL unset"
            case _:
                driver = await stack.enter_async_context(cls(http, url=url, **options))
                try:
                    await driver._common_call("GET", "/ready")
                except ProviderError as error:
                    reason = f"{str(url).rstrip('/')} unanswered: {error}"
                else:
                    return driver
        logger.warning("docling absent", reason=reason)
        return None

    async def health(self) -> bool:
        """docling-serve's readiness route."""
        try:
            await self._common_call("GET", "/ready")
        except ProviderError as error:
            logger.warning("docling unhealthy", error=str(error))
            raise
        return True
