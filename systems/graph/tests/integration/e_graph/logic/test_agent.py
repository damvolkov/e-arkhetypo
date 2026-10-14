"""tests/integration: logic.agent — typed, schema and text replies from a real model, costed and metered."""

from typing import TYPE_CHECKING, Any

import msgspec
import pydantic
import pytest

from e_graph.logic.agent import AgnosticAgent

if TYPE_CHECKING:
    from e_graph.logic.models import Endpoint

pytestmark = [pytest.mark.vcr, pytest.mark.integration]

INVOICE = "Invoice 42 from ACME: 2 x widget at 10.00 EUR, 1 x bolt at 2.50 EUR. Total 22.50 EUR."
GREEDY: dict[str, Any] = {"temperature": 0.0, "seed": 7, "max_tokens": 4096}


class Line(msgspec.Struct):
    item: str
    quantity: int
    price: float


class Capital(pydantic.BaseModel):
    city: str


class Invoice(msgspec.Struct):
    number: str
    vendor: str
    total: float
    lines: list[Line]


async def test_typed_reply_validated(agent: AgnosticAgent, endpoint: Endpoint) -> None:
    reply = await agent.run("Extract the invoice.", INVOICE, Invoice, endpoint=endpoint, **GREEDY)
    assert (reply.output.total, len(reply.output.lines), reply.attempts) == (22.5, 2, 1)
    assert reply.usage.calls == 1
    assert reply.usage.total_tokens > 0


async def test_schema_reply_is_an_object(agent: AgnosticAgent, endpoint: Endpoint) -> None:
    schema = {
        "title": "kind",
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["invoice", "receipt", "contract"]}},
        "required": ["kind"],
    }
    reply = await agent.run("Classify the document.", INVOICE, schema, endpoint=endpoint, **GREEDY)
    assert reply.output == {"kind": "invoice"}


async def test_pydantic_reply_metered(agent: AgnosticAgent, endpoint: Endpoint) -> None:
    with AgnosticAgent.meter() as meter:
        reply = await agent.run("Answer the question.", "Capital of France?", Capital, endpoint=endpoint, **GREEDY)
    assert reply.output.city.lower() == "paris"
    assert meter.usage == reply.usage
