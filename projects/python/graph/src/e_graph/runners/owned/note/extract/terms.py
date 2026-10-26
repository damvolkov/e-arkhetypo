"""runners.owned.note.extract.terms: the term sheet assembled — every extracted piece in one normalized record.

The money arrives as printed (commas, dollar signs, one match per page): the first reading of each is
the offering's, and it is converted to a number here, once. Everything else is already shaped by its
own spec and moves up unchanged; the levels keep the order the note states them — initial, barrier,
threshold, call."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call
from infra.struct import CheckedStruct


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Takes nothing: the term sheet reads every input from its declared dependencies."""

    @staticmethod
    def money(text: str) -> float:
        """A printed amount — "$6,484,400.00" — as a number."""
        return float(text.replace("$", "").replace(",", ""))


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The whole term sheet: identifiers, money, calendar, levels and parties, each in one shape."""
    inputs = call.inputs
    identifiers, amounts, fees = inputs["EXT-identifiers"], inputs["EXT-amounts"], inputs["EXT-fees"]
    dates, barrier, autocall = inputs["EXT-dates"], inputs["EXT-barrier"], inputs["EXT-autocall"]
    estimated, coupon, underlier = inputs["EXT-estimated-value"], inputs["EXT-coupon"], inputs["EXT-underlier"]
    agents, listing, schedule = inputs["EXT-agents"], inputs["EXT-listing"], inputs["EXT-schedule"]
    return {
        "cusip": identifiers["cusip"],
        "isin": identifiers["isin"],
        "registration_no": inputs["EXT-registration"]["registration_no"],
        "currency_symbol": amounts["currency_symbol"][0],
        "aggregate_principal": call.args.money(amounts["aggregate_principal"][0]),
        "denomination": call.args.money(amounts["denomination"][0]),
        "offering_price": call.args.money(amounts["offering_price"][0]),
        "underwriting_discount": call.args.money(fees["underwriting_discount"][0]),
        "pricing_date": dates["pricing_date"],
        "issue_date": dates["issue_date"],
        "maturity_date": dates["maturity_date"],
        "final_observation_date": dates["final_observation_date"],
        "underlier": dict(underlier),
        "coupon": dict(coupon),
        "levels": {
            "initial_value": autocall["initial_value"],
            "coupon_barrier": barrier["coupon_barrier"],
            "downside_threshold": barrier["downside_threshold"],
            "call_level": autocall["call_level"],
            "share_of_initial_percent": barrier["share_of_initial_percent"],
        },
        "estimated_value": estimated["estimated_value"],
        "calculation_agent": agents["calculation_agent"],
        "selling_agents": list(agents["selling_agents"]),
        "listed": listing["listed"],
        "observations": schedule["count"],
    }
