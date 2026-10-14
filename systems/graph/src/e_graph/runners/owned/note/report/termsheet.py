"""runners.owned.note.report.termsheet: the finished record — the note's terms, class, outcome and every verdict in one page."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The term sheet, who classified it, what it can pay and lose, the plain-language brief, and the audits' word."""
    extract, inference, audit = state.context.extract, state.context.inference, state.context.audit
    terms, issuer = extract["EXT-terms"], extract["EXT-issuer"]
    verdict, coherence = audit["AUD-verdict"], audit["AUD-coherence"]
    return {
        "isin": terms["isin"],
        "cusip": terms["cusip"],
        "issuer": issuer["issuer"],
        "guarantor": issuer["guarantor"],
        "underlier": {key: terms["underlier"][key] for key in ("name", "ticker")},
        "money": {
            "currency": terms["currency_symbol"],
            "aggregate_principal": terms["aggregate_principal"],
            "denomination": terms["denomination"],
            "offering_price": terms["offering_price"],
            "estimated_value": terms["estimated_value"],
            "fee_drag_percent": round(inference["INF-drag"]["share"] * 100, 4),
        },
        "coupon": {
            "rate_percent": terms["coupon"]["rate_percent"],
            "quarterly_per_note": terms["coupon"]["quarterly_payment"],
            "payments": terms["observations"],
        },
        "calendar": {
            "pricing_date": terms["pricing_date"],
            "issue_date": terms["issue_date"],
            "maturity_date": terms["maturity_date"],
            "term_years": inference["INF-tenor"]["years_act365"],
        },
        "levels": {
            key: terms["levels"][key] for key in ("initial_value", "coupon_barrier", "downside_threshold", "call_level")
        },
        "classification": {
            "eusipa": inference["INF-product-type"]["family"],
            "shape": inference["INF-product-type"]["shape"],
            "cfi": inference["INF-cfi"]["code"],
            "risk_class": inference["INF-risk-class"]["risk_class"],
        },
        "outcome": {
            "best_percent": inference["INF-max-return"]["best_percent"],
            "worst_percent": inference["INF-max-return"]["worst_percent"],
            "scenarios": len(inference["INF-scenarios"]["scenarios"]),
        },
        "summary": inference["INF-summary"]["summary"],
        "verdict": {
            "holds": verdict["holds"],
            "broken": verdict["broken"],
            "checks": verdict["checks"],
            "coherent": coherence["coherent"],
            "conflicts": coherence["conflicts"],
        },
    }
