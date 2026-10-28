# Changelog

Maintenance record of this repository: every sync, bump and repair, filed under the area it
touches — `stack`, `systems`, `infra`. Lines under `[Unreleased]` are written by the bots
(`tools/changelog.py`) and by humans alike; cutting a release moves them under a version heading.

## [Unreleased]

### stack

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

- **CI stops re-proving on main**: quality, test, coverage, ui, ecosystem, repo-gates and snapshots run on pull
  requests only — a push to main re-ran what its PR had just proved (710 of ~1,935 Actions minutes in a month on
  e-gnosis). docs builds on pull requests, and on push only where it deploys (public Pages). test skips its work on a
  docs-only change (docs/, *.md, zensical.toml), read off the merge commit's first parent inside the job — no extra
  job, so no extra billed minute on every PR.

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

