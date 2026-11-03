"""tests/unit/e_infra/processors/models: the Markdown result the processor hands out."""

import dataclasses

import pytest

from e_infra.processors.models import MarkdownFile


def test_a_markdown_file_ships_under_its_name_and_defaults_empty() -> None:
    file = MarkdownFile(name="report.md", markdown="# Hi", source="html")
    assert (file.warnings, file.path, file.error) == ((), "", "")


def test_a_markdown_file_traces_its_source_notes_and_failure() -> None:
    file = MarkdownFile(name="a.md", markdown="", source="pdf", warnings=("w",), path="x/a.pdf", error="refused")
    assert (file.source, file.path, file.error, file.warnings) == ("pdf", "x/a.pdf", "refused", ("w",))


def test_a_markdown_file_is_immutable_and_holds_no_dict() -> None:
    file = MarkdownFile(name="a.md", markdown="x", source="txt")
    assert not hasattr(file, "__dict__")
    frozen = "markdown"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(file, frozen, "y")
