"""providers/adapters/shapes/pyshacl: pySHACL behind `ShapesPort` — the reference engine, the arbiter of the CI.

Pure Python over rdflib, every constraint SHACL defines (SPARQL ones included, `advanced`), slow: each call parses both
graphs and validates on a worker thread — one at a time: rdflib's SPARQL parser (pyparsing) is not thread-safe, and two
validations at once fail inside it (`Param.postParse2`, measured). What it says is what the other engines must say."""

from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Self

import anyio
from pyshacl import validate
from rdflib import Graph
from rdflib.namespace import SH

from e_infra.infra.errors import ShapesError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.ports.shapes import Report, Violation
from e_infra.ports.triples import Serialization

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rdflib.term import Node

FORMATS: Final[Mapping[Serialization, str]] = MappingProxyType(
    {
        Serialization.TURTLE: "turtle",
        Serialization.NTRIPLES: "nt",
        Serialization.NQUADS: "nquads",
        Serialization.TRIG: "trig",
        Serialization.JSONLD: "json-ld",
        Serialization.RDFXML: "xml",
    }
)


class PyshaclShapesAdapter:
    """pySHACL behind `ShapesPort`, a call per thread."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("pyshacl", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.THREAD)

    __slots__ = ("_gate",)

    def __init__(self) -> None:
        ### one validation in flight: rdflib's SPARQL parsing is not thread-safe.
        self._gate = anyio.CapacityLimiter(1)

    ##### PRIVATE #####

    @staticmethod
    def _validate_run(data: bytes, shapes: bytes, serialization: Serialization) -> Report:
        try:
            graph = Graph().parse(data=data, format=FORMATS[serialization])
            rules = Graph().parse(data=shapes, format="turtle")
        except Exception as error:
            msg = f"{type(error).__name__}: {error}"
            raise ShapesError(msg) from error
        conforms, report, _ = validate(graph, shacl_graph=rules, advanced=True)
        match report:
            case Graph():
                pass
            case _:
                msg = f"pyshacl answered a report that is not a graph: {type(report).__name__}"
                raise ShapesError(msg)
        violations = tuple(
            Violation(
                focus_node=str(report.value(each, SH.focusNode)),
                message=PyshaclShapesAdapter._validate_text(report.value(each, SH.resultMessage)),
                source_shape=PyshaclShapesAdapter._validate_text(report.value(each, SH.sourceShape)),
                component=PyshaclShapesAdapter._validate_text(report.value(each, SH.sourceConstraintComponent)),
                path=PyshaclShapesAdapter._validate_text(report.value(each, SH.resultPath)),
            )
            for each in report.objects(None, SH.result)
        )
        return Report(conforms=bool(conforms), violations=violations)

    @staticmethod
    def _validate_text(found: Node | None) -> str | None:
        return None if found is None else str(found)

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        logger.info("pyshacl opened")
        return self

    async def __aexit__(self, *exc: object) -> None:
        logger.info("pyshacl closed")

    async def health(self) -> bool:
        """An empty graph against no shape conforms."""
        return (await self.validate(b"", b"")).conforms is True

    async def validate(self, data: bytes, shapes: bytes, serialization: Serialization = Serialization.TURTLE) -> Report:
        return await anyio.to_thread.run_sync(self._validate_run, data, shapes, serialization, limiter=self._gate)
