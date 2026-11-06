"""tests/unit/e_infra/providers/adapters/shapes/contract: `ShapesPort` as a contract — pySHACL (the arbiter) and
rudof (the fast engine) say the same on every case, and an engine that cannot run a constraint says so.

The data is a small model (`resources/rdf`: core, app) plus each case's instances; the shapes its `shapes.ttl`."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from e_infra.infra.errors import ShapesError
from e_infra.ports.shapes import Report, ShapesPort, Violation
from e_infra.ports.triples import Serialization
from e_infra.providers.adapters.shapes.pyshacl import PyshaclShapesAdapter
from e_infra.providers.adapters.shapes.rudof import RudofShapesAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

RDF: Final[Path] = Path(__file__).resolve().parents[5] / "resources" / "rdf"
BASE: Final[str] = "\n".join((RDF / name).read_text() for name in ("core.ttl", "app.ttl"))
SHAPES: Final[bytes] = (RDF / "shapes.ttl").read_bytes()
CASES: Final[dict[str, tuple[bytes, frozenset[str]]]] = {
    "conforming": ((RDF / "data.ttl").read_bytes(), frozenset()),
    "wrong-datatype-and-no-policy": (
        (RDF / "invalid.ttl").read_bytes(),
        frozenset({"MinCountConstraintComponent@holds", "DatatypeConstraintComponent@age"}),
    ),
}
TINY: Final[
    bytes
] = b"""@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <https://ex/> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:PS a sh:NodeShape ; sh:targetClass ex:P ; sh:property [ sh:path ex:age ; sh:datatype xsd:integer ; sh:minCount 1 ] ."""
SPARQL: Final[bytes] = b"""@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <https://ex/> .
ex:Unique a sh:NodeShape ; sh:targetClass ex:P ;
    sh:sparql [ sh:message "no bad" ; sh:prefixes ex: ; sh:select "SELECT $this WHERE { $this ex:bad ?x }" ] .
ex: sh:declare [ sh:prefix "ex" ; sh:namespace "https://ex/"^^<http://www.w3.org/2001/XMLSchema#anyURI> ] ."""


@pytest.fixture(params=["pyshacl", "rudof"])
async def shapes(request: pytest.FixtureRequest) -> AsyncIterator[ShapesPort]:
    engine: ShapesPort = PyshaclShapesAdapter() if request.param == "pyshacl" else RudofShapesAdapter()
    async with engine:
        yield engine


async def test_shapes_meets_the_port(shapes: ShapesPort) -> None:
    assert isinstance(shapes, ShapesPort)


async def test_shapes_health_answers(shapes: ShapesPort) -> None:
    assert await shapes.health() is True


async def test_shapes_an_empty_graph_is_validated_not_refused(shapes: ShapesPort) -> None:
    targeted = (
        b"@prefix sh: <http://www.w3.org/ns/shacl#> . <urn:s> a sh:NodeShape ; sh:targetNode <urn:n> ; "
        b"sh:property [ sh:path <urn:p> ; sh:minCount 1 ] ."
    )
    assert (
        (await shapes.validate(b"", targeted)).conforms,
        len((await shapes.validate(b"", targeted)).violations),
    ) == (
        False,
        1,
    )


async def test_shapes_conforming_data_conforms(shapes: ShapesPort) -> None:
    report = await shapes.validate(b"@prefix ex: <https://ex/> . ex:a a ex:P ; ex:age 3 .", TINY)
    assert report == Report(conforms=True)


async def test_shapes_a_violation_names_its_node_path_and_component(shapes: ShapesPort) -> None:
    report = await shapes.validate(b"@prefix ex: <https://ex/> . ex:b a ex:P .", TINY)
    [violation] = report.violations
    assert (report.conforms, violation.focus_node, violation.path) == (False, "https://ex/b", "https://ex/age")
    assert violation.key == "MinCountConstraintComponent@age"


@pytest.mark.parametrize("case", sorted(CASES))
async def test_shapes_fire_exactly_what_the_case_names(shapes: ShapesPort, case: str) -> None:
    data, fires = CASES[case]
    report = await shapes.validate(f"{BASE}\n{data.decode()}".encode(), SHAPES)
    assert (report.conforms, report.keys) == (not fires, fires)


async def test_shapes_a_sparql_constraint_runs_on_every_engine(shapes: ShapesPort) -> None:
    """Neither engine skips `sh:sparql`: one that did would have to answer None, never a pass."""
    passing = await shapes.validate(b"@prefix ex: <https://ex/> . ex:a a ex:P .", SPARQL)
    failing = await shapes.validate(b"@prefix ex: <https://ex/> . ex:a a ex:P ; ex:bad 1 .", SPARQL)
    assert (passing.conforms, passing.skipped, failing.conforms, failing.keys) == (
        True,
        (),
        False,
        frozenset({"Unique"}),
    )


async def test_shapes_data_that_does_not_parse_is_a_shapes_error(shapes: ShapesPort) -> None:
    with pytest.raises(ShapesError):
        await shapes.validate(b"@prefix ex: <https://ex/> . ex:a ex:b", TINY, Serialization.TURTLE)


def test_shapes_a_named_shape_is_its_own_key() -> None:
    assert Violation(focus_node="x", source_shape="https://example.org/app#DriverShape").key == "DriverShape"


async def test_shapes_validations_at_once_agree_with_one_at_a_time(shapes: ShapesPort) -> None:
    """Concurrent calls on one engine: pySHACL's parser is not thread-safe, so the adapter must keep them apart."""
    data = [f"{BASE}\n{body.decode()}".encode() for body, _ in 3 * list(CASES.values())]
    alone = [await shapes.validate(each, SHAPES) for each in data]
    together = await asyncio.gather(*(shapes.validate(each, SHAPES) for each in data))
    assert [report.keys for report in together] == [report.keys for report in alone]
