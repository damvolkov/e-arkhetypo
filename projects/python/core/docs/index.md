# e-core

Common core of the e-stack template systems: **uv · ruff · ty · tach · prek · pytest · zensical**.

## What this is

Every module a system materializes lives once here — this is the infra blueprint the e-taxis wizard reads
when it exports a new project, offering the user the parts that are optional. Services do **not** depend on
this package at runtime: `make core` in any system copies the sections of `src/e_core/` into its own `src/`
(byte-identical except import paths), so each system ships self-contained and this stays the single source
of truth. `make core-check` fails the moment a copy drifts.

## Modules

All sources live under `src/e_core/`, layered by [tach](https://tach.dev) — high to low:
`processors -> adapters -> core -> ops`. The purpose of each module is its first docstring line, verbatim;
reference pages are generated from the sources: drop a new module under `src/` and it appears on the next
build.

### core — the project's internal infrastructure

| Module | Purpose |
|---|---|
| [`e_core.core.background`](reference/e_core/core/background.md) | work that outlives the call that asked for it — one interface over a durable engine or memory. |
| [`e_core.core.errors`](reference/e_core/core/errors.md) | typed exception hierarchy — all domain exceptions inherit from CoreError. |
| [`e_core.core.logger`](reference/e_core/core/logger.md) | structured JSON in prod, ordered plain text in dev/local. |
| [`e_core.core.proxy`](reference/e_core/core/proxy.md) | import-safe lazy singletons — the object exists at module level, its load runs on first use. |
| [`e_core.core.state`](reference/e_core/core/state.md) | the app resource graph — dynamic attribute access all the way down. |
| [`e_core.core.struct`](reference/e_core/core/struct.md) | msgspec models validated however they are born — decoded at the edge or built in code. |
| [`e_core.core.settings`](reference/e_core/core/settings/index.md) | The dynamic composer — every `*Settings` of the package, merged into one `Settings` |

`core.settings` discovers its scopes on import — adding a scope is dropping a file here:

| Scope | Purpose |
|---|---|
| `agent` | the agnostic agent's edge — per-provider key and base, tier endpoints, retries, timeout. |
| `api` | the HTTP edge of this app — ALLOW_ORIGINS, ALLOW_METHODS. |
| `app` | process-level knobs — APP_ENV, APP_HOST, APP_PORT. |
| `base` | pydantic-settings — frozen, typed, layered config. |
| `cli` | the command-line edge of this app — CLI_TOKEN, CLI_HISTORY. |
| `crypto` | the configuration of the crypto engine (`ops/crypto`), loaded from CRYPTO__*. |
| `darts` | the DARTS orchestrator — how much of a section runs at once, and how semantic specs fuse (DARTS_*). |
| `db` | the embedded sqlite store — DB_PATH. |
| `doc` | the document processor — which engine reads which page, and how hard to push the deep one (DOC_*). |
| `docling` | the document-conversion edge — where docling-serve lives and how it converts (DOCLING_*). |
| `docs` | where the OpenAPI pages live, which aliases lead there, which renderers serve (DOCS_*). |
| `http` | the outbound HTTP edge — HTTP_BASE_URL, HTTP_TIMEOUT. |
| `md` | the anytomd Markdown converter — its PDF and vision capabilities and the ZIP fan-out (MD_*). |
| `oauth` | the OAuth2 identity provider — name, client, secret and metadata URL. |
| `otel` | the telemetry edge — where spans go, how, how fast, how many (OTEL_*). |
| `ping` | how long one adapter's ping may take — PING_TIMEOUT. |
| `postgres` | the Postgres edge — POSTGRES_DSN, pool and statement limits (POSTGRES_*). |
| `queue` | the durable job queue — a Postgres database of its own, apart from the service's data (QUEUE_*). |
| `redis` | the redis edge — REDIS_URL. |
| `theme` | the house theme — background, corporate hue and ink. |
| `ui` | the canvas's tunables — toast lifetime, run pace and grid spacing (UI_*). |

### ops — agnostic tools: categories only, the closed registry below

| Module | Purpose |
|---|---|
| [`e_core.ops.compose`](reference/e_core/ops/compose.md) | discover a stack tree and merge chosen fragments into one parameterized document. |
| [`e_core.ops.crypto`](reference/e_core/ops/crypto.md) | everything that needs a key or entropy — keyed ids, bearer tokens, password hashing, JWS/JWE, AEAD. |
| [`e_core.ops.file`](reference/e_core/ops/file.md) | agnostic discovery over an installed package — modules, classes, functions. |
| [`e_core.ops.image`](reference/e_core/ops/image.md) | deterministic square-font logos — banner by default, house colors, one rect per stroke. |
| [`e_core.ops.registry`](reference/e_core/ops/registry.md) | static code registry — parse a scope with `ast`, register every symbol by its path, import nothing. |
| [`e_core.ops.snap`](reference/e_core/ops/snap.md) | GallerySnap — the snapshot gallery for any set of Textual architectures. |
| [`e_core.ops.tui`](reference/e_core/ops/tui.md) | HeaderTui — the agnostic retro masthead for any Textual app. |
| [`e_core.ops.wrappers`](reference/e_core/ops/wrappers.md) | agnostic measuring wrappers — scope a block, read what it cost. |

### adapters — the edge of the world: ports and their implementations

| Module | Purpose |
|---|---|
| [`e_core.adapters.anytomd`](reference/e_core/adapters/anytomd.md) | anytomd bound to Python — one engine for every format, PDF and image descriptions folded in. |
| [`e_core.adapters.awa`](reference/e_core/adapters/awa.md) | the durable background engine — awa, a Rust Postgres job queue, behind `BackgroundPort`. |
| [`e_core.adapters.base`](reference/e_core/adapters/base.md) | the implementation base for external services — connect, close, ping, async-context bridge. |
| [`e_core.adapters.docling`](reference/e_core/adapters/docling.md) | document conversion on docling-serve — any source in, the DoclingDocument and its renderings out. |
| [`e_core.adapters.http`](reference/e_core/adapters/http.md) | the external-service client on wreq (Rust wreq bindings, browser-fidelity TLS). |
| [`e_core.adapters.otel`](reference/e_core/adapters/otel.md) | TelemetryPort over the official OpenTelemetry SDK, exported by OTLP over HTTP or gRPC. |
| [`e_core.adapters.pgqueuer`](reference/e_core/adapters/pgqueuer.md) | the default durable background engine, PgQueuer on asyncpg, behind `BackgroundPort`. |
| [`e_core.adapters.ports`](reference/e_core/adapters/ports.md) | what consumers (routers, deps, lifespan) may ask of an external service. |
| [`e_core.adapters.postgres`](reference/e_core/adapters/postgres.md) | the SQL edge over psqlpy — a Rust (tokio-postgres) pool, pgvector bound natively. |
| [`e_core.adapters.queue`](reference/e_core/adapters/queue.md) | the durable engines behind `BackgroundPort`, by QUEUE_ENGINE. |
| [`e_core.adapters.redis`](reference/e_core/adapters/redis.md) | StoreAdapter over redis.asyncio (the official client, async driver). |
| [`e_core.adapters.sqlite`](reference/e_core/adapters/sqlite.md) | StoreAdapter over aiosqlite (stdlib sqlite3 is sync-only on 3.14) — one kv table. |

### processors — the document pipeline

| Module | Purpose |
|---|---|
| [`e_core.processors.doc`](reference/e_core/processors/doc.md) | the DocProcessor — every page read by the engine that reads it best, as fast as the pair allows. |
| [`e_core.processors.md`](reference/e_core/processors/md.md) | the MDProcessor — any file to Markdown, detected and rendered by the anytomd engine. |
| [`e_core.processors.models`](reference/e_core/processors/models.md) | what the processors hand out — a document read, or the Markdown a file becomes, both typed. |

## Opt-in modules

Not every service takes everything: each service's `scripts/materialize.py` declares its exclusions, and
the e-taxis wizard offers the optional parts at export. A module not listed here rides into every service;
e-taxis itself materializes the whole tree (the stack machinery — `ops/compose` — exists for it).

| Module | Taken by |
|---|---|
| `ops/tui.py` | tui |
| `ops/snap.py` | mcp, tui |
| `ops/compose.py` | mcp |
| `adapters/postgres.py` | api, graph |
| `adapters/http.py` | api, cli, graph, tui |
| `adapters/redis.py` | api, cli, graph, tui |
| `adapters/sqlite.py` | api, cli, graph, tui |
| `adapters/awa.py`, `adapters/pgqueuer.py`, `adapters/queue.py` | none by default — the background's durable engines are opt-in: a service that runs one drops the exclusion |
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
make install      # materialize shared files + uv sync
make check        # lint + type + arch + validate + drift + test
make cov          # coverage gate (>=90%)
make docs         # serve docs at :8000
```

Editing rule: `src/e_core/` changes here; systems re-materialize. `make core-check` in any system
fails when its copies drift.
