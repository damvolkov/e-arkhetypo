# e-infra

The python infra blueprint of the e-stack template systems: **uv · ruff · ty · tach · prek · pytest · zensical**.

## What this is

Every module a system materializes lives once here — this is the infra blueprint the e-taxis wizard reads
when it exports a new project, offering the user the parts that are optional. Services do **not** depend on
this package at runtime: `make common` in any system copies the sections of `src/e_infra/` into its own `src/`
(byte-identical except import paths), so each system ships self-contained and this stays the single source
of truth. `make common-check` fails the moment a copy drifts.

## Modules

All sources live under `src/e_infra/`, layered by [tach](https://tach.dev) — high to low:
`engines | processors | providers -> ports -> infra -> ops`. The purpose of each module is its first docstring line, verbatim;
reference pages are generated from the sources: drop a new module under `src/` and it appears on the next
build.

### infra — the project's internal infrastructure

| Module | Purpose |
|---|---|
| [`e_infra.infra.background`](reference/e_infra/infra/background.md) | the in-process task supervisor — jobs as tasks of one task group, retries, progress, cancel, clocks. |
| [`e_infra.infra.events`](reference/e_infra/infra/events.md) | events delivered in this process — subscribers by event type, none known to the publisher. |
| [`e_infra.infra.errors`](reference/e_infra/infra/errors.md) | typed exception hierarchy — every domain exception inherits from CoreError; providers translate their library's errors into it. |
| [`e_infra.infra.logger`](reference/e_infra/infra/logger.md) | structured JSON in prod, ordered plain text in dev/local. |
| [`e_infra.infra.proxy`](reference/e_infra/infra/proxy.md) | import-safe lazy singletons — the object exists at module level, its load runs on first use. |
| [`e_infra.infra.state`](reference/e_infra/infra/state.md) | the app resource graph — dynamic attribute access all the way down. |
| [`e_infra.infra.struct`](reference/e_infra/infra/struct.md) | msgspec models validated however they are born — decoded at the edge or built in code. |
| [`e_infra.infra.settings`](reference/e_infra/infra/settings.md) | The dynamic composer — every `*Settings` of `infra.config`, merged into one `Settings` |

`infra.settings` discovers its scopes in `infra.config` on import — adding a scope is dropping a file there:

| Scope | Purpose |
|---|---|
| `agent` | the agnostic agent's edge — per-provider key and base, tier endpoints, retries, timeout. |
| `api` | the HTTP edge of this app — ALLOW_ORIGINS, ALLOW_METHODS. |
| `app` | process-level knobs — APP_ENV, APP_HOST, APP_PORT. |
| `base` | pydantic-settings — frozen, typed, layered config. |
| `cache` | the caches a service takes — how many entries each keeps in memory, for how long (CACHE_*). |
| `cli` | the command-line edge of this app — CLI_TOKEN, CLI_HISTORY. |
| `crypto` | the configuration of the crypto engine (`ops/crypto`), loaded from CRYPTO__*. |
| `darts` | the DARTS orchestrator — how much of a section runs at once, how semantic specs fuse (DARTS_*). |
| `db` | the embedded sqlite store — DB_PATH. |
| `doc` | the document processor — which engine reads which page, and how hard to push the deep one (DOC_*). |
| `docling` | the document-conversion edge — where docling-serve lives and how it converts (DOCLING_*). |
| `docs` | where the OpenAPI pages live, which aliases lead there, which renderers serve (DOCS_*). |
| `embed` | the embedding edge — a text-embeddings-inference server and the model it serves (EMBED_*). |
| `gliner` | the NER edge — a gliner service answering zero-shot entities (GLINER_*). |
| `http` | the outbound HTTP edge — HTTP_BASE_URL, HTTP_TIMEOUT. |
| `llm` | a chat model answering under a JSON schema — an OpenAI-compatible server (LLM_*). |
| `md` | the anytomd Markdown converter — its PDF and vision capabilities and the ZIP fan-out (MD_*). |
| `oauth` | the OAuth2 identity provider — name, client, secret and metadata URL. |
| `otel` | the telemetry edge — where spans go, how, how fast, how many (OTEL_*). |
| `ping` | how long one provider's health check may take — PING_TIMEOUT. |
| `postgres` | the Postgres edge — POSTGRES_DSN, pool and statement limits (POSTGRES_*). |
| `queue` | the durable job queue — a Postgres database of its own, apart from the service's data (QUEUE_*). |
| `redis` | the redis edge — REDIS_URL. |
| `rerank` | the reranking edge — a text-embeddings-inference server holding a cross-encoder (RERANK_*). |
| `theme` | the house theme — background, corporate hue and ink. |
| `ui` | the canvas's tunables — toast lifetime, run pace and grid spacing (UI_*). |

### ops — agnostic tools: categories only, the closed registry below

| Module | Purpose |
|---|---|
| [`e_infra.ops.compose`](reference/e_infra/ops/compose.md) | discover a stack tree and merge chosen fragments into one parameterized document. |
| [`e_infra.ops.crypto`](reference/e_infra/ops/crypto.md) | everything that needs a key or entropy — keyed ids, bearer tokens, password hashing, JWS/JWE, AEAD. |
| [`e_infra.ops.file`](reference/e_infra/ops/file.md) | agnostic discovery over an installed package — modules, classes, functions. |
| [`e_infra.ops.hash`](reference/e_infra/ops/hash.md) | hashing without a key — every id a project mints is a hash of what it names. |
| [`e_infra.ops.image`](reference/e_infra/ops/image.md) | deterministic square-font logos — banner by default, house colors, one rect per stroke. |
| [`e_infra.ops.registry`](reference/e_infra/ops/registry.md) | static code registry — parse a scope with `ast`, register every symbol by its path, import nothing. |
| [`e_infra.ops.snap`](reference/e_infra/ops/snap.md) | GallerySnap — the snapshot gallery for any set of Textual architectures. |
| [`e_infra.ops.tui`](reference/e_infra/ops/tui.md) | HeaderTui — the agnostic retro masthead for any Textual app. |
| [`e_infra.ops.wrappers`](reference/e_infra/ops/wrappers.md) | agnostic measuring wrappers — scope a block, read what it cost. |

### ports — the contracts: one `Protocol` per capability, never per technology

A port is the shape of the plug; it is never instantiated. Every provider port extends `Provider` (lifecycle,
`health`, an orienting `ProviderSpec`), and a port imports only the standard library and `infra`.

| Module | Purpose |
|---|---|
| [`e_infra.ports.cache`](reference/e_infra/ports/cache.md) | values of one type kept by key — a cache may forget, so a miss is never an error. |
| [`e_infra.ports.database`](reference/e_infra/ports/database.md) | a SQL database — statements with positional `$n` parameters, rows as dicts, a transaction scope. |
| [`e_infra.ports.documents`](reference/e_infra/ports/documents.md) | document conversion — a URL, raw bytes or a local file in, its structured forms out. |
| [`e_infra.ports.embed`](reference/e_infra/ports/embed.md) | text to vectors, one per text, in order — and the token count of the model that embeds them. |
| [`e_infra.ports.extract`](reference/e_infra/ports/extract.md) | a web page's main content as Markdown — what an article says, without what the site wraps it in. |
| [`e_infra.ports.http`](reference/e_infra/ports/http.md) | outbound HTTP — GET and POST of JSON, raw bytes, each bounded and optionally decoded to a shape. |
| [`e_infra.ports.llm`](reference/e_infra/ports/llm.md) | a chat model answering under a JSON schema — the decoded object, valid against it. |
| [`e_infra.ports.markdown`](reference/e_infra/ports/markdown.md) | a file of any format rendered to Markdown, and the format named from its bytes. |
| [`e_infra.ports.ner`](reference/e_infra/ports/ner.md) | zero-shot named entities — per text, the spans of the labels asked for, scored and never overlapping. |
| [`e_infra.ports.pages`](reference/e_infra/ports/pages.md) | a document's fast pass, page by page — blocks and the signals that tell where a deep reader pays off. |
| [`e_infra.ports.provider`](reference/e_infra/ports/provider.md) | the contract of everything the lifespan opens — lifecycle, health and an orienting spec. |
| [`e_infra.ports.queue`](reference/e_infra/ports/queue.md) | a durable job queue — kinds bound to handlers on named queues, jobs enqueued, read and cancelled. |
| [`e_infra.ports.rerank`](reference/e_infra/ports/rerank.md) | a cross-encoder — each text scored against the question, read together, in the texts' order. |
| [`e_infra.ports.store`](reference/e_infra/ports/store.md) | a byte-keyed store — point reads, writes, deletes and a lazy key scan, the whole CRUD a consumer sees. |
| [`e_infra.ports.telemetry`](reference/e_infra/ports/telemetry.md) | tracing — a span opened around a block, written until it ends, settled by how the block left. |

### providers/drivers — I/O with systems outside the process

A driver talks to something that lives elsewhere (network, socket, another process, a file with the semantics of a
service). Singleton in the lifespan: `__aenter__` opens the pool or client, `__aexit__` releases it, `health` never
raises, third-party exceptions are translated into `infra.errors` at the border. A driver composes another provider
only through its port, received by constructor (docling, TEI and the OpenAI-compatible driver ride an `HttpPort`).

| Module | Purpose |
|---|---|
| [`e_infra.providers.drivers.awa`](reference/e_infra/providers/drivers/awa.md) | the durable queue — awa, a Rust Postgres job queue, behind `QueuePort`. |
| [`e_infra.providers.drivers.docling`](reference/e_infra/providers/drivers/docling.md) | document conversion on docling-serve — any source in, the DoclingDocument and its renderings out. |
| [`e_infra.providers.drivers.gliner`](reference/e_infra/providers/drivers/gliner.md) | zero-shot entities from a gliner service — `POST /ner/batch`, NDJSON streamed both ways. |
| [`e_infra.providers.drivers.http`](reference/e_infra/providers/drivers/http.md) | the outbound client on wreq (Rust wreq bindings, browser-fidelity TLS). |
| [`e_infra.providers.drivers.openai`](reference/e_infra/providers/drivers/openai.md) | a chat model over an OpenAI-compatible server (vLLM, OpenAI) — answers under a JSON schema. |
| [`e_infra.providers.drivers.otel`](reference/e_infra/providers/drivers/otel.md) | TelemetryPort over the official OpenTelemetry SDK, exported by OTLP over HTTP or gRPC. |
| [`e_infra.providers.drivers.pgqueuer`](reference/e_infra/providers/drivers/pgqueuer.md) | the default durable queue, PgQueuer on asyncpg, behind `QueuePort` and `SchedulePort`. |
| [`e_infra.providers.drivers.postgres`](reference/e_infra/providers/drivers/postgres.md) | the SQL edge over psqlpy — a Rust (tokio-postgres) pool, pgvector bound natively. |
| [`e_infra.providers.drivers.redis`](reference/e_infra/providers/drivers/redis.md) | a store over redis.asyncio (the official client, async driver) — bytes in, bytes out. |
| [`e_infra.providers.drivers.sqlite`](reference/e_infra/providers/drivers/sqlite.md) | a store over aiosqlite (stdlib sqlite3 is sync-only on 3.14) — one kv table in one file. |
| [`e_infra.providers.drivers.tei`](reference/e_infra/providers/drivers/tei.md) | embeddings and reranking on text-embeddings-inference — `POST /embed`, `POST /rerank`. |

### providers/adapters — a foreign library inside the process, behind a contract

An adapter wraps a library with no connection (`Locality.EMBEDDED`): `__aenter__` loads the model or resource,
`__aexit__` frees it. The same lifecycle and the same border rules as a driver.

| Module | Purpose |
|---|---|
| [`e_infra.providers.adapters.anytomd`](reference/e_infra/providers/adapters/anytomd.md) | anytomd bound to Python — one engine for every format, PDF and image descriptions folded in. |
| [`e_infra.providers.adapters.liteparse`](reference/e_infra/providers/adapters/liteparse.md) | a document's fast pass on liteparse (Rust, in-process) — the `PagesPort`. |
| [`e_infra.providers.adapters.rtrafilatura`](reference/e_infra/providers/adapters/rtrafilatura.md) | a web page's main content as Markdown — the article without its menus and footers. |
| [`e_infra.providers.adapters.theine`](reference/e_infra/providers/adapters/theine.md) | a cache in this process's memory — theine (Rust core, W-TinyLFU admission, per-key TTL). |

### engines — execution against resources

An engine orchestrates providers received **by port**; it keeps references and configuration, never request state.
It never meets a concrete provider, a processor or another engine.

| Module | Purpose |
|---|---|
| [`e_infra.engines.cache`](reference/e_infra/engines/cache.md) | a fast cache in front of a durable one — the cache every module takes. |
| [`e_infra.engines.dispatch`](reference/e_infra/engines/dispatch.md) | background work by kind — on the durable queue when it answers, in memory when it does not. |
| [`e_infra.engines.health`](reference/e_infra/engines/health.md) | every provider asked how it is, at once — the startup survey and the readiness route's verdicts. |

### processors — transform input into output

A processor turns data into data through ports and `ops`; it is cheap, holds nothing between calls, and never meets a
concrete provider or an engine. Whatever library reads a page or detects a format sits behind a port.

| Module | Purpose |
|---|---|
| [`e_infra.processors.doc`](reference/e_infra/processors/doc.md) | the DocProcessor — every page read by the engine that reads it best, as fast as the pair allows. |
| [`e_infra.processors.md`](reference/e_infra/processors/md.md) | the MDProcessor — any file to Markdown, detected and rendered by the engine behind `MarkdownPort`. |
| [`e_infra.processors.models`](reference/e_infra/processors/models.md) | what the processors hand out — a document read, or the Markdown a file becomes, both typed. |

## Layers and dependencies

Three vertical levels, two horizontal: resources (`providers`) -> execution (`engines`, `processors`) -> business
(`services`, outside `e_infra`); `infra` and `ops` cross all of them. The module tree, the process state and the
construction order are one hierarchy: the lifespan — the composition root, the only module that imports concrete
classes — opens the providers with an `AsyncExitStack`, decides which class fills each port, and builds the engines
and processors over the ports.

| Module in... | May import | Never imports |
|---|---|---|
| `infra` | stdlib, `ops` | ports, providers, engines, processors |
| `ops` | stdlib | ports, providers, engines, processors |
| `ports` | stdlib, `infra` | providers, engines, processors |
| `providers/drivers`, `providers/adapters` | `ports`, `infra`, `ops`, its library | engines, processors, other providers |
| `engines` | `ports`, `infra`, `ops` | providers, processors, other engines |
| `processors` | `ports`, `infra`, `ops` | providers, engines |

`tach.toml` enforces the table (`uv run tach check`) and `tests/unit/test_taxonomy.py` reads it again from the imports;
the same test checks that every driver and adapter declares its `ProviderSpec` and the lifecycle, and that the folder
agrees with `Locality` (`EMBEDDED` is an adapter, the rest are drivers).

## Opt-in modules

Not every service takes everything: each service's `scripts/materialize.py` declares its exclusions, and
the e-taxis wizard offers the optional parts at export. A module not listed here rides into every service;
e-taxis itself materializes the whole tree (the stack machinery — `ops/compose` — exists for it).

| Module | Taken by |
|---|---|
| `ops/tui.py` | tui |
| `ops/snap.py` | mcp, tui |
| `ops/compose.py` | mcp |
| `ports/provider.py`, `engines/health.py` | api, cli, graph, tui |
| `ports/database.py`, `providers/drivers/postgres.py` | api, graph |
| `ports/http.py`, `providers/drivers/http.py` | api, cli, graph, tui |
| `ports/store.py`, `providers/drivers/redis.py`, `providers/drivers/sqlite.py` | api, cli, graph, tui |
| `ports/queue.py`, `providers/drivers/awa.py`, `providers/drivers/pgqueuer.py`, `engines/dispatch.py` | none by default — the background's durable queues are opt-in: a service that runs one drops the exclusion, and the composition root names which class fills `QueuePort` |
| `ports/telemetry.py`, `providers/drivers/otel.py` | none by default — tracing is opt-in |
| `ports/documents.py`, `providers/drivers/docling.py` | api, cli, graph, tui (with `processors/doc`) |
| `ports/pages.py`, `providers/adapters/liteparse.py` | api, cli, graph, tui (with `processors/doc`) |
| `ports/markdown.py`, `providers/adapters/anytomd.py` | api, cli, graph, tui (with `processors/md`) |
| `ports/cache.py`, `providers/adapters/theine.py`, `engines/cache.py` | none by default — the cache is opt-in; its durable layer is `CachePostgresDriver` in `providers/drivers/postgres.py` |
| `ports/embed.py`, `ports/rerank.py`, `providers/drivers/tei.py` | none by default — model edges are opt-in |
| `ports/llm.py`, `providers/drivers/openai.py` | none by default — model edges are opt-in |
| `ports/ner.py`, `providers/drivers/gliner.py` | none by default — model edges are opt-in |
| `ports/extract.py`, `providers/adapters/rtrafilatura.py` | none by default — web extraction is opt-in |
| `processors/*` | api, cli, graph, tui |

## ops — the closed registry of categories

A module in `ops/` names a **category** — what kind of tool it is, never one particular use of it; `file`
is the reference: everything that tells and reads what a file is. Functions are
`<category>_<scope>[_<detail>]`; classes carry the category as surname. Something new joins an existing
category; a new category is a decision, recorded, and only while the count stays at **20 or fewer**.
`tests/unit/test_ops_contract.py` enforces the three rules against this table.

**`hash` and `crypto` never overlap:** `hash` takes no key and no secret (it names things); `crypto` needs
a key or entropy (it protects things).

| Category | Holds | Never |
|---|---|---|
| `algorithm` | algorithms no domain owns: MinHash/LSH, statistics, numeric normalization | anything with a key or a secret — that is `crypto` |
| `compose` | stack documents discovered and merged under the compose-go rules | deployment; running services |
| `crypto` | everything that needs a key or entropy: keyed ids, bearer tokens, password hashing, JWS/JWE, signatures, AES-256-GCM | hashing without a key — that is `hash` |
| `file` | what a file is: detection, import-based discovery over an installed package | static code reading — that is `registry`; structured content — that is `parser` |
| `hash` | hashing without a key or a secret: content addresses, every id a project mints | anything that needs a key or entropy — that is `crypto` |
| `image` | images drawn by rule: the house wordmarks and logos, deterministic SVG | raster or photo editing; terminal widgets — that is `tui` |
| `lexical` | text read and rewritten by rule: name keys, secret redaction, language identification | typed value extraction — that is `pattern` |
| `parser` | structured formats read into values: Markdown events, records across versions, the bearer header | rewriting text — that is `lexical` |
| `pattern` | typed tokens in text, validated and normalized: dates, amounts, identifiers, URLs | the meaning of words — that is `lexical` |
| `registry` | static code registry: symbols by path through `ast`, importing nothing | import-based runtime discovery — that is `file` |
| `snap` | snapshot galleries: the visual drift gate over sets of widgets | unit assertions |
| `tui` | agnostic terminal widgets: the masthead and its kin | application screens; domain widgets |
| `wrappers` | measuring wrappers: scope a block, read what it cost (latency) | retry or timeout policy; domain logic |

Thirteen categories are claimed of the twenty allowed; a new one is a recorded decision while the limit holds.

## Usage

```bash
make install      # sync deps + git hooks
make check        # lint + type + arch + validate + test
make cov          # coverage gate (>=90%)
make docs         # serve docs at :8000
```

Editing rule: `src/e_infra/` and the shared root files change here; systems re-materialize.
`make common-check` in any system fails when its copies drift.
