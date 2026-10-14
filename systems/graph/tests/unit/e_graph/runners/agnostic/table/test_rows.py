"""tests/unit: runners.agnostic.table/rows — the rows of the table whose header holds the words, as records."""

from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.table.rows import Args, run

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState

PAGES = [
    {
        "number": 1,
        "markdown": "| Public Offering Price | Underwriting Discount |\n|---|---|\n| $10.00 | $0.00 |\n\n$0.00 $0.00",
    },
    {
        "number": 2,
        "markdown": (
            "## Observation Dates and Coupon Payment Dates\n"
            "| Observation Dates | Coupon Payment Dates |\n|---|---|\n"
            "| February 6, 2026 | February 10, 2026 |\n| November 8, 2027* | November 12, 2027 |\n"
            "| orphan row, three cells | x | y |\n"
        ),
    },
]


def call(**args: Any) -> Call:
    return Call(
        pipeline="note", section=Section.EXTRACT, spec="EXT-schedule-table", slot=Slot.RUNNER, args=Args(**args)
    )


@pytest.fixture
def state(run_state: RunState) -> RunState:
    run_state.context.ingest["ING-document"] = {"pages": PAGES}
    return run_state


async def test_the_table_whose_header_holds_the_words_answers_with_named_rows(state: RunState) -> None:
    answer = await run(
        state,
        call(header=("observation dates", "coupon payment dates"), columns=("observation_date", "payment_date")),
    )
    assert answer == {
        "rows": [
            {"observation_date": "February 6, 2026", "payment_date": "February 10, 2026"},
            {"observation_date": "November 8, 2027", "payment_date": "November 12, 2027"},
        ]
    }


async def test_a_table_of_another_width_is_no_match(state: RunState) -> None:
    answer = await run(state, call(header=("observation dates",), columns=("observation_date",)))
    assert answer == {"rows": []}


async def test_the_first_page_holds_when_several_tables_match(state: RunState) -> None:
    answer = await run(state, call(header=("public offering price",), columns=("price", "discount")))
    assert answer == {"rows": [{"price": "$10.00", "discount": "$0.00"}]}


async def test_no_header_holding_the_words_fails_the_spec(state: RunState) -> None:
    with pytest.raises(ValueError, match="no table header holds"):
        await run(state, call(header=("maturity dates",), columns=("date",)))
