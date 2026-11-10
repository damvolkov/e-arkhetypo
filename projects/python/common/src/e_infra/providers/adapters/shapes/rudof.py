"""providers/adapters/shapes/rudof: rudof behind `ShapesPort` — Rust, in process, the fast engine of every round.

rudof (0.3.35) runs SPARQL-based constraints (`sh:sparql`) natively — measured: it agrees with the oracle on all 23
pairs, the eight SPARQL shapes included (an older rudof skipped them). The contract with
pySHACL is what keeps that true. Each call builds its own engine on a worker thread: pyrudof's objects never cross
threads."""

from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Self

import anyio
import pyrudof

from e_infra.infra.errors import ShapesError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.ports.shapes import Report, Violation
from e_infra.ports.triples import Serialization

if TYPE_CHECKING:
    from collections.abc import Mapping

FORMATS: Final[Mapping[Serialization, pyrudof.RDFFormat]] = MappingProxyType(
    {
        Serialization.TURTLE: pyrudof.RDFFormat.Turtle,
        Serialization.NTRIPLES: pyrudof.RDFFormat.NTriples,
        Serialization.NQUADS: pyrudof.RDFFormat.NQuads,
        Serialization.TRIG: pyrudof.RDFFormat.TriG,
        Serialization.JSONLD: pyrudof.RDFFormat.JsonLd,
        Serialization.RDFXML: pyrudof.RDFFormat.RdfXml,
    }
)

### an empty graph as rudof reads one: it refuses empty input, not a document that holds no triple.
EMPTY: Final[str] = "# no triples\n"


class RudofShapesAdapter:
    """rudof behind `ShapesPort`, an engine per call."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("rudof", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.THREAD)

    ##### PRIVATE #####

    @staticmethod
    def _validate_run(data: bytes, shapes: bytes, serialization: Serialization) -> Report:
        engine = pyrudof.Rudof(pyrudof.RudofConfig())
        try:
            engine.read_shacl(shapes.decode())
            engine.read_data(data.decode() or EMPTY, format=FORMATS[serialization])
        except Exception as error:
            msg = f"{type(error).__name__}: {error}"
            raise ShapesError(msg) from error
        report = engine.validate_shacl()
        violations = tuple(
            Violation(
                focus_node=str(each.focus_node),
                message=str(each.message).strip('"'),
                source_shape=str(each.source_shape),
                component=str(each.constraint_component),
                path=None if each.path is None else str(each.path),
            )
            for each in report.violations
        )
        return Report(conforms=bool(report.conforms), violations=violations)

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        logger.info("rudof opened")
        return self

    async def __aexit__(self, *exc: object) -> None:
        logger.info("rudof closed")

    async def health(self) -> bool:
        """An empty graph against no shape conforms."""
        return (await self.validate(b"", b"@prefix sh: <http://www.w3.org/ns/shacl#> .")).conforms is True

    async def validate(self, data: bytes, shapes: bytes, serialization: Serialization = Serialization.TURTLE) -> Report:
        return await anyio.to_thread.run_sync(self._validate_run, data, shapes, serialization)
