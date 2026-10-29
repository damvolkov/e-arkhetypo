"""tests/unit: processors.doc (core, materialized) on the graph's corpus — hybrid reads held to the official truth.

Every corpus document is read once per module by the real hybrid: liteparse on the real PDF, docling
answered by the golden conversions (`support.docling.GoldenPort`). The filings' XBRL facts must sit on
the row of their label, exactly as a docling-only read gives them; the papers keep their table headers,
captions and figures, which only docling reads."""

import re
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from infra.config.doc import DocMode, DocSettings, DocSignal
from processors.doc import DocProcessor
from processors.models import Backend, Document
from support.docling import GoldenPort

if TYPE_CHECKING:
    from pytest_resources import Resources


LABELS: dict[str, str] = {
    "revenue": r"total net sales|net operating revenues|total revenues",
    "cost_of_revenue": r"total cost of sales|cost of goods sold",
    "gross_profit": r"gross margin|gross profit",
    "operating_income": r"operating income",
    "net_income": r"net income",
    "eps_basic": r"basic",
    "eps_diluted": r"diluted",
    "total_assets": r"total assets",
    "total_liabilities": r"total liabilities",
    "equity": r"total shareholders|total equity|equity attributable",
    "cash": r"cash and cash equivalents",
    "operating_cash_flow": r"operating activities",
    "dividends_per_share": r"dividends",
    "rnd_expense": r"research and development",
}


@pytest.fixture(scope="module")
def corpus(resources: Resources) -> list[dict[str, Any]]:
    """The corpus entries, each with its absolute path."""
    root = next(iter(resources.documents.paths("corpus.yaml"))).parent
    return [{**entry, "path": root / entry["file"]} for entry in resources.documents.corpus["documents"]]


@pytest.fixture(scope="module")
async def read(corpus: list[dict[str, Any]]) -> dict[str, tuple[Document, GoldenPort]]:
    """Every corpus document read by the hybrid, once; each with the port that saw its docling spans."""
    reads = {}
    for entry in corpus:
        port = GoldenPort()
        reads[entry["path"].stem] = (await DocProcessor(port, DocSettings()).process(entry["path"]), port)
    return reads


def rows(document: Document) -> list[str]:
    return [" | ".join(row) for table in document.tables for row in table.frame.iter_rows()]


def value(fact: dict[str, Any]) -> str:
    return f"{fact['value'] // 1_000_000:,}" if fact["unit"] == "USD" else f"{fact['value']}"


##### QUALITY — the official truth #####
@pytest.mark.parametrize("stem", ["aapl-10k-2025", "ko-10k-2025"])
def test_every_xbrl_fact_sits_on_its_labels_row(
    stem: str, read: dict[str, tuple[Document, GoldenPort]], corpus: list[dict[str, Any]]
) -> None:
    facts = next(entry["truth"]["facts"] for entry in corpus if entry["path"].stem == stem)
    lines = rows(read[stem][0])
    missing = [
        key
        for key, fact in facts.items()
        if not any(value(fact) in line and re.search(LABELS[key], line, re.IGNORECASE) for line in lines)
    ]
    assert missing == []


def test_the_statements_are_read_by_docling(read: dict[str, tuple[Document, GoldenPort]]) -> None:
    document, _ = read["aapl-10k-2025"]
    statement = next(
        table for table in document.tables if any("Net income" in line and "112,010" in line for line in rows_of(table))
    )
    assert statement.backend is Backend.DOCLING
    assert statement.page in document.deep


def rows_of(table: Any) -> list[str]:
    return [" | ".join(row) for row in table.frame.iter_rows()]


def test_paper_tables_keep_headers_and_captions(read: dict[str, tuple[Document, GoldenPort]]) -> None:
    document, _ = read["arxiv-2309.05783"]
    top = next(table for table in document.tables if table.caption.startswith("Table 4"))
    assert top.frame.columns[:2] == ["Rank", "Player"]
    assert top.backend is Backend.DOCLING


def test_paper_figures_come_with_bytes_and_captions(read: dict[str, tuple[Document, GoldenPort]]) -> None:
    document, _ = read["arxiv-2309.05783"]
    assert document.pictures
    assert all(picture.data.startswith(b"\x89PNG") for picture in document.pictures)
    assert any(picture.caption.startswith("Figure") for picture in document.pictures)


##### ROUTING — the work each engine did #####
@pytest.mark.parametrize(
    "stem", ["aapl-10k-2025", "ko-10k-2025", "arxiv-2505.24250", "arxiv-2309.05783", "arxiv-2402.01820"]
)
def test_docling_reads_only_the_routed_spans(stem: str, read: dict[str, tuple[Document, GoldenPort]]) -> None:
    document, port = read[stem]
    spans = [call["options"]["page_range"] for call in port.calls]
    covered = {page for first, last in spans for page in range(first, last + 1)}
    assert set(document.deep) == covered
    assert len(document.deep) < len(document.pages)
    ### OCR is asked of a span exactly when one of its pages has no usable text layer (a scan, vector-drawn text).
    signals = {page.number: page.signals for page in document.pages}
    for (first, last), call in zip(spans, port.calls, strict=True):
        scanned = any(DocSignal.SCANNED in signals[page] for page in range(first, last + 1))
        assert call["options"]["do_ocr"] is scanned
    ### every span exists for a reason: at least one of its pages carries a routed signal.
    assert all(any(signals[page] for page in range(first, last + 1)) for first, last in spans)


def test_text_pages_stay_with_liteparse(read: dict[str, tuple[Document, GoldenPort]]) -> None:
    document, _ = read["ko-10k-2025"]
    lite = [page for page in document.pages if page.backend is Backend.LITEPARSE]
    assert len(lite) > len(document.pages) / 2
    assert all(DocSignal.TABLE not in page.signals for page in lite)
    assert document.items.filter(pl.col("backend") == "liteparse").height > 0


def test_markdown_keeps_pictures_as_markers_never_as_bytes(read: dict[str, tuple[Document, GoldenPort]]) -> None:
    ### a picture's bytes are the document's pictures: inlined in the text, they would reach every prompt.
    pages = [page for document, _ in read.values() for page in document.pages if page.backend is Backend.DOCLING]
    assert not [page.number for page in pages if "data:image" in page.markdown]
    assert any("<!-- image -->" in page.markdown for page in pages)


async def test_lite_mode_reads_a_filing_without_docling(corpus: list[dict[str, Any]]) -> None:
    port = GoldenPort()
    path = next(entry["path"] for entry in corpus if entry["path"].stem == "aapl-10k-2025")
    document = await DocProcessor(port, DocSettings(doc_mode=DocMode.LITE)).process(path)
    assert (port.calls, document.deep) == ([], ())
    assert any("416,161" in line for line in rows(document))
