"""runners.owned.filing.report.facts: the filing's facts in one record, named as XBRL concepts are, with the audits' verdict."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Who filed, for which period, every fact read, and the audits that did not hold."""
    extract, audit = state.context.extract, state.context.audit
    cover = extract["EXT-cover"]
    return {
        "company": cover["company"],
        "period_end": cover["period_end"],
        "shares_outstanding": cover["shares_outstanding"],
        "facts": {**dict(extract["EXT-income"]), **dict(extract["EXT-balance"])},
        "broken": sorted(name for name, verdict in audit.items() if not verdict["holds"]),
    }
