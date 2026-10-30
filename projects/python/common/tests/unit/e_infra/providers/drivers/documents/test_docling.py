"""e_infra/providers/drivers/documents/docling: the task lifecycle, every source kind, options, failure and deadline — offline."""

import base64
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import wreq

from e_infra.infra.config.providers.drivers.documents.docling import (
    DoclingBackend,
    DoclingFormat,
    DoclingImages,
    DoclingSettings,
    DoclingTables,
)
from e_infra.infra.errors import DocumentError, HttpError, HttpTimeoutError
from e_infra.ports.documents import DocumentConversion, DocumentPort
from e_infra.providers.drivers.documents.docling import DoclingDriver
from unit.e_infra.providers.drivers.conftest import DOWN

if TYPE_CHECKING:
    from pathlib import Path

    from e_infra.ports.http import HttpPort


def settings(url: str, **values: Any) -> DoclingSettings:
    return DoclingSettings(url=url, poll=timedelta(milliseconds=5), **values)


async def test_port_shape(http: HttpPort) -> None:
    assert isinstance(DoclingDriver(http, DoclingSettings()), DocumentPort)
    assert DoclingDriver.spec.name == "docling-serve"


async def test_url_converted_as_a_task(docling_server: Any, http: HttpPort) -> None:
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        conversion = await adapter.convert("https://example.org/paper")
    assert conversion == DocumentConversion(
        filename="paper.pdf", status="success", markdown="# Title", document={"tables": []}, seconds=1.5
    )
    assert docling_server.sent["sources"] == [{"kind": "http", "url": "https://example.org/paper"}]
    assert docling_server.sent["target"] == {"kind": "inbody"}
    assert docling_server.handler.polls["paper"] == 2


async def test_bytes_and_paths_sent_inline(docling_server: Any, tmp_path: Path, http: HttpPort) -> None:
    file = tmp_path / "report.pdf"
    file.write_bytes(b"%PDF-1.7 report")
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        await adapter.convert(b"%PDF-1.7 raw")
        raw = docling_server.sent["sources"][0]
        await adapter.convert(b"<html/>", filename="page.html")
        named = docling_server.sent["sources"][0]
        await adapter.convert(file)
        local = docling_server.sent["sources"][0]
    assert (raw["kind"], raw["filename"], base64.b64decode(raw["base64_string"])) == (
        "file",
        "document",
        b"%PDF-1.7 raw",
    )
    assert named["filename"] == "page.html"
    assert (local["filename"], base64.b64decode(local["base64_string"])) == ("report.pdf", b"%PDF-1.7 report")


async def test_options_follow_settings_then_the_call(docling_server: Any, http: HttpPort) -> None:
    conf = settings(
        docling_server.url,
        formats=(DoclingFormat.JSON, DoclingFormat.TEXT),
        images=DoclingImages.PLACEHOLDER,
        tables=DoclingTables.FAST,
        backend=DoclingBackend.PYPDFIUM2,
        force_ocr=True,
        ocr_lang=("en", "es"),
        formulas=True,
        page_timeout=timedelta(minutes=2),
    )
    async with DoclingDriver(http, conf) as adapter:
        await adapter.convert("https://example.org/a", options={"table_mode": "accurate", "page_range": [1, 3]})
    options = docling_server.sent["options"]
    assert options["to_formats"] == ["json", "text"]
    assert (options["image_export_mode"], options["include_images"], options["pdf_backend"]) == (
        "placeholder",
        False,
        "pypdfium2",
    )
    assert (options["force_ocr"], options["ocr_lang"], options["do_formula_enrichment"]) == (True, ["en", "es"], True)
    assert (options["document_timeout"], options["table_mode"], options["page_range"]) == (120.0, "accurate", [1, 3])


async def test_defaults_ask_markdown_json_and_embedded_pictures(docling_server: Any, http: HttpPort) -> None:
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        await adapter.convert("https://example.org/a")
    options = docling_server.sent["options"]
    assert (options["to_formats"], options["image_export_mode"], options["include_images"]) == (
        ["md", "json"],
        "embedded",
        True,
    )
    assert "ocr_lang" not in options
    assert options["document_timeout"] is None


async def test_a_failed_task_raises_with_its_reason(docling_server: Any, http: HttpPort) -> None:
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        with pytest.raises(DocumentError, match="docling task fail failure: bad pdf"):
            await adapter.convert("https://example.org/fail")


async def test_a_task_past_the_deadline_is_abandoned(docling_server: Any, http: HttpPort) -> None:
    ### a task that never settles: the deadline, not the server, ends the wait — whatever the load on the machine.
    async with DoclingDriver(http, settings(docling_server.url, deadline=timedelta(milliseconds=300))) as adapter:
        with pytest.raises(TimeoutError):
            await adapter.convert("https://example.org/slow")
    assert docling_server.sent["sources"] == [{"kind": "http", "url": "https://example.org/slow"}]


async def test_a_body_past_the_deadline_times_out(docling_server: Any, http: HttpPort) -> None:
    ### headers in time, body too late: the cut lands on the body read and still surfaces as a TimeoutError.
    async with DoclingDriver(http, settings(docling_server.url, deadline=timedelta(milliseconds=300))) as adapter:
        with pytest.raises(HttpTimeoutError, match="timed out after"):
            await adapter.convert("https://example.org/stall")


async def test_a_body_error_that_is_no_timeout_stays_an_http_error(
    docling_server: Any, monkeypatch: Any, http: HttpPort
) -> None:
    async def broken(self: Any) -> None:
        msg = "is_body error: connection reset"
        raise wreq.BodyError(msg)

    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        monkeypatch.setattr(wreq.Response, "json", broken)
        with pytest.raises(HttpError, match="connection reset") as caught:
            await adapter._common_call("GET", "/ready")
    assert not isinstance(caught.value, TimeoutError)


async def test_health_reflects_the_server(docling_server: Any, http: HttpPort) -> None:
    """docling-serve's readiness route: answered, unready (503), or nobody listening."""
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        assert await adapter.health()
        docling_server.handler.ready = False
        assert not await adapter.health()
    async with DoclingDriver(http, settings(DOWN)) as gone:
        assert not await gone.health()


async def test_a_server_error_surfaces_as_an_http_error(docling_server: Any, http: HttpPort) -> None:
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        with pytest.raises(HttpError) as caught:
            await adapter._common_call("GET", "/nowhere")
    assert caught.value.status == 404


async def test_an_unknown_source_kind_is_refused(docling_server: Any, http: HttpPort) -> None:
    async with DoclingDriver(http, settings(docling_server.url)) as adapter:
        with pytest.raises(TypeError, match="not int"):
            await adapter.convert(42)  # ty: ignore[invalid-argument-type]


async def test_a_request_past_the_deadline_times_out_never_cancels(docling_server: Any, http: HttpPort) -> None:
    ### the bound is the request's own timeout: a TimeoutError, never a CancelledError leaking into the caller's group.
    async with DoclingDriver(http, settings(docling_server.url, deadline=timedelta(milliseconds=300))) as adapter:
        with pytest.raises(TimeoutError, match="timed out after"):
            await adapter.convert("https://example.org/hang")
