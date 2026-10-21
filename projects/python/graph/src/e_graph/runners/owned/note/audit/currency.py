"""runners.owned.note.audit.currency: the printed symbol resolves to one ISO 4217 code — the dollar signs are the US dollar."""

from types import MappingProxyType
from typing import Any, Final

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

### the symbols these notes print with, to their ISO 4217 codes (table dated 2026-10-14).
SYMBOLS: Final = MappingProxyType(
    {
        "$": "USD",
        "US$": "USD",
        "\u20ac": "EUR",
        "\u00a3": "GBP",
        "\u00a5": "JPY",
        "SFr.": "CHF",
        "C$": "CAD",
        "A$": "AUD",
    }
)


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The currency the note pays in, from its printed symbol; unknown symbols resolve to nothing."""
    symbol = state.context.extract["EXT-terms"]["currency_symbol"]
    currency = str(SYMBOLS.get(symbol, ""))
    return {"currency": currency or symbol, "holds": bool(currency)}
