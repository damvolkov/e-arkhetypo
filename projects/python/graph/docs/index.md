# e-graph

**e-stack** graph system template: **LangGraph** runtime, **rustworkx** topology, **React Flow** canvas.
Served by Litestar + Granian + msgspec on uv · ruff · ty · tach · prek · pytest · zensical · docker.

## Quickstart

```bash
make install    # materialize infra/ops/adapters + shared files, uv sync, git hooks
make check      # lint + types + architecture + drift + tests
make serve      # build the canvas + start the server: api + canvas at :8000
make docs       # serve this site at http://localhost:8001
make up         # docker compose up
```

## Layout

The service lives in `src/e_graph/`, layered by [tach](https://tach.dev). `src/infra/`, `src/ops/` and
`src/adapters/` are **materialized** from the infra blueprint by `make infra` — edit them there, never here:

| Module | Layer | Purpose |
|---|---|---|
| [`e_graph.main`](reference/e_graph/main.md) | api | Composition root: explicit registration only, `create_app` for granian |
| [`e_graph.cli`](reference/e_graph/cli.md) | api | `e-graph darts check \| plan` (the static check) and `e-graph lab list \| graph \| simulate` (draw and rehearse) |
| [`e_graph.api.deps`](reference/e_graph/api/deps.md) | api | Dependency chains: system root, store, pipeline, correlation id |
| [`e_graph.api.router.pipelines`](reference/e_graph/api/router/pipelines.md) | api | `/api/pipelines`: list, topology, batch, stream — by id |
| [`e_graph.api.router.specs`](reference/e_graph/api/router/specs.md) | api | `/api/specs`: list, topology, svg, simulate — by pipeline and section, the spec-node level |
| [`e_graph.api.router.ui`](reference/e_graph/api/router/ui.md) | api | The canvas as a static page at `/`, its tunables at `/api/ui` |
| [`e_graph.api.state`](reference/e_graph/api/state.md) | api | Litestar's state, typed: the sealed system graph |
| [`e_graph.api.lifespan.graphs`](reference/e_graph/api/lifespan/graphs.md) | api | Build every pipeline once: the graph singletons under `system.graphs` |
| [`e_graph.pipelines.base`](reference/e_graph/pipelines/base.md) | pipelines | PipelineBuilder (declare → build) and PipelineRegistry (sweeps the pipeline folders, mounts their sections) |
| [`e_graph.pipelines.doc.graph`](reference/e_graph/pipelines/doc/graph.md) | pipelines | The demo document graph: sequence, parallel pair, join, retry loop — every section run by DARTS |
| [`e_graph.pipelines.filing.graph`](reference/e_graph/pipelines/filing/graph.md) | pipelines | A 10-K read into its XBRL facts: ingest → extract → audit → report |
| `e_graph.pipelines.<pipeline>.nodes.<section>.node` | pipelines | One node per section: runs the section's specs through the orchestrator |
| [`e_graph.instrument.graph`](reference/e_graph/instrument/graph.md) | instrument | InstrumentGraph: LangGraph builder with contract, topology (rustworkx) and run frames |
| [`e_graph.instrument.node`](reference/e_graph/instrument/node.md) | instrument | InstrumentNode: function contract in, `RunState → NodeOutput` out, always |
| [`e_graph.instrument.errors`](reference/e_graph/instrument/errors.md) | instrument | ContractError at load time, NodeError at run time |
| [`e_graph.instrument.state`](reference/e_graph/instrument/state.md) | instrument | RunState (`id` · `infra` · `context`), the contexts store and the LangGraph channels |
| [`e_graph.instrument.models`](reference/e_graph/instrument/models.md) | instrument | NodeOutput (with its START/END/MID role), RunEnd, Topology — msgspec |
| [`e_graph.logic.agent`](reference/e_graph/logic/agent.md) | engine | AgnosticAgent: one structured async call over any model provider, pooled, metered |
| [`e_graph.logic.models`](reference/e_graph/logic/models.md) | engine | The DARTS core's own models: the agent's, the specs' (kinds, slots, roles, scopes, `Call`), the catalog, the plan, the report |
| [`e_graph.logic.discover`](reference/e_graph/logic/discover.md) | logic | SpecDiscover: lazy, per section — decode specs, resolve and read their runners, judge, validate args; SystemDiscover: the whole system's static check |
| [`e_graph.logic.rules`](reference/e_graph/logic/rules.md) | logic | The coherence laws (tree, source, section), one function each — the discovery's tools |
| [`e_graph.logic.errors`](reference/e_graph/logic/errors.md) | engine | Agent errors and the discovery's `RuleError` / `CatalogError` / `AuditError` |
| [`e_graph.logic.orchestrator.core`](reference/e_graph/logic/orchestrator/core.md) | logic | OrchestratorCore: runs a section — steps in sequence, specs in a step at once; check · produce · validate · write · fallback |
| [`e_graph.logic.orchestrator.plan`](reference/e_graph/logic/orchestrator/plan.md) | logic | DagPlan: catalog → steps (topological generations), semantic specs fused by tier, fallbacks held |
| [`e_graph.logic.orchestrator.fusion`](reference/e_graph/logic/orchestrator/fusion.md) | logic | SpecFusion: many semantic specs, one agent call — briefs, shared material, fused schema, split, packing |
| [`e_graph.logic.orchestrator.lab`](reference/e_graph/logic/orchestrator/lab.md) | logic | SectionLab: a section listed, mapped, drawn (rustworkx → Graphviz on wasmtime) and rehearsed with its agent calls whole |
| `e_graph.specs.<pipeline>/<section>/<name>.yaml` | specs | One spec per file, named as the spec (`EXT-total-amount`); `wiki/` per pipeline and shared |
| `e_graph.runners.owned.<pipeline>.<section>.<name>` | runners | A runner owned by one pipeline's section: one function, named by its role |
| `e_graph.runners.agnostic.<capability>.<name>` | runners | A tool any spec may plug: one function, named by its role, its `Args` declared |
| [`e_graph.models.section`](reference/e_graph/models/section.md) | models | The closed DARTS taxonomy, in fixed order |
| [`e_graph.models.pipeline`](reference/e_graph/models/pipeline.md) | models | How the list names a pipeline |
| [`e_graph.models.ui`](reference/e_graph/models/ui.md) | models | The canvas tunables as the UI reads them |
| [`processors.doc`](reference/processors/doc.md) | processors | DocProcessor: liteparse on every page, docling-serve on the pages that hold tables, figures or scans — one engine-neutral `Document` (materialized) |
| [`adapters.docling`](reference/adapters/docling.md) | adapters | DocumentPort over docling-serve: conversions as server tasks, options from `DOCLING_*` (materialized) |
| [`adapters.otel`](reference/adapters/otel.md) | adapters | TelemetryPort over the OpenTelemetry SDK, OTLP/HTTP export — common to every system (materialized) |
| [`ops.wrappers`](reference/ops/wrappers.md) | ops | LatencyWrapper and the agnostic measuring wrappers (materialized) |
| [`infra.settings`](reference/infra/settings.md) | infra | Composed settings: one BaseSettings reader over the per-scope structs of `infra.config` (materialized) |
| [`infra.logger`](reference/infra/logger.md) | infra | Structured logging: JSON in prod, ordered plain text in dev (materialized) |

Reference pages are generated automatically from the sources: drop a new module under `src/` and it
appears here on the next build.

## DARTS

Sections run as DAGs of specs and the runners they plug — the taxonomy, the laws and the procedures
are in [DARTS](darts.md). `e-graph darts check` is the static check; `e-graph darts plan` shows a section's steps.

## Run state

Every node receives one `RunState`: `state.id`, `state.infra` (the app's singletons — `adapters`, `agent`,
`telemetry`, `graphs`) and `state.context`, the run's own ephemeral zone, stored as `context.<id>`. The
instrument releases the context when the run closes — END or failure — unless `run(state, retain=True)`;
the run span keeps a snapshot (`run.context`), so nothing is lost to telemetry.

A node returns `str` (the summary), a `dict` (keys naming `NodeOutput` fields fill its empty slots, the
rest land in `extra`), a `NodeOutput` (merged the same way), or `None`. Fields the instrument fills —
status, latency, trace ids — always stand. When the node called the agent, `usage` carries its tokens.

## Agent

`state.infra.agent.run(instructions, prompt, output, endpoint=Tier.MEDIUM, api_base=None, api_key=None,
**generation)` returns a `Reply[T]`. `output` is always structured, resolved once by type dispatch:

| `output` | Schema sent | Reply validated by | `Reply.output` |
|---|---|---|---|
| pydantic model | `model_json_schema()` | `model_validate_json` | the model instance |
| msgspec Struct / dataclass | `msgspec.json.schema` | `msgspec.json.decode(type=…)` | the instance |
| JSON Schema (`Mapping`, object root) | as given | jsonschema-rs, compiled once | the validated `dict` |

The endpoint is an `Endpoint` or a `Tier` read from `AGENT_HIGH` / `AGENT_MEDIUM` / `AGENT_LOW`; base and
key resolve run argument → endpoint → the provider's standard variables (see `.env.example`, full table
in `infra/config/agent.py`) → a dummy key for local servers. Invalid replies are retried with the
validation error (`AGENT_RETRIES`). No token limit is imposed unless the caller sets `max_tokens`; a
reply cut at it is asked again with the budget doubled, on the same retry budget.

| Error (`logic/errors.py`) | Raised when | Retried |
|---|---|---|
| `SchemaError` | the output is no known shape, or a raw schema is invalid or has no object root | never — before any call |
| `EndpointError` | a tier is unset or malformed, CUSTOM has no base, a remote provider has no key | never — before any call |
| `ProviderError` | the call itself failed: transport, timeout, auth, quota, server | no |
| `InvalidError` | every reply broke the shape | yes, with the validation error |
| `TruncatedError` | the reply was cut at the token limit, no larger budget left | yes, budget doubled |
| `RefusedError` | the model refused, or the provider's content filter blocked the reply | no |

The last three are `OutputError`s: they carry `raw`, `attempts`, `usage` and `finish`, and their message
ends in `[finish=…, attempts=…, output_tokens=…]` — what the failed node's output, span and log show. The run span
carries the request's `run.correlation_id`.

Unit tests mock the provider client (pytest-mock); integration tests replay cassettes recorded against
the local vLLM (pytest-recording, auth headers redacted). `make record` re-records them — set
`VLLM_API_KEY`, or point `AGENT_MEDIUM` elsewhere.
