"""tests/unit: runners.agnostic.context.present — the outputs a spec reads exist and hold something."""

from typing import TYPE_CHECKING

import msgspec
import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.context.present import Args, check
from infra.struct import CheckedStruct

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


def call(*needs: str) -> Call:
    return Call(pipeline="doc", section=Section.EXTRACT, spec="EXT-a", slot=Slot.CHECK, args=Args(needs=needs))


async def test_every_need_written_and_filled_passes(run_state: RunState) -> None:
    run_state.context.ingest["ING-document"] = {"text": "x"}
    run_state.context.normalize["NOR-canonical"] = {"text": "x"}
    assert await check(run_state, call("ingest/ING-document", "normalize/NOR-canonical")) is True


@pytest.mark.parametrize("written", [{}, {"ING-document": {}}], ids=["absent", "empty"])
async def test_a_need_absent_or_empty_refuses(run_state: RunState, written: dict[str, object]) -> None:
    run_state.context.ingest.update(written)
    assert await check(run_state, call("ingest/ING-document")) is False


@pytest.mark.parametrize("needs", [[], ["ING-document"], ["ingest/document"]], ids=["none", "no-section", "no-prefix"])
def test_args_hold_addresses_only(needs: list[str]) -> None:
    with pytest.raises(msgspec.ValidationError):
        CheckedStruct.convert({"needs": needs}, Args)
