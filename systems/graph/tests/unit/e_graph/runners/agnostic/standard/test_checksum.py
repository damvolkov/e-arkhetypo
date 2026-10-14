"""tests/unit: runners.agnostic.standard/checksum — the check digit of ISINs, CUSIPs and LEIs holds or not."""

from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.standard.checksum import Args, Scheme, run

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


def call(**args: Any) -> Call:
    return Call(pipeline="note", section=Section.AUDIT, spec="AUD-isin", slot=Slot.RUNNER, args=Args(**args))


@pytest.fixture
def state(run_state: RunState) -> RunState:
    run_state.context.extract["EXT-identifiers"] = {"cusip": "09711E688", "isin": "US09711E6885"}
    run_state.context.extract["EXT-entity"] = {"lei": "5493001KJTIIGC8Y1R12"}
    return run_state


@pytest.mark.parametrize(
    ("scheme", "value", "expected", "holds"),
    [
        ("isin", "extract/EXT-identifiers.isin", "US09711E6885", True),
        ("cusip", "extract/EXT-identifiers.cusip", "09711E688", True),
        ("lei", "extract/EXT-entity.lei", "5493001KJTIIGC8Y1R12", True),
        ("isin", "extract/EXT-entity.lei", "5493001KJTIIGC8Y1R12", False),
        ("cusip", "extract/EXT-entity.lei", "5493001KJTIIGC8Y1R12", False),
    ],
    ids=["isin-holds", "cusip-holds", "lei-holds", "isin-not-an-isin", "cusip-not-a-cusip"],
)
async def test_a_real_identifier_holds_under_its_own_standard(
    state: RunState, scheme: str, value: str, expected: str, holds: bool
) -> None:
    assert await run(state, call(scheme=scheme, value=value)) == {"value": expected, "holds": holds}


async def test_a_corrupted_check_digit_is_a_verdict_never_a_crash(state: RunState) -> None:
    state.context.extract["EXT-identifiers"] = {"isin": "US09711E6884", "cusip": "09711E687"}
    assert (await run(state, call(scheme="isin", value="extract/EXT-identifiers.isin")))["holds"] is False
    assert (await run(state, call(scheme="cusip", value="extract/EXT-identifiers.cusip")))["holds"] is False
    state.context.extract["EXT-entity"] = {"lei": "5493001kjtiigc8y1r12"}
    assert (await run(state, call(scheme="lei", value="extract/EXT-entity.lei")))["holds"] is False


def test_an_address_without_a_field_is_refused_at_birth() -> None:
    with pytest.raises(ValueError, match="matching regex"):
        Args(scheme=Scheme.ISIN, value="extract/EXT-identifiers")
