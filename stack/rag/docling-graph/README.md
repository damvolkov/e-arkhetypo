# rag/docling-graph

[docling-graph](https://github.com/docling-project/docling-graph) (IBM, MIT) as a service: a document goes in, its
knowledge graph lands in FalkorDB. Docling converts, the LLM slot extracts through a Pydantic template, and
docling-graph's own Cypher exporter writes the graph — Neo4j constraints become FalkorDB indexes, nothing else is changed.

| Route | |
|---|---|
| `POST /graph/file` | multipart `file`, form `graph` (FalkorDB graph name, default `docling`), form `template` (a `Template` bank value, default `DG_TEMPLATE`) → `{graph, nodes, edges, statements}` |
| `POST /graph/url` | form `url` (the server fetches it; loopback addresses are refused), form `graph`, form `template` |
| `GET /health` | 200 only when docling, the LLM slot and FalkorDB all answer; a down one is a 503 |

| Piece | What |
|---|---|
| `Dockerfile`, `app.py` | the image: docling-graph + a thin FastAPI door; torch is the CPU wheel (conversion runs on docling-serve) |
| `sanitize.py`, `template.py` | Cypher control-byte guard, and the `Template` allowlist the routes validate against |
| `templates/` | mounted read-only at `/app/templates`; the bank names what a request may pick (`document`, `paper`) — a new document type is a file and a bank entry |
| `compose.yml` | host network, loopback `:45850`; `DG_*` point it at docling, the LLM, FalkorDB |
| `docling-graph.service` | the systemd user unit |

## Notes

- A template declares its own `edge()` helper (`Field(json_schema_extra={"edge_label": …})`); docling-graph exports none.
- Provider is `vllm`: LiteLLM needs a provider prefix, `openai` + a bare model name fails.
- `Entity.kind` is a closed `StrEnum`; the `paper` template splits `Author` / `Concept` / `Dataset` / `Organization` so a paper's cited names stop drowning its real content (rag.pdf: 240/340 persons under `document`, 116 typed nodes under `paper`).
- A load is **atomic and replaces**: it builds into a `<name>__dgtmp` staging graph and `GRAPH.COPY`-swaps it over `name` at the end. A failure mid-build leaves the previous graph untouched and cleans staging, so a re-run reflects the latest build instead of accumulating. Extraction is still stochastic — the same PDF twice gives overlapping, not identical, graphs.
- Boot does not depend on the database: FalkorDB connects lazily on first use, so a dependency down is a 503 on `/health` and on a build, never a crash at startup.
- Cypher strings are scrubbed of raw control bytes before they reach FalkorDB, which reads a statement as a C string and cuts it at a NUL (the 502 class); `tab`/`LF`/`CR` are kept.
- One build at a time (a semaphore): each holds the LLM slot for ~1.5 min on a 15-page paper.
- On the host FalkorDB is `findr-falkordb` (`:45018`); a build writes into the graph named by `graph`.

## Up

```bash
docker compose up -d --build --wait
install -m 644 docling-graph.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now docling-graph
```
