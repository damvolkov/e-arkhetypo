"""tests/unit/e_infra/processors/models: the document the processor hands out."""

import dataclasses

import polars as pl
import pytest

from e_infra.processors.models import Backend, Document, Page


def test_a_document_defaults_to_no_warnings_and_names_its_deep_pages() -> None:
    pages = (Page(1, Backend.ANYTOMD, (), "# a"), Page(2, Backend.DOCLING, (), "b"))
    document = Document(name="d", pages=pages, items=pl.DataFrame(), tables=(), pictures=(), formulas=())
    assert (document.warnings, document.deep, document.markdown) == ((), (2,), "# a\n\nb")


def test_a_page_is_immutable_and_holds_no_dict() -> None:
    page = Page(1, Backend.ANYTOMD, (), "x")
    assert not hasattr(page, "__dict__")
    frozen = "markdown"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(page, frozen, "y")
