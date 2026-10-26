"""runners.owned.note.extract.schedule: the printed dates of the offering, normalized to ISO — the note's calendar."""

from datetime import date
from time import strptime
from typing import Annotated, Any

import msgspec

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call
from infra.struct import CheckedStruct


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`formats`: how the document prints a date, tried in order; anything else the schedule prints is no date."""

    formats: Annotated[tuple[str, ...], msgspec.Meta(min_length=1)] = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y")

    def iso(self, text: str) -> str:
        """One printed date as `YYYY-MM-DD`, parsed with the known formats; footnote markers stripped."""
        stripped = text.strip().strip("*")
        match [found for fmt in self.formats if (found := self._try(stripped, fmt))]:
            case [first, *_]:
                return first
            case _:
                msg = f"{text!r} is no date in the known formats {list(self.formats)}"
                raise ValueError(msg)

    @staticmethod
    def _try(text: str, fmt: str) -> str:
        """The date as ISO under one format, or empty when it does not fit."""
        try:
            return date(*strptime(text, fmt)[:3]).isoformat()
        except ValueError:
            return ""


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The schedule's rows as ISO pairs, with the first and final observation and the maturity of the calendar."""
    table, dates = call.inputs["EXT-schedule-table"], call.inputs["EXT-dates"]
    observations = [
        {"observation_date": call.args.iso(row["observation_date"]), "payment_date": call.args.iso(row["payment_date"])}
        for row in table["rows"]
    ]
    return {
        "count": len(observations),
        "observations": observations,
        "first_observation": observations[0]["observation_date"],
        "final_observation": observations[-1]["observation_date"],
        "maturity_date": dates["maturity_date"],
    }
