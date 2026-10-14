"""runners.owned.note.audit.cfi: the CFI code keeps the shape of ISO 10962 — six capitals, the debt category, and the index it tracks."""

from typing import Any, Final

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

CODE_LENGTH: Final[int] = 6
### the group letters ISO 10962 gives the debt category (table dated 2026-10-14): bonds, convertibles,
### bonds with warrants, medium-term notes, money market, mortgage- and asset-backed, municipal,
### depositary receipts, other — plus X, the standard's own "unspecified".
DEBT_GROUPS: Final = frozenset("BCTWYGQNDA MX")


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The code as classified, whether it keeps the standard's shape, and the first position that broke it."""
    code = state.context.inference["INF-cfi"]["code"]
    index = state.context.extract["EXT-terms"]["underlier"]["is_index"]
    why = next(
        (
            reason
            for reason, held in (
                (f"the code is {len(code)} letters, not six", len(code) == CODE_LENGTH),
                ("a letter outside A-Z", code.isalpha() and code.isupper()),
                (f"category {code[:1]} is not D for debt", code[:1] == "D"),
                (f"group {code[1:2]} is not a debt group or X", code[1:2] in DEBT_GROUPS),
                (
                    f"an index-linked note must carry the I attribute, and {code} does not",
                    "I" in code[2:] if index else True,
                ),
            )
            if not held
        ),
        "",
    )
    return {"code": code, "holds": not why, "why": why}
