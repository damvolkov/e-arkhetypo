"""tests/unit: runners.agnostic.document.read — the document at the run's context key, read page by page."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.document.read import Args, run

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState

NOTES = Path(__file__).resolve().parents[6] / "tests" / "resources" / "documents" / "notes"


def call(**args: Any) -> Call:
    return Call(pipeline="note", section=Section.INGEST, spec="ING-document", slot=Slot.RUNNER, args=Args(**args))


@pytest.fixture
def state(run_state: RunState) -> RunState:
    run_state.context.source = str(NOTES / "bofa-autocall-2027.pdf")
    return run_state


async def test_the_document_at_the_default_key_is_read_into_pages(state: RunState) -> None:
    output = await run(state, call())
    assert output["name"] == "bofa-autocall-2027.pdf"
    assert [page["number"] for page in output["pages"]][:3] == [1, 2, 3]
    assert len(output["pages"]) == 25
    assert output["deep"]
    assert set(output["deep"]) <= {page["number"] for page in output["pages"]}


async def test_a_key_other_than_source_is_read_from_where_it_lives(state: RunState) -> None:
    state.context.paper = state.context["source"]
    del state.context["source"]
    output = await run(state, call(key="paper"))
    assert output["name"] == "bofa-autocall-2027.pdf"


@pytest.mark.parametrize("source", [None, ""], ids=["absent", "empty"])
async def test_a_run_without_its_named_key_names_what_it_lacks(state: RunState, source: str | None) -> None:
    del state.context["source"]
    _ = state.context.update({"source": source}) if source is not None else None
    with pytest.raises(ValueError, match="the run needs `source`"):
        await run(state, call())
