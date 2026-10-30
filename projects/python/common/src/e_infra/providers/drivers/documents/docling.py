"""providers/drivers/documents/docling: document conversion on docling-serve — any source in, the DoclingDocument out.

The service, not the library: docling's models (layout, TableFormer, OCR) live in their own container
and process, so the app carries no torch. Conversions run as server tasks — submit, long-poll the
status, fetch the result — because the synchronous endpoint is cut off by the server's wait limit,
and a hundred-page filing outlives it. docling-serve answers a status poll at once (its `wait` is
not held), so the driver paces the polls itself. It speaks through an `HttpPort` received by constructor, absolute
URLs on DOCLING_URL: the process holds one HTTP pool, not one per service.

A source is a URL (`str`, fetched by the server), raw `bytes` (sent inline, base64) or a local `Path`
(read here, sent inline). The conversion options come from `DoclingSettings`; `options` overrides
them per call, in docling-serve's own names. The whole conversion is bounded by DOCLING_DEADLINE, carried as
each request's own timeout (what is left of it), never as a cancellation of a request in flight."""

import base64
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

import anyio

from e_infra.infra.config.docling import DoclingImages
from e_infra.infra.errors import DocumentError, HttpTimeoutError, ProviderError
from e_infra.infra.settings import settings as st
from e_infra.ports.documents import DocumentConversion
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.config.docling import DoclingSettings
    from e_infra.ports.http import HttpPort

DONE: Final[frozenset[str]] = frozenset({"success", "partial_success"})
FAILED: Final[frozenset[str]] = frozenset({"failure", "skipped"})
FORMS: Final[Mapping[str, str]] = {
    "markdown": "md_content",
    "document": "json_content",
    "html": "html_content",
    "text": "text_content",
    "doctags": "doctags_content",
}


##### DRIVER #####
class DoclingDriver:
    """docling-serve behind `DocumentPort`: conversions as server tasks, options from DoclingSettings."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "docling-serve", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, fork_safe=True
    )

    def __init__(self, http: HttpPort, settings: DoclingSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.docling if settings is None else settings
        self._http = http

    ##### PRIVATE METHODS #####

    async def _convert_source(self, source: str | bytes | Path, filename: str) -> dict[str, Any]:
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
    def _convert_inline(raw: bytes, filename: str) -> dict[str, Any]:
        return {"kind": "file", "base64_string": base64.b64encode(raw).decode(), "filename": filename}

    def _convert_options(self, overrides: Mapping[str, object] | None) -> dict[str, Any]:
        """The configured conversion in docling-serve's names, the call's overrides on top."""
        conf = self._conf
        timeout = conf.docling_page_timeout
        configured = {
            "to_formats": [str(form) for form in conf.docling_formats],
            "image_export_mode": str(conf.docling_images),
            "include_images": conf.docling_images is not DoclingImages.PLACEHOLDER,
            "images_scale": conf.docling_images_scale,
            "table_mode": str(conf.docling_tables),
            "do_ocr": conf.docling_ocr,
            "force_ocr": conf.docling_force_ocr,
            "ocr_engine": conf.docling_ocr_engine,
            "pdf_backend": str(conf.docling_backend),
            "do_formula_enrichment": conf.docling_formulas,
            "do_picture_classification": conf.docling_pictures,
            "do_chart_extraction": conf.docling_charts,
            "do_code_enrichment": conf.docling_code,
            "document_timeout": timeout.total_seconds() if timeout is not None else None,
            **({"ocr_lang": list(conf.docling_ocr_lang)} if conf.docling_ocr_lang else {}),
        }
        return configured | dict(overrides or {})

    async def _convert_wait(self, task: str, deadline: float) -> None:
        """Poll the task until it settles, DOCLING_POLL apart (also sent as `wait`, for servers that hold the poll),
        never past the deadline."""
        interval = self._conf.docling_poll.total_seconds()
        ### a real loop: polling is iteration over time, and recursion here would grow the stack once per poll.
        while True:
            status = await self._common_call("GET", f"/v1/status/poll/{task}?wait={interval}", deadline)
            match status.get("task_status"):
                case state if state in DONE:
                    return
                case state if state in FAILED:
                    msg = f"docling task {task} {state}: {status.get('error_message') or 'no reason given'}"
                    raise DocumentError(msg)
                case _:
                    await anyio.sleep(min(interval, self._common_remaining(deadline)))

    @staticmethod
    def _convert_result(body: dict[str, Any]) -> DocumentConversion:
        document = body.get("document") or {}
        forms = {field: document.get(key) for field, key in FORMS.items()}
        return DocumentConversion(
            filename=document.get("filename", ""),
            status=str(body.get("status", "")),
            **{field: value for field, value in forms.items() if value is not None},
            errors=tuple(body.get("errors") or ()),
            seconds=float(body.get("processing_time") or 0.0),
        )

    async def _common_call(
        self, method: str, path: str, deadline: float | None = None, payload: object = None
    ) -> dict[str, Any]:
        """One call to the server, JSON both ways, bounded by DOCLING_TIMEOUT and what is left of the deadline.

        The bound travels as the request's own timeout, never as a cancellation: a Rust future cancelled
        mid-flight surfaces as a bare CancelledError, which would cancel the caller's whole task group."""
        url = f"{self._conf.docling_url.rstrip('/')}{path}"
        limit = self._conf.docling_timeout.total_seconds()
        within = timedelta(seconds=min(limit, self._common_remaining(deadline)) if deadline is not None else limit)
        try:
            return await (
                self._http.post(url, payload, as_=dict[str, Any], within=within)
                if method == "POST"
                else self._http.get(url, as_=dict[str, Any], within=within)
            )
        except HttpTimeoutError as error:
            msg = f"docling {method} {path} timed out after {within.total_seconds():.1f}s"
            raise HttpTimeoutError(msg) from error

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
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def convert(
        self, source: str | bytes | Path, *, filename: str = "", options: Mapping[str, object] | None = None
    ) -> DocumentConversion:
        """Convert one document as a server task, within DOCLING_DEADLINE: submit, wait, fetch."""
        request = {
            "sources": [await self._convert_source(source, filename)],
            "options": self._convert_options(options),
            "target": {"kind": "inbody"},
        }
        deadline = anyio.current_time() + self._conf.docling_deadline.total_seconds()
        task = (await self._common_call("POST", "/v1/convert/source/async", deadline, request))["task_id"]
        await self._convert_wait(task, deadline)
        return self._convert_result(await self._common_call("GET", f"/v1/result/{task}", deadline))

    async def health(self) -> bool:
        """docling-serve's readiness route."""
        try:
            await self._common_call("GET", "/ready")
        except ProviderError:
            return False
        return True
