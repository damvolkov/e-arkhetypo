"""tests/unit: runners.agnostic.number.scale — figures read in millions brought to units, the rest untouched."""

from typing import TYPE_CHECKING

import msgspec
import pytest

from e_graph.logic.models import Call, Slot
from e_graph.models.section import Section
from e_graph.runners.agnostic.number.scale import Args, post_run
from infra.struct import CheckedStruct

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


async def test_listed_figures_scale_the_rest_stays(run_state: RunState) -> None:
    call = Call(
        pipeline="filing",
        section=Section.EXTRACT,
        spec="EXT-income",
        slot=Slot.POST,
        args=Args(fields=("revenue", "net_income", "missing", "unread")),
    )
    output = {"revenue": 416161, "net_income": 112010.4, "unread": None, "eps": 7.49}
    assert await post_run(run_state, call, output) == {
        "revenue": 416161000000,
        "net_income": 112010400000,
        "unread": None,
        "eps": 7.49,
    }


@pytest.mark.parametrize(
    "raw", [{"fields": []}, {"fields": ["a"], "factor": 0}, {}], ids=["no-fields", "zero", "absent"]
)
def test_args_refuse_what_scales_nothing(raw: dict[str, object]) -> None:
    with pytest.raises(msgspec.ValidationError):
        CheckedStruct.convert(raw, Args)
