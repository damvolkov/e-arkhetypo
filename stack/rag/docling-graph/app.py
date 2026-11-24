"""docling-graph as a service: a document in, a knowledge graph in FalkorDB out."""

import asyncio
import re
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Final

import httpx
import networkx as nx
from docling_graph import run_pipeline
from docling_graph.core.exporters.cypher_exporter import CypherExporter
from docling_graph.exceptions import DoclingGraphError
from falkordb import FalkorDB
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.exceptions import RedisError, ResponseError

from sanitize import sanitize
from template import Template

##### CONFIG #####


class Settings(BaseSettings):
    """The services this one stands on, by host loopback address."""

    model_config = SettingsConfigDict(frozen=True, env_prefix="DG_")

    docling_url: str = "http://127.0.0.1:45800"
    llm_url: str = "http://127.0.0.1:45100/v1"
    llm_key: SecretStr = SecretStr("local-dev")
    llm_model: str = "demian-model"
    falkordb_host: str = "127.0.0.1"
    falkordb_port: int = 45018
    falkordb_password: SecretStr = SecretStr("falkordb")
    template: Template = Template.DOCUMENT
    contract: str = "auto"


class Built(BaseModel):
    """What one document became."""

    graph: str
    nodes: int
    edges: int
    statements: int


GRAPH_NAME: Final = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
STAGING_SUFFIX: Final = "__dgtmp"
NEO4J_CONSTRAINT: Final = re.compile(r"^CREATE CONSTRAINT \S+ IF NOT EXISTS FOR (\(n:.+\)) REQUIRE n\.id IS UNIQUE$")
STATEMENT_END: Final = re.compile(r";[ \t]*(?:\n|$)")
GATE: Final = asyncio.Semaphore(1)

##### PIPELINE #####


def _extract(source: str, settings: Settings, template: Template) -> nx.DiGraph:
    context = run_pipeline(
        {
            "source": source,
            "template": template.value,
            "backend": "llm",
            "inference": "remote",
            "provider_override": "vllm",
            "model_override": settings.llm_model,
            "llm_overrides": {
                "connection": {"base_url": settings.llm_url, "api_key": settings.llm_key.get_secret_value()}
            },
            "docling_serve_url": settings.docling_url,
            "processing_mode": "many-to-one",
            "extraction_contract": settings.contract,
            "use_chunking": True,
        }
    )
    return context.knowledge_graph


def _statements(graph: nx.DiGraph) -> list[str]:
    """The graph as openCypher: docling-graph's own exporter, Neo4j constraints turned into FalkorDB indexes."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "graph.cypher"
        CypherExporter().export(graph, path)
        lines = [line for line in sanitize(path.read_text()).splitlines() if not line.startswith("//")]
    parts = (part.strip() for part in STATEMENT_END.split("\n".join(lines)))
    return [NEO4J_CONSTRAINT.sub(r"CREATE INDEX FOR \1 ON (n.id)", part) for part in parts if part]


def _load(db: FalkorDB, name: str, statements: list[str]) -> None:
    """Build into a temp graph, then swap it over `name`: a failure never leaves a partial graph.

    The swap is COPY over an absent target, so `name` is dropped first; a re-run
    therefore replaces the graph with the latest build rather than accumulating.
    """
    staging = db.select_graph(_staging(name))
    try:
        _write(staging, statements)
        _drop(db, name)
        staging.copy(name)
    finally:
        _drop(db, _staging(name))


def _write(target, statements: list[str]) -> None:
    indexes = [s for s in statements if s.startswith("CREATE INDEX")]
    writes = [s for s in statements if not s.startswith("CREATE INDEX")]
    ### An index that exists is not an error: a re-run into the same staging must be idempotent.
    [_index(target, s) for s in indexes]
    [target.query(s) for s in writes]


def _index(target, statement: str) -> None:
    with suppress(ResponseError):
        target.query(statement)


def _drop(db: FalkorDB, name: str) -> None:
    """Delete a graph; deleting one that is absent is not an error."""
    with suppress(ResponseError):
        db.select_graph(name).delete()


def _staging(name: str) -> str:
    """The temp graph a build writes into before it is swapped over `name`."""
    return f"{name}{STAGING_SUFFIX}"


def _falkor(state) -> FalkorDB:
    """The FalkorDB client, built on first use and kept thereafter.

    FalkorDB connects when constructed, so building it eagerly in the lifespan
    would crash startup whenever the database is down. Deferring it lets the
    service boot and makes a dead database a `RedisError` on the request that
    needs it (a 503), which the provider can recover from on a later call.
    """
    db = getattr(state, "db", None)
    if db is None:
        settings = state.settings
        db = state.db = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            password=settings.falkordb_password.get_secret_value(),
        )
    return db


async def _build(request: Request, source: str, name: str, template: Template) -> Built:
    state = request.app.state
    async with GATE:
        graph = await asyncio.to_thread(_extract, source, state.settings, template)
        statements = await asyncio.to_thread(_statements, graph)
        await asyncio.to_thread(_load, _falkor(state), name, statements)
    return Built(graph=name, nodes=graph.number_of_nodes(), edges=graph.number_of_edges(), statements=len(statements))


##### APP #####


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.settings = Settings()
    async with httpx.AsyncClient(timeout=5) as http:
        app.state.http = http
        yield


app = FastAPI(title="docling-graph", lifespan=lifespan)


@app.exception_handler(DoclingGraphError)
async def _pipeline_failed(_: Request, err: DoclingGraphError) -> JSONResponse:
    return JSONResponse({"error": type(err).__name__, "detail": str(err)}, status_code=502)


@app.exception_handler(httpx.HTTPError)
@app.exception_handler(RedisError)
async def _dependency_down(_: Request, err: Exception) -> JSONResponse:
    return JSONResponse({"error": type(err).__name__, "detail": str(err)}, status_code=503)


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Up only when docling, the LLM slot and FalkorDB all answer; a down one is a 503."""
    state = request.app.state
    auth = {"Authorization": f"Bearer {state.settings.llm_key.get_secret_value()}"}
    docling, llm = await asyncio.gather(
        state.http.get(f"{state.settings.docling_url}/health"),
        state.http.get(f"{state.settings.llm_url}/models", headers=auth),
    )
    docling.raise_for_status()
    llm.raise_for_status()
    await asyncio.to_thread(_falkor(state).connection.ping)
    return {"docling": "ok", "llm": "ok", "falkordb": "ok"}


@app.post("/graph/file")
async def graph_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    graph: Annotated[str, Form(pattern=GRAPH_NAME)] = "docling",
    template: Annotated[Template | None, Form()] = None,
) -> Built:
    """Build the graph of an uploaded document into FalkorDB."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / Path(file.filename or "upload").name
        target.write_bytes(await file.read())
        return await _build(request, str(target), graph, template or request.app.state.settings.template)


@app.post("/graph/url")
async def graph_url(
    request: Request,
    url: Annotated[str, Form()],
    graph: Annotated[str, Form(pattern=GRAPH_NAME)] = "docling",
    template: Annotated[Template | None, Form()] = None,
) -> Built:
    """Build the graph of a document the server fetches into FalkorDB."""
    return await _build(request, url, graph, template or request.app.state.settings.template)
