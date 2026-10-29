"""adapters/docling: document conversion on docling-serve — any source in, the DoclingDocument and its renderings out.

The service, not the library: docling's models (layout, TableFormer, OCR) live in their own container
and process, so the app carries no torch. Conversions run as server tasks — submit, long-poll the
status, fetch the result — because the synchronous endpoint is cut off by the server's wait limit,
and a hundred-page filing outlives it. docling-serve answers a status poll at once (its `wait` is
not held), so the client paces the polls itself. One wreq client per app, opened and closed by the lifespan.

A source is a URL (`str`, fetched by the server), raw `bytes` (sent inline, base64) or a local `Path`
(read here, sent inline). The conversion options come from `DoclingSettings`; `options` overrides
them per call, in docling-serve's own names. The whole conversion is bounded by DOCLING_DEADLINE, carried as
each request's own timeout (what is left of it), never as a cancellation of a request in flight."""

import base64
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

import anyio
import wreq

from e_infra.adapters.base import BaseAdapter
from e_infra.adapters.ports import DocumentConversion
from e_infra.infra.config.docling import DoclingImages
from e_infra.infra.settings import settings as st

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.config.docling import DoclingSettings

DONE: Final[frozenset[str]] = frozenset({"success", "partial_success"})
FAILED: Final[frozenset[str]] = frozenset({"failure", "skipped"})
TIMED_OUT: Final = "TimedOut"
FORMS: Final[Mapping[str, str]] = {
    "markdown": "md_content",
    "document": "json_content",
    "html": "html_content",
    "text": "text_content",
    "doctags": "doctags_content",
}


##### ERRORS #####
class DoclingError(RuntimeError):
    """The server took the document and could not convert it: its task failed, or was skipped."""


##### ADAPTER #####
class DoclingAdapter(BaseAdapter):
    """One docling-serve client per app: conversions as server tasks, options from DoclingSettings."""

    name: ClassVar[str] = "docling"

    def __init__(self, settings: DoclingSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.docling if settings is None else settings
        self._client: wreq.Client | None = None

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
                    raise DoclingError(msg)
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
        client = self._common_connected()
        url = f"{self._conf.docling_url.rstrip('/')}{path}"
        limit = self._conf.docling_timeout.total_seconds()
        timeout = timedelta(seconds=min(limit, self._common_remaining(deadline)) if deadline is not None else limit)
        try:
            response = await (
                client.post(url, json=payload, timeout=timeout)
                if method == "POST"
                else client.get(url, timeout=timeout)
            )
            response.raise_for_status()
            return await response.json()
        except (wreq.TimeoutError, wreq.BodyError) as error:
            ### The bound covers the body too: cut while reading it, wreq says BodyError with a TimedOut source.
            match error:
                case wreq.BodyError() if TIMED_OUT not in str(error):
                    raise
                case _:
                    msg = f"docling {method} {path} timed out after {timeout.total_seconds():.1f}s"
                    raise TimeoutError(msg) from error

    @staticmethod
    def _common_remaining(deadline: float) -> float:
        """Seconds left before the deadline; none left is a TimeoutError, raised here, before any call."""
        match deadline - anyio.current_time():
            case left if left > 0:
                return left
            case _:
                msg = "docling conversion passed its DOCLING_DEADLINE"
                raise TimeoutError(msg)

    def _common_connected(self) -> wreq.Client:
        match self._client:
            case None:
                msg = "DoclingAdapter not connected: the lifespan opens it, handlers never do"
                raise RuntimeError(msg)
            case client:
                return client

    ############################################################

    ##### PUBLIC #####

    async def connect(self) -> None:
        self._client = wreq.Client(timeout=self._conf.docling_timeout)

    async def close(self) -> None:
        match self._client:
            case None:
                return
            case client:
                client.close()
                self._client = None

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

    async def ping(self) -> None:
        """docling-serve's readiness route."""
        with self._ping_guard():
            await self._common_call("GET", "/ready")
