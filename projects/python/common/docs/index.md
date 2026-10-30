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
| [`e_infra.infra.errors`](reference/e_infra/infra/errors.md) | the one root of every error — each layer imports its exceptions from here, none defines its own. |
| [`e_infra.infra.events`](reference/e_infra/infra/events.md) | events delivered in this process — subscribers by event type, none known to the publisher. |
| [`e_infra.infra.logger`](reference/e_infra/infra/logger.md) | structured JSON in prod, ordered plain text in dev/local. |
| [`e_infra.infra.proxy`](reference/e_infra/infra/proxy.md) | import-safe lazy singletons — the object exists at module level, its load runs on first use. |
| [`e_infra.infra.settings`](reference/e_infra/infra/settings.md) | the dynamic composer — every ``*Settings`` of ``infra/config``, merged into one nested ``Settings``. |
| [`e_infra.infra.state`](reference/e_infra/infra/state.md) | the app resource graph — dynamic attribute access all the way down. |
| [`e_infra.infra.struct`](reference/e_infra/infra/struct.md) | msgspec models validated however they are born — decoded at the edge or built in code. |

#### infra.errors — the one root of every error

Every layer imports its exceptions from `infra/errors`; none defines its own (`tests/unit/e_infra/infra/test_errors.py` walks
the package and fails on any exception class defined elsewhere). Providers translate their library's exceptions into this
tree at the border, so no layer above imports a library's own.

```
CoreError
├─ ProviderError
│  ├─ DriverError            a system outside the process failed
│  │  ├─ DatabaseError · StoreError · QueueError · TelemetryError
│  │  ├─ HttpError ─ HttpTimeoutError (also TimeoutError)
│  │  └─ ModelError ─ TruncatedError
│  ├─ AdapterError           a library inside the process failed
│  │  └─ ParseError
│  └─ CacheError · DocumentError      both DriverError and AdapterError
├─ EngineError ─ DispatchError ─ ScheduleError (ValueError) · UnknownWorkError (LookupError)
├─ ProcessorError ─ MDError (RuntimeError) ─ UnsupportedFormatError · InputTooLargeError · ZipBombError
└─ OpsError ─ ComposeError · RegistryError · FileError · LogoError · CryptoError ─ TokenError
```

A capability met on both natures raises an error that is honestly both. The cache is theine in memory and Postgres over
the wire; documents are docling-serve over HTTP and docling in process: `CacheError` and `DocumentError` inherit
`DriverError` and `AdapterError` at once, so `except DriverError` and `except AdapterError` each catch the failure of the
nature they guard. `tach` holds `infra.errors` as the floor module of the package (it imports nothing; `ops` raises
from it).

#### infra.config — the settings tree mirrors the module tree

`infra.settings` discovers every `*Settings` of `infra.config` recursively on import and builds nested, lazy, frozen
sections: the module path, the attribute chain and the module configured are one hierarchy (the OST parity,
`test_taxonomy` is its gate). `st.providers.drivers.database.psqlpy.dsn` is read from
`infra/config/providers/drivers/database/psqlpy.py` and configures `providers/drivers/database/psqlpy.py`;
`st.app.env` is a scope that serves no provider, engine or processor, so it sits at the top. Adding a scope is dropping a
file in the tree; each scope keeps its own sources (`env_prefix`, `env_file`, `toml_file`, `secrets_dir`), and
`Settings.load(providers={"drivers": {"database": {"psqlpy": {"pool": 3}}}})` overrides one scope by its path.
Env variable names are the scope's `env_prefix` plus the field, so a scope that already existed keeps its names
(`POSTGRES_*`, `REDIS_*`, `QUEUE_*`); a new scope takes a prefix named after its provider (`ASYNCPG_*`). Fields always
run connection, credentials, limits, behaviour, and a provider's constructor takes `settings: <X>Settings | None = None`,
read lazily from the composer when absent.

| Config module | Chain | Purpose |
|---|---|---|
| `infra/config/agent.py` | `st.agent` | the agnostic agent's edge — per-provider key and base, tier endpoints, retries, timeout. |
| `infra/config/api.py` | `st.api` | the HTTP edge of this app — ALLOW_ORIGINS, ALLOW_METHODS. |
| `infra/config/app.py` | `st.app` | process-level knobs — APP_ENV, APP_HOST, APP_PORT. |
| `infra/config/cli.py` | `st.cli` | the command-line edge of this app — CLI_TOKEN, CLI_HISTORY. |
| `infra/config/crypto.py` | `st.crypto` | the configuration of the crypto engine (`ops/crypto`), loaded from CRYPTO__*. |
| `infra/config/darts.py` | `st.darts` | the DARTS orchestrator — how much of a section runs at once, how semantic specs fuse (DARTS_*). |
| `infra/config/docs.py` | `st.docs` | where the OpenAPI pages live, which aliases lead there, which renderers serve (DOCS_*). |
| `infra/config/engines/dispatch.py` | `st.engines.dispatch` | the dispatch engine — which durable queue backs the background, and its write pace. |
| `infra/config/oauth.py` | `st.oauth` | the OAuth2 identity provider — name, client, secret and metadata URL. |
| `infra/config/ping.py` | `st.ping` | how long one provider's health check may take — PING_TIMEOUT. |
| `infra/config/processors/doc.py` | `st.processors.doc` | the document processor — which engine reads which page, and how hard to push (DOC_*). |
| `infra/config/processors/md.py` | `st.processors.md` | the Markdown processor — input ceiling, ZIP fan-out and its zip-bomb guard (MD_*). |
| `infra/config/providers/adapters/cache/theine.py` | `st.providers.adapters.cache.theine` | the in-memory cache — how many entries it keeps, for how long (CACHE_*). |
| `infra/config/providers/adapters/markdown/anytomd.py` | `st.providers.adapters.markdown.anytomd` | the anytomd converter — its PDF reader and the vision model (MD_*). |
| `infra/config/providers/adapters/pages/liteparse.py` | `st.providers.adapters.pages.liteparse` | liteparse's own Tesseract and page workers (DOC_*). |
| `infra/config/providers/drivers/cache/postgres.py` | `st.providers.drivers.cache.postgres` | the durable cache in Postgres — how long a value lives. |
| `infra/config/providers/drivers/database/asyncpg.py` | `st.providers.drivers.database.asyncpg` | the asyncpg pool — ASYNCPG_DSN, pool bounds and command limit. |
| `infra/config/providers/drivers/database/psqlpy.py` | `st.providers.drivers.database.psqlpy` | the psqlpy pool — POSTGRES_DSN, pool size and statement limit. |
| `infra/config/providers/drivers/documents/docling.py` | `st.providers.drivers.documents.docling` | the docling-serve edge — where it lives and how it converts. |
| `infra/config/providers/drivers/embed/tei.py` | `st.providers.drivers.embed.tei` | the embedding edge — a text-embeddings-inference server and its model. |
| `infra/config/providers/drivers/http/wreq.py` | `st.providers.drivers.http.wreq` | the outbound HTTP client — HTTP_BASE_URL and HTTP_TIMEOUT. |
| `infra/config/providers/drivers/llm/openai.py` | `st.providers.drivers.llm.openai` | a chat model answering under a JSON schema — an OpenAI-compatible server. |
| `infra/config/providers/drivers/ner/gliner.py` | `st.providers.drivers.ner.gliner` | the NER edge — a gliner service answering zero-shot entities. |
| `infra/config/providers/drivers/queue/awa.py` | `st.providers.drivers.queue.awa` | the awa queue — a Postgres database of its own, pool, poll and drain. |
| `infra/config/providers/drivers/queue/pgqueuer.py` | `st.providers.drivers.queue.pgqueuer` | PgQueuer's pace — poll, drain, call bound, heartbeat and restart. |
| `infra/config/providers/drivers/rerank/tei.py` | `st.providers.drivers.rerank.tei` | the reranking edge — a text-embeddings-inference server and a cross-encoder. |
| `infra/config/providers/drivers/store/redis.py` | `st.providers.drivers.store.redis` | the redis client — REDIS_URL, connection bound and socket timeout. |
| `infra/config/providers/drivers/store/sqlite.py` | `st.providers.drivers.store.sqlite` | the embedded sqlite store — DB_PATH and the busy timeout. |
| `infra/config/providers/drivers/telemetry/otel.py` | `st.providers.drivers.telemetry.otel` | the telemetry edge — where spans go, how, how fast, how many. |
| `infra/config/theme.py` | `st.theme` | the house theme — background, corporate hue and ink. |
| `infra/config/ui.py` | `st.ui` | the canvas's tunables — toast lifetime, run pace and grid spacing (UI_*). |

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

### providers — a capability, a nature, an implementation

A provider lives at `providers/<drivers|adapters>/<capability>/<name>.py`. **`<capability>` is exactly the module name of the
port it meets** (`ports/embed.py` ↔ `providers/drivers/embed/tei.py`, one to one), and `tests/unit/test_taxonomy.py` checks
it: the path is a port module and the provider has the port's members. **The file names what tells implementations apart**:
the library when several reach one service (`database/psqlpy.py`, `database/asyncpg.py`), otherwise the service or brand
(`embed/tei.py`, `llm/openai.py`). **Class names are unique in the package, `<Name><Nature>`**; a brand that repeats across
capabilities takes the capability as a qualifier before it (`TeiEmbedDriver`, `TeiRerankDriver`, `CachePostgresDriver`).
Every implementation worth keeping stays: the blueprint holds the alternatives and a project picks one at its composition
root. SQLite is a driver (`Locality.FILESYSTEM`) and, as it meets `StorePort` (one kv table), it lives at
`store/sqlite.py`; a SQL-flavoured sqlite driver would be `database/sqlite.py` meeting `DatabasePort`.

The capabilities share their vocabulary with the self-hosted stack's categories (`stack/<category>/<service>/`): the stack
groups what is deployed, the providers group contracts, and a new capability enters both at once.

| Capability (port module) | Stack category |
|---|---|
| `database` | `rdb` |
| `store`, `cache` | `cdb` |
| `http` | — transport, composed by other drivers |
| `queue` | `queue` |
| `telemetry` | `watch` |
| `documents`, `markdown`, `pages`, `extract` | `rag` |
| `embed`, `rerank`, `llm`, `ner` | `llm` |

#### Two Postgres drivers, both first-class

`database/psqlpy.py` (`PsqlpyDriver`: a Rust tokio-postgres pool, pgvector bound natively) and `database/asyncpg.py`
(`AsyncpgDriver`: asyncpg's pool, a `Vector` bound as pgvector's text form) meet the same `DatabasePort` with the same
semantics — `$n` parameters, rows as dicts, `transaction()` pinning one connection, errors as `DatabaseError`; the pool is
the driver's and a connection is taken per operation, never kept. The project picks one at its root. `AsyncpgDriver` also
gives a library that owns its client what it needs, on the driver class and in no port: `pool`, `connection()` (a dedicated
connection, closed on exit) and `guard()` (asyncpg's errors as `DatabaseError`). `PgqueuerDriver` **receives** an
`AsyncpgDriver` by constructor and rides it — its schema on the pool, one dedicated connection for each queue manager and
for the scheduler — and opens no pool of its own; the lifespan opens the database first and closes it last. The queue
wants a database of its own (`app_background` beside the service's `app`): hand it an `AsyncpgDriver` built on
`AsyncpgSettings(dsn=...)` for that database.

#### providers/drivers — I/O with systems outside the process

A driver talks to something that lives elsewhere (network, socket, another process, a file with the semantics of a
service). Singleton in the lifespan: `__aenter__` opens the pool or client, `__aexit__` releases it, `health` never
raises, third-party exceptions are translated into `infra.errors` at the border (`DriverError` and below). A driver composes
another provider only through its port, received by constructor (docling, TEI and the OpenAI-compatible driver ride an
`HttpPort`; the durable cache rides a `DatabasePort`) — with one stated exception: PgQueuer's library owns its
asyncpg client, so its driver is handed the `AsyncpgDriver`, typed by a small protocol it declares itself.

| Module | Purpose |
|---|---|
| [`e_infra.providers.drivers.cache.postgres`](reference/e_infra/providers/drivers/cache/postgres.md) | a durable cache in a Postgres database — it rides a `DatabasePort`, whichever driver. |
| [`e_infra.providers.drivers.database.asyncpg`](reference/e_infra/providers/drivers/database/asyncpg.md) | the SQL edge over asyncpg — a pooled client, and the pool PgQueuer rides. |
| [`e_infra.providers.drivers.database.psqlpy`](reference/e_infra/providers/drivers/database/psqlpy.md) | the SQL edge over psqlpy — a Rust (tokio-postgres) pool, pgvector bound natively. |
| [`e_infra.providers.drivers.documents.docling`](reference/e_infra/providers/drivers/documents/docling.md) | document conversion on docling-serve — any source in, the DoclingDocument out. |
| [`e_infra.providers.drivers.embed.tei`](reference/e_infra/providers/drivers/embed/tei.md) | embeddings on text-embeddings-inference — `POST /embed`, behind `EmbedPort`. |
| [`e_infra.providers.drivers.http.wreq`](reference/e_infra/providers/drivers/http/wreq.md) | the outbound client on wreq (Rust wreq bindings, browser-fidelity TLS). |
| [`e_infra.providers.drivers.llm.openai`](reference/e_infra/providers/drivers/llm/openai.md) | a chat model over an OpenAI-compatible server (vLLM, OpenAI) — JSON-schema answers. |
| [`e_infra.providers.drivers.ner.gliner`](reference/e_infra/providers/drivers/ner/gliner.md) | zero-shot entities from a gliner service — `POST /ner/batch`, NDJSON streamed both ways. |
| [`e_infra.providers.drivers.queue.awa`](reference/e_infra/providers/drivers/queue/awa.md) | the durable queue — awa, a Rust Postgres job queue, behind `QueuePort`. |
| [`e_infra.providers.drivers.queue.pgqueuer`](reference/e_infra/providers/drivers/queue/pgqueuer.md) | the default durable queue, PgQueuer on asyncpg, behind `QueuePort` and `SchedulePort`. |
| [`e_infra.providers.drivers.rerank.tei`](reference/e_infra/providers/drivers/rerank/tei.md) | reranking on text-embeddings-inference — `POST /rerank`, behind `RerankPort`. |
| [`e_infra.providers.drivers.store.redis`](reference/e_infra/providers/drivers/store/redis.md) | a store over redis.asyncio (the official client, async driver) — bytes in, bytes out. |
| [`e_infra.providers.drivers.store.sqlite`](reference/e_infra/providers/drivers/store/sqlite.md) | a store over aiosqlite (stdlib sqlite3 is sync-only on 3.14) — one kv table in one file. |
| [`e_infra.providers.drivers.telemetry.otel`](reference/e_infra/providers/drivers/telemetry/otel.md) | TelemetryPort over the official OpenTelemetry SDK, exported by OTLP over HTTP or gRPC. |

#### providers/adapters — a foreign library inside the process, behind a contract

An adapter wraps a library with no connection (`Locality.EMBEDDED`): `__aenter__` loads the model or resource,
`__aexit__` frees it. The same lifecycle and the same border rules as a driver (`AdapterError` and below).

| Module | Purpose |
|---|---|
| [`e_infra.providers.adapters.cache.theine`](reference/e_infra/providers/adapters/cache/theine.md) | a cache in this process's memory — theine (Rust core, W-TinyLFU, per-key TTL). |
| [`e_infra.providers.adapters.extract.rtrafilatura`](reference/e_infra/providers/adapters/extract/rtrafilatura.md) | a web page's main content as Markdown — the article without its chrome. |
| [`e_infra.providers.adapters.markdown.anytomd`](reference/e_infra/providers/adapters/markdown/anytomd.md) | anytomd bound to Python — one engine for every format, PDF and images folded in. |
| [`e_infra.providers.adapters.pages.liteparse`](reference/e_infra/providers/adapters/pages/liteparse.md) | a document's fast pass on liteparse (Rust, in-process) — the `PagesPort`. |

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

### Logging

Every provider, engine and processor logs through `infra.logger`, as structured key/value events (never an f-string):
`debug` for lifecycle and per-operation detail, `info` on open and close, `warning` for a degraded or fallback path
(a health check that answers false, a durable layer left for memory, a manager restarted), `error` for the failure a
border translates and re-raises. The unit tests assert the events where behaviour depends on them.

### Testing without a service

The default run (`make test`, `make cov`) needs no Postgres, no redis and no network service. Redis is
[fakeredis](https://github.com/cunla/fakeredis-py) (`FakeServer`, switched off to take it down); every HTTP-based driver
(wreq, docling, TEI, OpenAI-compatible, gliner) runs against a real localhost server
([pytest-httpserver](https://pytest-httpserver.readthedocs.io), streaming over a werkzeug `Response` on a generator);
telemetry reads spans from the SDK's in-memory exporter; sqlite is a temp file. psqlpy, asyncpg and awa have no fake, so
the repo writes its own under `tests/support/`: a pool, connection and transaction that hold scripted rows, record the SQL
and raise the library's own exception types, which the driver is patched to build. PgQueuer runs its real managers,
retries and cron on its own in-memory backend (`InMemoryQueries`), with the driver's `background.job` book on the fake
asyncpg pool. The real-service tests stay, marked `integration` (a Postgres at `POSTGRES_TEST_DSN`, skipped when none
answers): `make integration`.

## Layers and dependencies

Three vertical levels, two horizontal: resources (`providers`) -> execution (`engines`, `processors`) -> business
(`services`, outside `e_infra`); `infra` and `ops` cross all of them. The module tree, the process state and the
construction order are one hierarchy: the lifespan — the composition root, the only module that imports concrete
classes — opens the providers with an `AsyncExitStack`, decides which class fills each port, and builds the engines
and processors over the ports.

| Module in... | May import | Never imports |
|---|---|---|
| `infra` | stdlib, `ops` | ports, providers, engines, processors |
| `infra.errors` | stdlib | everything else — it is the floor |
| `ops` | stdlib, `infra.errors` | the rest of `infra`, ports, providers, engines, processors |
| `ports` | stdlib, `infra` | providers, engines, processors |
| `providers/drivers`, `providers/adapters` | `ports`, `infra`, `ops`, its library | engines, processors, other providers |
| `engines` | `ports`, `infra`, `ops` | providers, processors, other engines |
| `processors` | `ports`, `infra`, `ops` | providers, engines |

`tach.toml` spells the table edge by edge (`uv run tach check`): `engines`, `processors`, `providers.drivers` and
`providers.adapters` each declare `ports`, `infra` and `ops` and no one of the others, `ports` declares `infra`, `infra`
declares `ops`, `ops` declares the error tree; an import that is not an edge is reported with its file and line.
`tests/unit/test_taxonomy.py` reads the table again from the imports and holds what one tach module cannot: a driver never
imports another provider. The same test checks that every driver and adapter declares its `ProviderSpec` and the
lifecycle, that the folder agrees with `Locality` (`EMBEDDED` is an adapter, the rest are drivers), that a provider sits at
`providers/<nature>/<capability>/<name>.py` meeting that capability's port, and that the config tree mirrors the module tree.

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
| `ports/database.py`, `providers/drivers/database/psqlpy.py` | api, graph — `database/asyncpg.py` is the alternative a project may take instead (or beside, for PgQueuer) |
| `ports/http.py`, `providers/drivers/http/wreq.py` | api, cli, graph, tui |
| `ports/store.py`, `providers/drivers/store/redis.py`, `providers/drivers/store/sqlite.py` | api, cli, graph, tui |
| `ports/queue.py`, `providers/drivers/queue/awa.py`, `providers/drivers/queue/pgqueuer.py` (with `database/asyncpg.py`), `engines/dispatch.py` | none by default — the background's durable queues are opt-in: a service that runs one drops the exclusion, and the composition root names which class fills `QueuePort` |
| `ports/telemetry.py`, `providers/drivers/telemetry/otel.py` | none by default — tracing is opt-in |
| `ports/documents.py`, `providers/drivers/documents/docling.py` | api, cli, graph, tui (with `processors/doc`) |
| `ports/pages.py`, `providers/adapters/pages/liteparse.py` | api, cli, graph, tui (with `processors/doc`) |
| `ports/markdown.py`, `providers/adapters/markdown/anytomd.py` | api, cli, graph, tui (with `processors/md`) |
| `ports/cache.py`, `providers/adapters/cache/theine.py`, `engines/cache.py` | none by default — the cache is opt-in; its durable layer is `CachePostgresDriver` in `providers/drivers/cache/postgres.py`, over any `DatabasePort` |
| `ports/embed.py`, `ports/rerank.py`, `providers/drivers/embed/tei.py`, `providers/drivers/rerank/tei.py` | none by default — model edges are opt-in |
| `ports/llm.py`, `providers/drivers/llm/openai.py` | none by default — model edges are opt-in |
| `ports/ner.py`, `providers/drivers/ner/gliner.py` | none by default — model edges are opt-in |
| `ports/extract.py`, `providers/adapters/extract/rtrafilatura.py` | none by default — web extraction is opt-in |
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
