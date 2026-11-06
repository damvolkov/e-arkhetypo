"""tests/unit/e_infra/providers/adapters/triples/contract: `TriplesPort` as a contract — load and dump by named
graph, the union as the default graph, typed substitutions, ask, update, refusals.

Oxigraph in memory is the one implementation today; a SPARQL server joins this parametrization the day it is built,
and must answer the same."""

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from e_infra.infra.errors import TriplesError
from e_infra.ports.triples import Binding, Serialization, Term, TermKind, TriplesPort
from e_infra.providers.adapters.triples.oxigraph import OxigraphTriplesAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

RDF: Final[Path] = Path(__file__).resolve().parents[5] / "resources" / "rdf"
CORE: Final[str] = "urn:test:core"
APP: Final[str] = "urn:test:app"
CLASSES: Final[str] = "PREFIX owl: <http://www.w3.org/2002/07/owl#> SELECT ?c WHERE { ?c a owl:Class } ORDER BY ?c"


@pytest.fixture(params=["oxigraph"])
async def triples(request: pytest.FixtureRequest) -> AsyncIterator[TriplesPort]:
    async with OxigraphTriplesAdapter(page=2) as store:
        yield store


async def loaded(store: TriplesPort) -> tuple[int, int]:
    core = await store.load(CORE, (RDF / "core.ttl").read_bytes(), Serialization.TURTLE)
    app = await store.load(APP, (RDF / "app.ttl").read_bytes(), Serialization.TURTLE)
    return core, app


async def test_triples_meets_the_port(triples: TriplesPort) -> None:
    assert (isinstance(triples, TriplesPort), await triples.health()) == (True, True)


async def test_triples_load_counts_each_graph(triples: TriplesPort) -> None:
    core, app = await loaded(triples)
    assert (await triples.graphs(), core > 0, app > 0) == ({CORE: core, APP: app}, True, True)


async def test_triples_dump_reloads_to_the_same_graph(triples: TriplesPort) -> None:
    await loaded(triples)
    dumped = await triples.dump(CORE)
    await triples.clear(CORE)
    assert await triples.graphs() == {APP: (await triples.graphs())[APP]}
    await triples.load(CORE, dumped, Serialization.NTRIPLES)
    assert sorted((await triples.dump(CORE)).splitlines()) == sorted(dumped.splitlines())


async def test_triples_select_sees_the_union_of_named_graphs_lazily(triples: TriplesPort) -> None:
    await loaded(triples)
    found = [row["c"] async for row in triples.select(CLASSES)]
    assert ("https://example.org/core#Person" in found, "https://example.org/app#Driver" in found) == (True, True)
    assert found == sorted(found)


async def test_triples_substitutions_bind_typed_terms_never_text(triples: TriplesPort) -> None:
    await loaded(triples)
    sparql = "SELECT ?label WHERE { ?c <http://www.w3.org/2000/01/rdf-schema#label> ?label }"
    persona = Term(value="https://example.org/core#Person", kind=TermKind.IRI)
    assert [row["label"] async for row in triples.select(sparql, {"c": persona})] == ["Person"]
    hostile = Term(value='x" } ; DROP ALL ; { "', kind=TermKind.LITERAL)
    assert [row async for row in triples.select(sparql.replace("?c ", "?x "), {"label": hostile})] == []
    assert sum((await triples.graphs()).values()) > 0


async def test_triples_ask_and_update(triples: TriplesPort) -> None:
    await loaded(triples)
    assert await triples.ask(f"ASK {{ GRAPH <{CORE}> {{ ?s ?p ?o }} }}")
    await triples.update(f"CLEAR GRAPH <{CORE}>")
    assert (await triples.ask(f"ASK {{ GRAPH <{CORE}> {{ ?s ?p ?o }} }}"), CORE in await triples.graphs()) == (
        False,
        False,
    )


async def _drain(store: TriplesPort, sparql: str) -> list[Binding]:
    return [row async for row in store.select(sparql)]


REFUSALS: Final[dict[str, Callable[[TriplesPort], Awaitable[object]]]] = {
    "load": lambda store: store.load(CORE, b"@prefix x: <https://x/> . x:a x:b", Serialization.TURTLE),
    "select": lambda store: _drain(store, "SELECT WHERE {"),
    "ask": lambda store: store.ask("ASK {"),
    "update": lambda store: store.update("CLEAR NOTHING"),
}


@pytest.mark.parametrize("call", sorted(REFUSALS))
async def test_triples_refusals_are_triples_errors(triples: TriplesPort, call: str) -> None:
    with pytest.raises(TriplesError):
        await REFUSALS[call](triples)


async def test_triples_a_stream_left_halfway_closes_cleanly(triples: TriplesPort) -> None:
    await loaded(triples)
    stream = triples.select(CLASSES)
    first = await anext(stream)
    await stream.aclose()
    assert (bool(first["c"]), len([row async for row in triples.select(CLASSES)]) > 1) == (True, True)


async def test_triples_convert_reads_one_syntax_into_another_without_the_store(triples: TriplesPort) -> None:
    turtle = (RDF / "core.ttl").read_bytes()
    converted = await triples.convert(turtle, Serialization.TURTLE, Serialization.NTRIPLES)
    untouched = await triples.graphs()
    count = await triples.load(CORE, converted, Serialization.NTRIPLES)
    assert (untouched, len(converted.splitlines()), count > 0) == ({}, count, True)


async def test_triples_convert_refuses_what_does_not_parse(triples: TriplesPort) -> None:
    with pytest.raises(TriplesError):
        await triples.convert(b"<a> <b> .", Serialization.TURTLE, Serialization.NTRIPLES)


async def test_triples_a_typed_literal_binds_with_its_datatype(triples: TriplesPort) -> None:
    await triples.load(
        CORE, b'<urn:a> <urn:p> "7"^^<http://www.w3.org/2001/XMLSchema#integer> .', Serialization.NTRIPLES
    )
    seven = Term(value="7", datatype="http://www.w3.org/2001/XMLSchema#integer")
    assert [row async for row in triples.select("SELECT ?s WHERE { ?s <urn:p> ?n }", {"n": seven})] == [{"s": "urn:a"}]


async def test_triples_a_blank_node_comes_back_as_its_label(triples: TriplesPort) -> None:
    await triples.load(CORE, b"_:x <urn:p> <urn:o> .", Serialization.NTRIPLES)
    (row,) = [row async for row in triples.select("SELECT ?s WHERE { ?s <urn:p> <urn:o> }")]
    assert row["s"].startswith("_:")


async def test_triples_an_adapter_not_open_refuses() -> None:
    with pytest.raises(TriplesError, match="not open"):
        await OxigraphTriplesAdapter(page=2).graphs()
