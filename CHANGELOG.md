# Changelog

Maintenance record of this repository: every sync, bump and repair, filed under the area it
touches — `stack`, `systems`, `infra`. Lines under `[Unreleased]` are written by the bots
(`tools/changelog.py`) and by humans alike; cutting a release moves them under a version heading.

## [Unreleased]

### stack

- floating tags resolved to current digests, the ledger's paradedb row on `v0.26.4-pg17` (`stack/resolve-2026-11-02`)
- `llm/gliner` has a healthcheck: `ghcr.io/edamlabs/gliner:0.1.3` (pinned, the EDamLabs image) ships `gliner probe`,
  which `GET /ready`s from inside the distroless image — `docker ps` shows `(healthy)` once the model is loaded.
- `rdb/paradedb` rides `paradedb/paradedb:v0.26.4-pg17` (from `0.26.2-pg17`, Renovate) — the tag is real on Docker Hub
  (amd64 + arm64, published 2026-10-29), and infra's `full_stack` golden, which pins the merged model of the whole real
  stack, is re-recorded to follow it: one byte wider, one line different, nothing else moved (`renovate/stack-images`)
- The LLM slot's default is `llm/vllm` (Gemma 4 26B-A4B AWQ), `llm/strata` its alternative — the final fight on one
  4090 and the same 20.6 GiB, measured 2026-10-28: 175 vs 57-86 tok/s decode, ~10k vs 4.1k prefill, 760 vs 59 tok/s
  at 8 concurrent, prefix reuse 34x vs 2x; strata speaks no logprobs (jev). `llm/vllm` defaults to 0.86 · 131072
  (desktop on the iGPU, TEI beside it: 212k KV tokens, embed+rerank stress 0 failures; 0.87 OOMs at start).
- `llm/llama` and `llm/ikllama` born, parked: llama.cpp and ik_llama.cpp with the MoE experts in RAM over one shared
  `llama-models` volume, ports 8082 / 8083, no slot alias. Kept for the day a CPU path nears vLLM — today Gemma 4 does
  31 tok/s at 8 GiB of card, Qwen3.8-Flash-Next UD-IQ4_XS 11-16 tok/s with ~350-790 tok/s prefill.
- `llm/reranker` born: `ghcr.io/huggingface/text-embeddings-inference:89-1.9` (GPU) serving
  `Alibaba-NLP/gte-multilingual-reranker-base` on `:80` (`POST /rerank`), a cross-encoder beside `llm/embed`; chosen over
  bge-reranker-v2-m3 on e-gnosis's sandbox (same pointer, twice as fast, the only one separating off-topic questions);
  floating tags resolved with it in the ledger (`feat/stack-reranker`)
- floating tags resolved to current digests with `llm/gliner` in the ledger (`feat/gliner-ping`)
- `llm/gliner` born: `ghcr.io/damvolkov/gliner:latest` (GLiNER NER, Rust/ONNX, CPU) on `:5800`, model registry in the named volume `gliner-models` mounted `:ro` and filled by hand (export or copy, see its README); no compose healthcheck — distroless, no shell, readiness is `GET /ready`
- floating tags resolved to current digests (`stack/resolve-2026-10-20`)
- `storage/minio` parked: `stack.parked: "true"` — the image died upstream with MinIO's OSS, the service is off on the host and the version bots stop probing it until removal

### projects

- `common` takes e-gnosis's second pass (TODO_REVERSE step 13):
  - PgQueuer never loses a cancel: PgQueuer 1.6 drops a cancel NOTIFY for a job picked but not yet registered and sends
    its log and NOTIFY at once, so a job cancelled in that window ran to its end under a `cancelled` record (e-gnosis
    #190, measured 1 in 20). The driver now logs first and notifies after (`_cancel_ordered`), and reads the log once
    the job's scope exists (`_register_cancelled`): a job cancelled by then never starts. A real test forces the
    interleaving; the running-cancel test waits for the handler, not the pick.
  - every template ignores `/secrets` — the folder `secrets/<APP_ENV>/` that step 9 reads was ignored by none — and
    `data` without its slash (a worktree's link), as e-gnosis learned (#192).
  - `TeiEmbedDriver`/`TeiRerankDriver` (and their settings) are `EmbedTeiDriver`/`RerankTeiDriver`: the capability
    before the brand, as every other repeated brand (`AuthPostgresDriver`, `CachePostgresDriver`).
  - Settled without change: dispatch's traced jobs and injected memory were already here (step 7); the templates
    type-check `tests/` whole, benchmarks included (e-gnosis's ty-excluded scripts do not exist here).
- `common` gains e-gnosis's last two providers and its health contract (TODO_REVERSE steps 11 and 7):
  - `ports/language` + `providers/adapters/language/lingua` (`LinguaAdapter`: ISO 639-1 over LANGUAGE_LANGUAGES, a
    20 000-character prefix, a text under 40 characters told by no one, pickled as its settings for worker processes,
    `annotator` = `lingua@<version>`) and `ports/watch` + `providers/adapters/watch/watchfiles` (`WatchfilesAdapter`:
    batches of added/modified/deleted over a debounce, a quiet tick, the defaults' ignore patterns plus the caller's,
    polling on demand); `lingua` and `watchfiles` imported nowhere else (TID251). Every project gains both libraries.
  - `Provider.health()` answers True or raises its own error, and that error is the reason `/ready` shows
    (`DatabaseError: connection refused`) — before, a provider answered False and `/ready` said only `unhealthy`. Every
    provider follows it (a store riding a database raises the database's error); `DispatchEngine.health` in memory
    raises `QueueError`. `HealthEngine` is unchanged: a raise was already its verdict's reason.
  - graph locks regenerated with e-taxis main.
- `common/ops/image`: the square font drew K as H and D as O — K now has a waist and stepped arms, D chamfered
  corners; `test_every_glyph_paints_a_shape_no_other_glyph_paints` gates every letter against every other by the
  pixels it paints (found rendering `e-track`; `e-serde`'s wordmark reads `SEROE`).
- `common`'s error tree gains `ServiceError` (TODO_REVERSE step 11), the branch of a project's own business — the one
  layer that never travels, named by the tree, filled by the project (e-gnosis hangs knowledge's and memory's there).
- `common`'s config (TODO_REVERSE step 9, e-gnosis's content):
  - secrets: every scope reads `secrets/<APP_ENV>/<var>` (gitignored, one file per key, its variable in lower case:
    `secrets/dev/auth_secret` is AUTH_SECRET) — dev the dev keys, prod the prod ones —; a scope that names its own
    `secrets_dir` (`/run/secrets`) reads that instead.
  - `RERANK_URL`, `GLINER_URL`: `none` turns them off — the composition root builds no driver, and one built anyway
    refuses to open.
  - the LLM's defaults meet the blueprint's own `stack/llm/vllm` (`demian-model`, the development key `local-dev`):
    before, a default call answered 401.
  - Not taken: lazy scope discovery (the blueprint's scopes import `infra/config/base`, never the composer, so no scope
    is met half-built). Open for Damien: a slot for a project's own scopes — today `common-check` refuses any file of
    a project's own under `infra/config`. e-gnosis's env names stay e-gnosis's; nothing here renames them.
- `common`'s processors and ops (TODO_REVERSE step 8, e-gnosis's content):
  - doc: no fast-pass block is dropped — the kinds both readers share are named as docling names them, any other
    (`rule`, `grid_fallback`) keeps its own label —, and every item carries its `group` (docling's `list`, `slide`,
    `form_area`…) and its `hyperlink`.
  - md: handed an `ExtractPort`, a web page is read by its main content first (a URL passed only when the name is one),
    whole through the converter when none is found or the extractor fails.
  - ops/file: `FileDetector` beside `FileFinder` — a file named from its name and first 64 KiB (anytomd's format and
    ZIP office format, tree-sitter's grammar by name then content, MIME, a UTF-8 sniff telling a page from text), the
    deciding layer in `because`; `tree-sitter-language-pack` joins every project. Not taken: e-gnosis's nature table
    and conversation dialects — its readers' routing, a consumer's table.
  - graph locks regenerated with e-taxis main (they lagged the units of steps 7 and 8).
- `common`'s HTTP, telemetry and dispatch tracing (TODO_REVERSE step 7, e-gnosis's content):
  - wreq: HTTP_AGENT on every request (Wikimedia answers 403 without one), HTTP_HEADERS as the process's own, a call's
    `headers` over both for that request only — one shared client, a service's credential never in it; `HttpPort`
    gains `upload` (a streamed POST) and `delete` (204 is None).
  - telemetry: `ports/telemetry` speaks the service's vocabulary — `SpanRole`, `SpanKey` —, and a span opened with a
    role is the role's kind and `openinference.span.kind`, its keys named per role (`embedding.model_name` on an
    embedding); without one it is as before (the graph template's calls unchanged). `carrier`/`resume` move a trace
    across a queue (W3C `traceparent`); the tracer is named by OTEL_SERVICE. `providers/adapters/telemetry/null` is
    tracing off. `engines/telemetry` (`TelemetryEngine`) is the guarded facade: a failing provider costs a warning and
    the trace, never the call; its `processor`, handed to `Logger.setup(extra=...)`, makes a log line inside a span
    one of its events with its ids.
  - dispatch: given a tracer (met by shape), a submit carries the current trace in `_trace` — never handed to the work,
    never compared when coalescing — and the run is a `job.<kind>` span, the child of that trace, each snapshot an
    event and the last one on the span.
  - health: already in `HealthEngine` (the reason of a raise or a timeout, one gather, the name as data); the reason a
    provider's own `health()` would give needs the `Provider` contract to change, left to decide.
- `common`'s auth (TODO_REVERSE step 6): the bearer is the scheme and everything after it (`strip().partition(" ")`,
  e-gnosis's parse) — `Bearer a b` is a key nobody holds, a 401, never the anonymous caller it read as before. Settled
  without change: the driver already prepares its tables on open (the admin path enters it, so no `migrate()` on the
  port), `ensure()` already runs only with AUTH_SECRET, and the tables stay `auth_account`/`auth_grant` — e-gnosis keeps
  `owner`/`token` on its own driver, so nobody renames and nothing migrates.
- `common`'s cache (TODO_REVERSE step 5): theine's CACHE_TTL may be None (kept until evicted), so each cache is built
  on its own settings — a ledger kept forever beside annotations kept 180 days — instead of one TTL for every scope;
  the Postgres cache refuses a value msgspec cannot encode as a `CacheError` at its border, so `CacheEngine` degrades on
  every refusal of its durable layer while still catching only `ProviderError`. Not taken from e-gnosis: `TieredCache.over`
  and `TieredCaches` (they build providers inside the engine, and the blueprint's theine is opened by the lifespan) and
  the partial `expires` index (the blueprint runs no expiry sweep that would read it).
- `common`'s PgQueuer rides the ports (TODO_REVERSE step 4): `PgqueuerDriver(database, listen)` takes a `DatabasePort`
  and a `ListenPort` — e-gnosis's design — and PgQueuer's own `Driver` is met by `PgqueuerBridge` over them (statements
  on the pool, a transaction or a connection, LISTEN on the database driver's one held connection): no pool and no
  connection of its own, its schema installed under the session lock on one `connection()`, `jsonb` parameters as
  Python values, a close bounded by QUEUE_DRAIN + 2 QUEUE_TIMEOUT, `OSError` an outage. `AsyncpgDriver`'s `pool`,
  `guard` and `dedicated()` — PgQueuer's private door — are gone. Measured: on psqlpy PgQueuer 1.6 cannot open (its
  schema read returns `name[]`, which psqlpy 0.12–0.13 does not decode), so the queue rides asyncpg and a real test
  names the refusal. `DispatchEngine` gains `queue(name, slots)`, `kinds`, `schedules` and a registry sealed once it is
  entered (a late declaration is a `DispatchError`). The span per job and the trace carrier wait for telemetry
  (step 7). Gates: common 1291, integration 109 (the queue's 67 on the real database), check green in the five.
- `common`'s two Postgres drivers gain e-gnosis's content (TODO_REVERSE step 3): `DatabasePort` adds `script()` and
  `connection()` (one connection, each statement its own commit), `ListenPort` is new (`listen`/`unlisten`; psqlpy by
  listener generations, asyncpg on one held pooled connection), `DatabaseError` carries `sqlstate` and
  `constraint_name`; asyncpg's connections are born with psqlpy's shapes (json/jsonb as Python values, uuid as text),
  run every statement on the extended protocol, bind a vector through `float` (numpy 2) and `provision()` like psqlpy;
  asyncpg's timeout is a `DatabaseError`. `AsyncpgDriver.connection()` (the dedicated connection PgQueuer rides) is now
  `dedicated()`. A repeated `unlisten` of a released channel is a no-op (e-gnosis raised `KeyError`). Gates: the port's
  contract on both drivers against a real Postgres (22), integration 109, common 1288 at 99 %.
- **The MCP door and the unified auth join the blueprint**, from e-gnosis's finished door (PR #165, `07d5477`), stripped of its domain. `common` (opt-in like the queue drivers; cli, tui and graph exclude them): `infra/auth` (`models`, `policy`, `resolver` — the Protocol the token middleware asks of whoever knows the keys —, `TokenMiddleware`, and the `guard` at `OPT[Access.*]` for routes and tools), `infra/mcp` (`models`, `registry`, `bridge`, `guard`, `mount` and `server` — the only module that imports `mcp.server*`, ruff TID251 holds the rest), `ports/auth`, `providers/drivers/auth/postgres` (`AuthPostgresDriver` over any `DatabasePort`; it creates its two tables on open) and `engines/auth` (`AuthEngine`: named by its module, the surname rule; accounts and keys over `AuthPort`). Errors join the one root (`AuthError`, `McpError`), settings the mirrored tree (`st.engines.auth`: `AUTH_SECRET` a `Secret`, `AUTH_TTL`, `AUTH_ADMIN`; `st.mcp`: `MCP_PATH`, `MCP_HOSTS`, `MCP_ORIGINS`); tach spells `infra.auth` and `infra.mcp` as edges and `test_taxonomy` reads that nothing always shipped imports them. api: `src/e_api/mcp/` (`tools/{health,user}.py` — each tool a native Litestar route, twin of its router —, `registry`, `mount`, `state`, `instructions`, `models`, `refusals`), the MCP lifespan beside the others (`system.mcp` ≡ `e_api/mcp/state.py`), and one auth system for both doors: the JWT bearer guard and `current_user` retire, `/users` rides `OPT[Access.USER|ADMIN]`, `GET /auth/me` and the admin's `POST|DELETE /auth/accounts/{name}/token` hand out and revoke opaque keys (the first admin key: `python -m e_api admin`), the authlib OAuth registry goes (no consumer left; OAuth2 is a sibling engine over the same records). The surface is held to `tests/resources/mcp/surface.json`; the endpoint is tested through the SDK's own client, both handshakes. `templates.yml`: the api choice `mcp` (modules, default on) removes the door cleanly. Gates: common 1273 tests at 99 %, api 146 at 100 %.

- **The house taxonomy** (e-nous `TODO_taxonomy`, 2026-10-30). The blueprint moves `projects/python/infra` →
  `projects/python/common` (package `e_infra`; `make common` / `common-check`), and `e_infra` is laid out by nature:
  `ports/` (one Protocol per capability, every provider port extends `Provider` — lifecycle, `health()`, a mandatory
  `ProviderSpec`: locality, workload, isolation, fork-safety, pooling, warm-up, memory hint), `providers/drivers/` and
  `providers/adapters/` by capability (`drivers/database/psqlpy.py`, `drivers/database/asyncpg.py`, `drivers/store/redis.py`,
  `drivers/http/wreq.py`, `drivers/queue/{pgqueuer,awa}.py`, `drivers/telemetry/otel.py`, `drivers/documents/docling.py`,
  `drivers/{embed,rerank}/tei.py`, `drivers/llm/openai.py`, `drivers/ner/gliner.py`, `drivers/cache/postgres.py`;
  `adapters/{cache/theine,markdown/anytomd,pages/liteparse,extract/rtrafilatura}.py`), `engines/` (`health`,
  `dispatch`, `cache`), `processors/` (`doc`, `md` — no library of their own). Providers are singletons, open by
  `async with`, translate foreign errors at the border; PgQueuer rides the asyncpg driver. `infra/errors.py` is the one
  root of every exception (`ProviderError` → `DriverError`/`AdapterError`, `EngineError`, `ProcessorError`, `OpsError`);
  `infra/config/` mirrors the module tree (`st.providers.drivers.database.psqlpy.dsn`, env names unchanged); every layer
  logs. tach and `test_taxonomy` gate the import table, the capability folders and the config mirror. Brought in from
  e-gnosis (read-only): the tiered cache, TEI embed/rerank, the OpenAI-compatible LLM, GLiNER, liteparse, rtrafilatura,
  PgQueuer's cron. Unit runs need no service: fakeredis, PgQueuer's in-memory queries, OTel's in-memory exporter,
  pytest-httpserver, and our own psqlpy/asyncpg/awa fakes; real-service tests are `integration`, out of CI's default.
  api, cli, graph and tui ride it (state branch `providers`, `/ready` from `HealthEngine`); the **mcp template retires**
  (MCP joins api next). `stack/README.md` maps each provider capability to its stack category.

- api, graph: **the tree is the state** (house law 22), gated — `tests/unit/e_<svc>/api/lifespan/test_parity.py` boots the real lifespan chain, walks the sealed system whole (`State` nodes and typed sections alike) and fails on any node whose class is a stratum's (every `e_<svc>` package but the edge `api`) living outside the package its chain names — e-gnosis's parity rule, exactly; the infrastructure sections (`shared`, `adapters`, `infra`) are walked, never placed. graph failed it on seven nodes and is reshaped: `system.logic` = `LogicState(agent, orchestrator)` in `e_graph/logic/state.py`, `system.instrument` = `InstrumentState(telemetry, contexts)` beside the RunState in `e_graph/instrument/state.py`; `ContextState` becomes `InstrumentContexts` in `e_graph/instrument/contexts.py`; `InfraState` keeps `adapters`, `processors`, `graphs`. One lifespan per layer: `api/lifespan/instrument.py` and `api/lifespan/logic.py` (the agent opens and closes there) split out of `services`, which keeps crypto and the processors; `sealed` composes `infra` and seals. The RunState mirrors the tree — `state.logic.orchestrator`, `state.logic.agent`, `state.instrument.telemetry` — and the lab's and DARTSOPS's sandboxes take the system root as RunState does (`simulate(..., system=)`, `evaluate(pipeline, data, system, agent)`); the cli's `system()` yields the same sealed tree. tach registers `e_graph.logic.state` in the `logic` layer. api passes as it stands (no stratum mounts a node yet; a planted one fails it). cli seals `shared` + `session` with no stratum node, mcp holds no state tree, tui's `State` is a walk's mutable bag: no gate for them. One object, one path: the gate also fails on any object the sealed tree holds at two paths (identity; interned atoms and the settings proxies aside, containers counted). graph held nine twins — `adapters`, `processors`, `graphs` and their leaves beside `infra.*` — and now writes them only under `system.infra` (the lifespans fill the open node, `sealed` retypes it as `InfraState`); `deps`, `/ready`, the routers' docstrings, README and the tests read `system.infra.*`. api has no `infra` section and holds no twin (a planted one fails it). Behaviour unchanged: every suite green.
- infra: two modules ported from e-gnosis (reverse-distill `gnosis-r4`), riding into every service by default like the rest of `infra/` and stdlib-or-anyio only. `ops/hash` — `hash_text` (sha256 over NUL-joined parts, 16 hex), `hash_bytes` (full sha256), `hash_version` (semver + 8-hex config digest); the keyless counterpart of `ops/crypto`, its registry row already claimed. `infra/events` — `MemoryEvents`, in-process pub/sub by event type over one bounded anyio stream (CAPACITY 1000, backpressure), one ordered delivery task, a raising handler logged and skipped, enter starts / exit drains; producers depend on `EventsPort`, declared beside it as `BackgroundPort` is beside `Background`. Its log test patches a fresh structlog logger inside `capture_logs`, never the module's cached one. The state-parity gate ships with the state-tree reshape (entry above).
- infra: **no `__init__.py` anywhere** (`TODO_init`) — the settings composer leaves `infra/settings/__init__.py` for the module `infra/settings.py` (`from infra.settings import settings as st` unchanged), the scopes move to the namespace package `infra/config/<scope>.py` (`base` included; `infra.settings.<scope>` → `infra.config.<scope>` in every service blueprint, test, docstring and ruff `runtime-evaluated-base-classes`). The composer discovers `f"{__package__}.config"`, never a spelled name: materialization rewrites imports, not strings. The blueprint's pytest path is `tests`, not `tests/unit` — with `infra/config` a namespace package, the mirrored `tests/unit/e_infra/infra/config/` would otherwise join it and the composer would import the tests (`from unit.e_infra.conftest import …`). mcp's `.dockerignore` drops the dead `.pre-commit-config.yaml` line.
- core → **infra**: `projects/python/core` is now `projects/python/infra` (package `e_core` → `e_infra`, brand e-core → e-infra) — the python infra blueprint of every system, named for what it holds; the house abandons `core/` and `common/` in every python project. `common/` disappears into the blueprint: the five shared root files (`prek.toml`, `.gitattributes`, `.python-version`, `.github/dependabot.yml`, `.github/CODEOWNERS`) are now the blueprint's own tracked root files, and every system materializes sections **and** root files with one `make infra`, drift-gated by one `make infra-check` (the `common`/`common-check` targets are gone). In every service: `src/core/` → `src/infra/`, `api/lifespan/core.py` → `api/lifespan/infra.py`, the state section `system.core` → `system.shared` (`CoreState` → `SharedState`, startup event `shared ready`) because `system.infra` is already the sealed section of the graph; cli seals `shared` + `session`; mcp drops its `settings as core` alias. tach layers relabelled to what they hold (`core` → `infra`). `CoreError` keeps its name (e-gnosis precedent) and the HKDF info labels (`e-core/token|jwe|encrypt|sign`) are untouched: changing them changes every derived key. `templates.yml` speaks infra throughout (common root/package, materials at the blueprint root, finalize and docker prunes); repo Makefile, README, QWEN, TODO and `infra/README` follow; the assembled `.github/` and its `infra/jobs/` sources pin Python from `projects/python/infra/.python-version`, materialize with `make infra` and drift-gate with `infra-check`; the blueprint release smoke imports `e_infra`. The blueprint's `docs/index.md` is now the full inventory of every module (purpose verbatim, who materializes what — the surface the e-taxis wizard reads to offer the optional parts). Only moves and renames: every project's suite, coverage, ty, tach and strict docs build unchanged in result. Ported from e-gnosis refactor/infra (PR #38).
- core: **cryptography is an agnostic tool — `ops/crypto`** — its errors move with it (`CryptoError` a root of its own, `TokenError`, `TokenFailure` out of `core/errors`), its enums too (`TokenAlg`, `TokenEnc`, `PasswordHasher` out of `core/settings/crypto`, which keeps only `CryptoSettings`), and the engine reads its configuration through the `CryptoConfig` protocol that `CryptoSettings` satisfies structurally; `generate_keys` mints the `CryptoKeys` dataclass rather than settings, `Crypto.load()` retires. Two additions need no engine: `Crypto.identify` (a keyed, stable id: NFKC + casefold + strip, HMAC-SHA256 under the key as given — never HKDF-derived — hex cut to 32) and `Crypto.token` (a fresh URL-safe bearer token), pinned vectors included; the RSA sign test runs on a monkeypatched 2048-bit key out of the `slow` marker, so the fast suite CI runs covers every branch. The HKDF info labels (`e-core/token|jwe|encrypt|sign`) are untouched: changing them changes every derived key. `docs/index.md` becomes the full inventory of the blueprint — every module, its purpose verbatim, who materializes what — and hosts the **closed ops registry: thirteen categories, the limit twenty**, enforced by `tests/unit/test_ops_contract.py` (a module outside the registry fails, a twenty-first category fails, a function without its category prefix fails). api, graph: the consumers switch to `ops.crypto`; mcp: the crypto deps (joserfc, cryptography, argon2-cffi, bcrypt) join its pyproject — the settings/crypto → ops/crypto chain imports them wherever the settings composer loads. Ported from e-gnosis #37.
- core: docling's timeout covers the body too — a deadline that lands while the response body is read (wreq `BodyError` with a `TimedOut` source) is a `TimeoutError` like any other, a body error that is no timeout stays a `BodyError`; `test_a_task_past_the_deadline_is_abandoned` failed under load whenever the cut fell on the body. The stub's `/stall` (headers at once, body after the deadline) pins that path deterministically (20/20 runs through `BodyError`)
- core: the background's durable engine is **PgQueuer by default, awa one setting away** — `QUEUE_ENGINE` (`QueueEngine`: `pgqueuer` | `awa`) picks it through the frozen map `adapters/queue.ENGINES`; the composition root that runs the background builds `Background(ENGINES[st.queue.engine](st.queue), slots)`. `adapters/pgqueuer.py` (PgQueuer 1.6 on asyncpg, pure async; `pgqueuer[asyncpg]` a runtime dependency) carries all its own recovery — the facade only dispatches: one `QueueManager` per queue on a connection of its own, supervised and restarted on a fresh one when it dies; retries through `RetryRequested`; calls bounded by `QUEUE_TIMEOUT` (`TimeoutError` — an `OSError` — caught before `OSError`, or a slow call read as an empty outage); close bounded by `QUEUE_DRAIN` + 2·`QUEUE_TIMEOUT`; a job's kind, queue, args, attempts and latest snapshot in `background.job`. awa: `connect` opens the whole pool within `QUEUE_TIMEOUT` (a refused connection is a `BackgroundError`, work falls back to memory, never a runtime stalled later), `close` bounded by `QUEUE_DRAIN` + `QUEUE_TIMEOUT`. `BackgroundPort.ping` joins the port; `Background.ping` answers through the durable engine and raises `in memory: …` when jobs would not survive a restart. Tests: the port contract on both engines, each on a database of its own per worker (`<dsn>_queue_<worker>`, `<dsn>_pgqueuer_<worker>`), PgQueuer's failure paths, the facade over memory, awa and PgQueuer. Every service still excludes the queue adapters from materialization (`adapters/pgqueuer.py`, `adapters/queue.py` beside `adapters/awa.py`). Ported from e-gnosis 79730be + #21; evidence in e-gnosis `docs/decisions.md`, 2026-10-22 ("the durable queue: PgQueuer by default", "the queue spike's last numbers": a 30-min job done first try where awa's default 5-min deadline killed it 6×, a SIGKILLed worker's job rescued in ~30 s against ~93 s, 1,000 jobs over 2 processes with 0 duplicates and 0 lost on both, every PgQueuer job reported completed against 118 awa jobs in an unknown state)
- core: `make lint` lints `scripts` only when it exists — the Zensical migration removed core's last script and left ruff failing on the missing path (E902), so core's `make ci` stopped at lint on every run since
- api, cli, graph, mcp, tui: `graph.lock.yml` regenerated with e-taxis (`GraphStore.write`) — it was already stale on main (`settings/ping.py`, `adapters/test_base.py`) and the materialized `core/background.py`/`core/settings/queue.py` move its hash
- api, core, graph: the docs generator moves from properdocs (the MkDocs fork) to **Zensical** — `properdocs.yml` becomes `zensical.toml` (`classic` Material variant, same palette and features), and the gen-files + literate-nav + `scripts/gen_ref_pages.py` trio is replaced by the native `mkdocs-autoapi` plugin: the reference tree and its nav are generated inside the build, no script, no virtual files. Docs group shrinks to `zensical` + `mkdocstrings[python]`; `make docs`/`docs-build` and the docs CI job run `zensical serve` / `zensical build --strict`.
- infra: the ci docs job builds with `zensical build --strict`; the templates manifest tracks `zensical.toml`; `qwen.md` names the Zensical site.
- api, graph: every adapter pinged at once at startup — one `adapter ping` event each, a warning when down, never a failed start — and on the new `GET /ready`: 200 when the required edges answer (`store`), 503 otherwise, every verdict in the body; `/health` stays liveness
- core: adapter health contract — `BaseAdapter.ping` is abstract (each adapter's cheapest real check: sqlite/postgres/awa `SELECT 1`, redis `PING`, docling `/ready` — replacing its `ready() -> bool` —, otel flush, anytomd a one-line render, http the open client) raising `PingError(adapter, reason)`; `BaseAdapter.survey` gathers many under one limit (`asyncio.gather`, `return_exceptions`) into typed `AdapterPing(name, required, ok, latency, reason)`, never raising; `PING_TIMEOUT` (2 s). Ported from e-gnosis 63deb94; the gather lives in core, not in each service, so api and graph share one implementation
- core: wall-clock benchmarks marked `slow` and out of `test`/`cov` by default (`TESTARGS`) — a cold runner hiccup is not a correctness gate
- graph: visual goldens leave `test`/`cov` (`TESTARGS` default `-m 'not ui'`) — they are runner-canonical now

### infra

- the root `make update` materializes through the api's `common` target (it still called the retired `infra`)
- **CI stops re-proving on main**: quality, test, coverage, ui, ecosystem, repo-gates and snapshots run on pull
  requests only — a push to main re-ran what its PR had just proved (710 of ~1,935 Actions minutes in a month on
  e-gnosis). docs builds on pull requests, and on push only where it deploys (public Pages). test skips its work on a
  docs-only change (docs/, *.md, zensical.toml), read off the merge commit's first parent inside the job — no extra
  job, so no extra billed minute on every PR.
- repo-gates and ecosystem jobs materialize with `make infra` + `infra-check` (the `core`/`common` targets are gone from every Makefile), pin the ecosystem Python from `projects/python/infra/.python-version`, and `snap-refresh` follows; `qwen.repo.md` and `infra/README.md` name the blueprint by its new path. Assembled `.github/workflows/{ci,snap-refresh}.yml` updated in lockstep with their `infra/jobs/` sources.
- ten action pins that named no commit fixed — `attest-build-provenance`, `setup-node`, the four `docker/*` actions, `pnpm/action-setup` (two phantoms of v6.1.0), `maturin-action`, `taiki-e/install-action`: each kept its version and got the commit its tag resolves to (every phantom shared the real SHA's first 8 characters); every pin in `infra/` and the committed `.github` now resolves (`gh api repos/<action>/commits/<sha>`)
- `renovate.json` and `renovate.repo.json` pass `renovate-config-validator --strict`: the managers `uv` and `docker` and `matchCategories: runtime` never existed (now `pep621`, `docker-compose`, `matchDepTypes: project.dependencies`), `regex` is `custom.regex`, `fileMatch` is `managerFilePatterns`, the action-pin datasource is `github-tags`; `requires-python` is never bumped; the project template adopts the policy proven on EDamLabs — lock file maintenance, Python tooling, actions and the agent CLI merge themselves (platform automerge), runtime patch releases too
- maintenance reads the provider-agnostic `SM_API_KEY` · `SM_BASE_URL` · `SM_MODEL` first and falls back to the `QWEN_*` names, so EDamLabs' organisation-level secrets and the per-repo `QWEN_*` of existing repositories both work
- sync-stack and snap-refresh mint their app token with `pull-requests: write`: sync-stack failed at `gh pr create` on every run (`Resource not accessible by integration`)
- **e-templates → e-arkhetypo**: a data-only repo — project blueprints, stacks, CI sources. `systems/` → `projects/python/` (`projects/rust/` reserved), area `systems` → `projects` (`area:projects`, `sync-projects`, `### projects`); `management/` leaves for e-taxis, its registry stays as `projects/templates.yml`. `repo-gates` now materializes every project and runs each one's `core-check`/`common-check` plus pinned zizmor; the repo's own `sync-infra` is retired (its fragment waits for e-taxis) and Renovate's `github-actions` manager bumps every committed `.github/` with `infra/` in one PR
- `maintenance` discards a compose file whose `image:` line moved; the agent CLI pinned to `@qwen-code/qwen-code` 0.25.3, tracked by Renovate (npm); dead labels `upstream-update`/`binding-update` dropped from the contract
- one shared GitHub App, `self-maintenance`, for every repo: `selfmaintain.md` and `repo-maintain.md` cut to the user's five steps (`bootstrap-repos {{repo}}`, Renovate, merge, Free-plan protection note), the per-repo App guides moved to `infra/setup/deprecated/`; the app's contract (names, permissions, rotation) in `infra/README.md`. Setup docs now take project tokens (`{{repo}}` = `damvolkov/<brand>`); `e_management gen` prints what a credential-holding feature needs by hand; `image` no longer lists the built-in `GITHUB_TOKEN` as a secret
- new feature `snap-refresh`: a dispatch regenerates one system's goldens on the runner and PRs the pixels; `gh pr create --head` fixed in the bot PR openers
- setup-uv step in `sync-stack`, `health-areas` and `upstream-context-repo`: bare `uv run --no-project` died 127 on runners without it
- setup docs for dummies: `selfmaintain.md` and `repo-maintain.md` rewritten as click-by-click GitHub installs (App, keys, Renovate, labels, branch protection, verification), same shape as anytomd's `docs/maintenance.md`
- fix(tools): `Request(url, headers)` pasaba el dict como *data* — todo sondeo de `health.py`/`upstream.py` moría antes de preguntar; orden de versiones por enteros, no lexicográfico; `zizmor` al grupo lint de management; las ensambladuras de `systems/*` entran en `drops` de los templates
- Self-maintenance for wide repos born: `repo-ci` and `repo-maintain` in `infra/` — the repo

