"""providers/adapters/triples/oxigraph: Oxigraph in memory behind `TriplesPort` — Rust, in-process, one store a process.

Every call is CPU in Rust, so it runs off the loop — on the adapter's own single worker thread: an answer pyoxigraph hands
back cannot cross threads (pyo3, unsendable), so the query, every page pulled from it and its end live on that one
thread, in a cursor the loop never touches. A `select` is pulled a page (OXIGRAPH_PAGE rows) per hop, so an answer
streams without being collected. Substitutions are bound as a trailing `VALUES` block of terms Oxigraph serializes —
escaped, never the caller's text — so any variable binds, projected or not. The store holds
a release and is rebuilt from it — never a source of truth, nothing on disk."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Self

import pyoxigraph as ox

from e_infra.infra.errors import TriplesError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, Opened, ProviderSpec, Workload
from e_infra.ports.triples import Binding, Serialization, Term, TermKind

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Iterator, Mapping

FORMATS: Final[Mapping[Serialization, ox.RdfFormat]] = MappingProxyType(
    {
        Serialization.TURTLE: ox.RdfFormat.TURTLE,
        Serialization.NTRIPLES: ox.RdfFormat.N_TRIPLES,
        Serialization.NQUADS: ox.RdfFormat.N_QUADS,
        Serialization.TRIG: ox.RdfFormat.TRIG,
        Serialization.JSONLD: ox.RdfFormat.JSON_LD,
        Serialization.RDFXML: ox.RdfFormat.RDF_XML,
    }
)
### what pyoxigraph raises on RDF or SPARQL it refuses.
REFUSED: Final[tuple[type[Exception], ...]] = (SyntaxError, ValueError, OSError)


class OxigraphTriplesAdapter:
    """One in-memory Oxigraph store behind `TriplesPort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "oxigraph", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.THREAD, warmup=True
    )
    store = Opened[ox.Store](TriplesError)

    __slots__ = ("_page", "_store", "_worker")

    def __init__(self, *, page: int) -> None:
        self._page = page
        self._store: ox.Store | None = None
        self._worker: ThreadPoolExecutor | None = None

    ##### PRIVATE #####

    @staticmethod
    def _common_term(term: Term) -> ox.NamedNode | ox.Literal:
        match term:
            case Term(kind=TermKind.IRI, value=value):
                return ox.NamedNode(value)
            case Term(value=value, datatype=str() as datatype):
                return ox.Literal(value, datatype=ox.NamedNode(datatype))
            case _:
                return ox.Literal(term.value, language=term.language)

    @classmethod
    def _common_bound(cls, sparql: str, terms: Mapping[str, Term] | None) -> str:
        """The query with its substitutions as a trailing `VALUES` block of serialized terms; untouched without any."""
        match sorted((terms or {}).items()):
            case []:
                return sparql
            case bound:
                names = " ".join(f"?{name}" for name, _ in bound)
                row = " ".join(str(cls._common_term(term)) for _, term in bound)
                return f"{sparql}\nVALUES ({names}) {{ ({row}) }}"

    @staticmethod
    def _select_value(node: ox.NamedNode | ox.BlankNode | ox.Literal) -> str:
        match node:
            case ox.BlankNode():
                return f"_:{node.value}"
            case _:
                return node.value

    async def _common_run[T](self, work: Callable[[], T]) -> T:
        """A store call on the adapter's own thread, its refusal as the port's error."""
        try:
            return await asyncio.get_running_loop().run_in_executor(self._worker, work)
        except REFUSED as error:
            logger.warning("oxigraph refused", error=str(error))
            raise TriplesError(str(error)) from error

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._store = ox.Store()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oxigraph")
        logger.info("oxigraph opened", page=self._page)
        return self

    async def __aexit__(self, *exc: object) -> None:
        worker, self._worker, self._store = self._worker, None, None
        _ = worker is not None and worker.shutdown(wait=True)
        logger.info("oxigraph closed")

    async def health(self) -> bool:
        """The store answers an empty ask."""
        await self.ask("ASK { }")
        return True

    async def load(self, graph: str, data: bytes, serialization: Serialization) -> int:
        store, node = self.store, ox.NamedNode(graph)

        def run() -> int:
            store.load(data, format=FORMATS[serialization], to_graph=node)
            return len(list(store.quads_for_pattern(None, None, None, node)))

        return await self._common_run(run)

    async def convert(self, data: bytes, source: Serialization, target: Serialization) -> bytes:
        return await self._common_run(
            lambda: ox.serialize(ox.parse(data, format=FORMATS[source]), format=FORMATS[target]) or b""
        )

    async def dump(self, graph: str, serialization: Serialization = Serialization.NTRIPLES) -> bytes:
        store = self.store
        return await self._common_run(
            lambda: store.dump(format=FORMATS[serialization], from_graph=ox.NamedNode(graph)) or b""
        )

    async def clear(self, graph: str) -> None:
        store = self.store
        await self._common_run(
            lambda: store.remove_graph(ox.NamedNode(graph)) if ox.NamedNode(graph) in store.named_graphs() else None
        )

    async def graphs(self) -> dict[str, int]:
        store = self.store

        def run() -> dict[str, int]:
            counted = {
                named.value: len(list(store.quads_for_pattern(None, None, None, named)))
                for named in store.named_graphs()
                if isinstance(named, ox.NamedNode)
            }
            ### a graph emptied by an update stays registered: it holds nothing, so it is no graph.
            return {name: size for name, size in counted.items() if size}

        return await self._common_run(run)

    async def select(self, sparql: str, substitutions: Mapping[str, Term] | None = None) -> AsyncGenerator[Binding]:
        """The solutions of a SELECT over the union of graphs, a page per hop to the store's thread."""
        store, query = self.store, self._common_bound(sparql, substitutions)
        ### the cursor holds pyoxigraph's answer; only the store's thread fills it, reads it, and empties it.
        cursor: dict[str, Iterator[ox.QuerySolution]] = {}

        def start() -> list[str]:
            match store.query(query, use_default_graph_as_union=True):
                case ox.QuerySolutions() as found:
                    cursor["rows"] = iter(found)
                    return [variable.value for variable in found.variables]
                case _:
                    msg = "select takes a SELECT query"
                    raise TriplesError(msg)

        def page() -> list[Binding]:
            return [
                {
                    name: self._select_value(value)
                    for name, value in zip(variables, row, strict=True)
                    if value is not None
                }
                for row in islice(cursor["rows"], self._page)
            ]

        variables = await self._common_run(start)
        try:
            ### a real loop: the stream is pulled a page at a time until the store hands back none.
            while rows := await self._common_run(page):
                for row in rows:
                    yield row
        finally:
            await self._common_run(cursor.clear)

    async def ask(self, sparql: str, substitutions: Mapping[str, Term] | None = None) -> bool:
        store, query = self.store, self._common_bound(sparql, substitutions)
        return await self._common_run(lambda: bool(store.query(query, use_default_graph_as_union=True)))

    async def update(self, sparql: str) -> None:
        store = self.store
        await self._common_run(lambda: store.update(sparql))
