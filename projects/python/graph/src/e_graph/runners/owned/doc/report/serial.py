"""runners.owned.doc.report.serial: the record serialized in the format the run asked for."""

from typing import Any, cast

import eserde
from eserde import Format

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The record as text in the run's `format` (JSON by default); an unknown format fails here."""
    codec = Format[cast("str", state.context.get("format", "json")).upper()]
    record = dict(state.context.transform["TRF-record"])
    return {"format": codec.name.lower(), "text": (await eserde.adumps(record, format=codec)).decode()}
