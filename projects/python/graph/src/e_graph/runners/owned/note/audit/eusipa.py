"""runners.owned.note.audit.eusipa: the family is one of the map's seven, and the note's shape is the family it claims."""

from types import MappingProxyType
from typing import Any, Final

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

### the EUSIPA derivative map, level two (map dated 2020-02-13): the families and whether each risks capital.
FAMILIES: Final = MappingProxyType(
    {
        "capital protected": False,
        "yield enhancement": True,
        "participation": True,
        "reference entity": True,
        "leveraged without knock-out": True,
        "leveraged with knock-out": True,
        "constant leverage": True,
    }
)


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The classified family, whether the map admits it, and whether the note's own threshold backs the claim."""
    product, terms = state.context.inference["INF-product-type"], state.context.extract["EXT-terms"]
    family, at_risk = product["family"], product["capital_at_risk"]
    levels = terms["levels"]
    risky = levels["downside_threshold"] < levels["initial_value"]
    why = next(
        (
            reason
            for reason, held in (
                (f"{family!r} is not a family of the map", family in FAMILIES),
                (
                    f"the map says {family} is {FAMILIES.get(family)} at risk; the classification says otherwise",
                    at_risk is FAMILIES.get(family),
                ),
                (
                    f"the note's downside threshold stands at {levels['downside_threshold']} of {levels['initial_value']}: capital at risk is {risky}",
                    at_risk is risky,
                ),
            )
            if not held
        ),
        "",
    )
    return {"family": family, "holds": not why, "why": why}
