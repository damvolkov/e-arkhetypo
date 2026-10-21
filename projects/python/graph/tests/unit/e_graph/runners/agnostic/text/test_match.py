"""tests/unit: runners.agnostic.text.match — the named groups of a regex over the chosen pages."""

import re
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.text.match import Args, run

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState

PAGES = [
    {"number": 1, "markdown": "BofA Finance LLC $6,484,400 Trigger Notes\nCUSIP/ ISIN 09711E688 / US09711E6885"},
    {"number": 2, "markdown": "Registration Statement Nos. 333-268718 and 333-268718-01"},
    {"number": 3, "markdown": "US09711E6885 appears again in the footer."},
]


def call(**args: Any) -> Call:
    return Call(pipeline="note", section=Section.EXTRACT, spec="EXT-identifiers", slot=Slot.RUNNER, args=Args(**args))


@pytest.fixture
def state(run_state: RunState) -> RunState:
    run_state.context.ingest["ING-document"] = {"pages": PAGES}
    return run_state


async def test_the_named_groups_of_the_first_match_answer(state: RunState) -> None:
    answer = await run(state, call(pattern=r"(?P<cusip>[0-9A-Z]{6}\d{2}[0-9A-Z]) / (?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)"))
    assert answer == {"cusip": "09711E688", "isin": "US09711E6885"}


async def test_pages_outside_the_selection_are_never_searched(state: RunState) -> None:
    with pytest.raises(ValueError, match="matched nothing"):
        await run(state, call(pattern=r"(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)", pages=(2,)))


async def test_many_gathers_the_group_from_every_page_in_order(state: RunState) -> None:
    answer = await run(state, call(pattern=r"(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)", many=True))
    assert answer == {"isin": ["US09711E6885", "US09711E6885"]}


async def test_alternations_fall_to_their_lists(state: RunState) -> None:
    answer = await run(state, call(pattern=r"(?P<registration>333-\d{6})|(?P<aggregate>\$[\d,]+) Trigger", many=True))
    ### p2 states "333-268718 and 333-268718-01": the base number is read twice, and `many` keeps both.
    assert answer == {"registration": ["333-268718", "333-268718"], "aggregate": ["$6,484,400"]}


async def test_a_pattern_without_groups_is_refused_at_birth() -> None:
    with pytest.raises(ValueError, match="names no group"):
        Args(pattern=r"[0-9]+")
    with pytest.raises(re.error, match="unterminated name"):
        Args(pattern=r"(?P<broken")
