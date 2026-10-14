"""nodes.report.node: serialize the record in the requested format and confirm delivery."""

import asyncio
from typing import cast

import eserde
from eserde import Format

from e_graph.instrument.state import RunState


async def node_report(state: RunState) -> str:
    """Serialize the record in the requested format (`data.format`, JSON by default) and confirm it."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    ### an unknown format is a KeyError: the node answers FAILED, the run's verdict names it.
    codec = Format[cast("str", state.context.get("format", "json")).upper()]
    state.context.report = report = await eserde.adumps(state.context.record, format=codec)
    return f"delivered {len(report)} bytes as {codec.name.lower()}"
