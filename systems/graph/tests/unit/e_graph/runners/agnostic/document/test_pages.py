"""tests/unit: runners.agnostic.document.pages — the leading pages, then the pages that open with what is sought."""

from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.document.pages import Args, pre_run

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState

PAGES = [
    {"number": 1, "markdown": "FORM 10-K · Apple Inc."},
    {"number": 2, "markdown": "Index: Consolidated Statements of Operations ... 44"},
    {"number": 3, "markdown": "## CONSOLIDATED STATEMENTS OF OPERATIONS\n| Net income | 112,010 |\n| Gross margin |"},
    {"number": 4, "markdown": "Notes. Net income grew; gross margin held."},
]


def call(**args: Any) -> Call:
    return Call(pipeline="filing", section=Section.EXTRACT, spec="EXT-income", slot=Slot.PRE, args=Args(**args))


@pytest.fixture
def state(run_state: RunState) -> RunState:
    run_state.context.ingest["ING-document"] = {"pages": PAGES}
    return run_state


def test_a_title_opening_the_page_outweighs_every_word() -> None:
    args = Args(titles=("consolidated statements of operations",), words=("net income", "gross"), head=60)
    assert [args.score(page) for page in PAGES] == [0, 10, 12, 2]


@pytest.mark.parametrize(
    ("args", "numbers"),
    [
        ({"titles": ("consolidated statements of operations",), "words": ("net income",), "most": 1}, [3]),
        ({"titles": ("consolidated statements of operations",), "most": 2}, [2, 3]),
        ({"first": 1, "most": 0}, [1]),
        ({"first": 1, "words": ("gross",), "most": 1}, [1, 3]),
        ({"words": ("dividends",)}, []),
    ],
    ids=["best-one", "ties-in-page-order", "leading-only", "leading-and-best", "nothing-sought-nothing-sent"],
)
async def test_the_material_is_the_chosen_pages_in_order(
    state: RunState, args: dict[str, Any], numbers: list[int]
) -> None:
    material = await pre_run(state, call(**args))
    assert [
        int(line.removeprefix("## Page ")) for line in material.splitlines() if line.startswith("## Page ")
    ] == numbers


async def test_each_page_is_headed_by_its_number(state: RunState) -> None:
    assert await pre_run(state, call(first=1, most=0)) == "## Page 1\nFORM 10-K · Apple Inc."
