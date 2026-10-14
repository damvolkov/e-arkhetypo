"""runners.owned.note.audit.verdict: the audit of audits — every check's answer, the names of the ones that did not hold."""

from typing import TYPE_CHECKING, Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

if TYPE_CHECKING:
    from collections.abc import Mapping


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """How many checks ran, which failed their predicate, and the whole verdict."""
    answers: Mapping[str, Any] = call.inputs
    broken = sorted(name for name, answer in answers.items() if not answer["holds"])
    return {"holds": not broken, "broken": broken, "checks": len(answers)}
