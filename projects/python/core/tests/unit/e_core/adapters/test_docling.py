"""tests/unit/e_core/adapters/docling: the task lifecycle, every source kind, options, failure and deadline — offline."""

import base64
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import wreq

from e_core.adapters.base import PingError
from e_core.adapters.conftest import DOWN
from e_core.adapters.docling import DoclingAdapter, DoclingError
from e_core.adapters.ports import DocumentConversion, DocumentPort
from e_core.core.settings.docling import DoclingBackend, DoclingFormat, DoclingImages, DoclingSettings, DoclingTables

if TYPE_CHECKING:
    from pathlib import Path


def settings(url: str, **values: Any) -> DoclingSettings:
    return DoclingSettings(docling_url=url, docling_poll=timedelta(milliseconds=5), **values)


async def test_lifecycle_and_port_shape() -> None:
    adapter = DoclingAdapter(DoclingSettings())
    assert isinstance(adapter, DocumentPort)
    assert adapter.name == "docling"
    with pytest.raises(RuntimeError, match="not connected"):
        await adapter.convert("https://example.org/a.pdf")
    async with adapter:
        pass
    await adapter.close()


async def test_url_converted_as_a_task(docling_server: Any) -> None:
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
        conversion = await adapter.convert("https://example.org/paper")
    assert conversion == DocumentConversion(
        filename="paper.pdf", status="success", markdown="# Title", document={"tables": []}, seconds=1.5
    )
    assert docling_server.sent["sources"] == [{"kind": "http", "url": "https://example.org/paper"}]
    assert docling_server.sent["target"] == {"kind": "inbody"}
    assert docling_server.handler.polls["paper"] == 2


async def test_bytes_and_paths_sent_inline(docling_server: Any, tmp_path: Path) -> None:
    file = tmp_path / "report.pdf"
    file.write_bytes(b"%PDF-1.7 report")
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
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


async def test_options_follow_settings_then_the_call(docling_server: Any) -> None:
    conf = settings(
        docling_server.url,
        docling_formats=(DoclingFormat.JSON, DoclingFormat.TEXT),
        docling_images=DoclingImages.PLACEHOLDER,
        docling_tables=DoclingTables.FAST,
        docling_backend=DoclingBackend.PYPDFIUM2,
        docling_force_ocr=True,
        docling_ocr_lang=("en", "es"),
        docling_formulas=True,
        docling_page_timeout=timedelta(minutes=2),
    )
    async with DoclingAdapter(conf) as adapter:
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


async def test_defaults_ask_markdown_json_and_embedded_pictures(docling_server: Any) -> None:
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
        await adapter.convert("https://example.org/a")
    options = docling_server.sent["options"]
    assert (options["to_formats"], options["image_export_mode"], options["include_images"]) == (
        ["md", "json"],
        "embedded",
        True,
    )
    assert "ocr_lang" not in options
    assert options["document_timeout"] is None


async def test_a_failed_task_raises_with_its_reason(docling_server: Any) -> None:
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
        with pytest.raises(DoclingError, match="docling task fail failure: bad pdf"):
            await adapter.convert("https://example.org/fail")


async def test_a_task_past_the_deadline_is_abandoned(docling_server: Any) -> None:
    ### a task that never settles: the deadline, not the server, ends the wait — whatever the load on the machine.
    async with DoclingAdapter(settings(docling_server.url, docling_deadline=timedelta(milliseconds=300))) as adapter:
        with pytest.raises(TimeoutError):
            await adapter.convert("https://example.org/slow")
    assert docling_server.sent["sources"] == [{"kind": "http", "url": "https://example.org/slow"}]


async def test_ping_reflects_the_server(docling_server: Any) -> None:
    """docling-serve's readiness route: answered, unready (503), or nobody listening."""
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
        await adapter.ping()
        docling_server.handler.ready = False
        with pytest.raises(PingError, match=r"^docling: StatusError: "):
            await adapter.ping()
    async with DoclingAdapter(settings(DOWN)) as gone:
        with pytest.raises(PingError, match=r"^docling: ConnectionError: "):
            await gone.ping()


async def test_a_server_error_surfaces_as_the_clients_own(docling_server: Any) -> None:
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
        with pytest.raises(wreq.StatusError):
            await adapter._common_call("GET", "/nowhere")


async def test_an_unknown_source_kind_is_refused(docling_server: Any) -> None:
    async with DoclingAdapter(settings(docling_server.url)) as adapter:
        with pytest.raises(TypeError, match="not int"):
            await adapter.convert(42)  # ty: ignore[invalid-argument-type]


async def test_a_request_past_the_deadline_times_out_never_cancels(docling_server: Any) -> None:
    ### the bound is the request's own timeout: a TimeoutError, never a CancelledError leaking into the caller's group.
    async with DoclingAdapter(settings(docling_server.url, docling_deadline=timedelta(milliseconds=300))) as adapter:
        with pytest.raises(TimeoutError, match="timed out after"):
            await adapter.convert("https://example.org/hang")
