# Decisions

Every architectural decision: date, the decision, the evidence, what was rejected and why.

## 2026-11-05 — The changelog is a fragment per branch, folded after every merge; the tool is ours, stdlib

**Decision.** A change is recorded in `changelog.d/<branch, / as ->.md`, never in `CHANGELOG.md`: two branches never
touch the same file. After every merge to main the `changelog-fold` workflow runs `changelog.py fold` on the fixed
branch `chore/changelog-fold` (rebuilt from main), opens or updates one PR with the self-maintenance App token and
auto-merges it. `CHANGELOG.md` is written only by that fold and by a release; the prek hook `changelog` blocks any
other commit that stages it, unless `CHANGELOG_FOLD=1`. The tool stays `infra/files/tools/changelog.py` (stdlib,
`record` and `fold`), shipped to every repo with the `selfmaintain` and `repo-maintain` features.
**Evidence.** Nearly every merge conflicted on `CHANGELOG.md`: each branch inserted its entry on the same line under
`## [Unreleased]` and the resolution was always "keep both". A fragment per branch removes the shared line. Tests
(`tests/unit/tools`, `tests/unit/hooks`): fold order by first-commit date, areas kept where the file uses them, plain
bullets otherwise, idempotent, no fragments is a no-op; the hook blocks a staged `CHANGELOG.md` and passes with
`CHANGELOG_FOLD=1` or nothing staged (also run through `prek` in a scratch repo). zizmor: no findings on the
workflow. Not run: the workflow end to end, which needs the App installed on the repo.
**Rejected.** towncrier, scriv and changie do the same, but towncrier types a fragment by file name
(`<id>.<type>.md`), scriv wants its own config and categories, changie is a Go binary: a toolchain a runner does not
have and a taxonomy our changelogs do not use, against a stdlib tool that already runs anywhere and that the bots'
`record` already uses. Folding only on release (findr-ground has no tags, the file would never move) and a generated
view of the fragments (the file people read would not exist in the tree). A `GITHUB_TOKEN` PR for the fold (it does
not trigger the required CI, so the PR would never merge).

## 2026-11-09 — The fragments folder is hidden: `.changelog.d/`

**Decision.** The per-branch fragments live in `.changelog.d/<branch, / as ->.md` (and the shipped guide in
`infra/files/.changelog.d/README.md`); the fold tool, the workflows that stage fragments, the features' file lists and
the prek hook's message name it. Fragments stay tracked, never ignored: they are the record a PR carries and the fold
reads from `origin/main`. The Triad moves with it: e-nous's `changelog` and `plans` checks, e-taxis's allowlist.
**Evidence.** Damien (2026-11-09): the folder is plumbing, not a page of the repo. findr-ground had dropped fragments
(TODO_layout 11) and, behind a merge queue, met four `CHANGELOG.md` conflicts in one day (#62 twice, #64, #65); it
returns to fragments under this name.
**Rejected.** Renaming in one piece only: the checks would see no fragments and demand `CHANGELOG.md`, which the hook
forbids — no commit passes. Gitignoring the folder: the record would never reach the PR.

## 2026-11-24 — docling-graph loads replace atomically; the graph named X is the latest build

**Decision.** A build writes into a `<graph>__dgtmp` staging graph and, once every statement has loaded, drops the
target and `GRAPH.COPY`s the staging graph over it; on any failure the staging graph is deleted and the target is left
untouched. So a re-run *replaces* `X` rather than merging into it. Cypher strings are scrubbed of raw C0 control bytes
(except tab/CR/LF) and the Unicode line separators before they reach FalkorDB.
**Evidence.** The load was a partial write on failure: `dg_docling` left 134 `Entity` and no `Document` after a 502, and
re-runs of the same PDF grew the graph 211→231 because every statement `MERGE`s on node id. FalkorDB reads a statement
as a C string: a NUL byte from PDF extraction cut `MERGE ... SET n.name = "Doc\0..."` mid-string →
`Unterminated string ... 502` (reproduced deterministically against the live server; the earlier real run hit the same at
`pos: 105`). The swap was verified live: success builds and cleans staging, a mid-build failure preserves the target and
leaves a first-ever target absent, indexes carry across the `COPY`, and a 64-char name (71-char staging) is fine.
**Rejected.** Query parameters instead of text splicing (`GRAPH.QUERY ... CYPHER k=v`) removes the whole escaping class
in principle, but it means parsing the library exporter's finished statements back into placeholders — reimplementing
the exporter to reach a byte (NUL) that the exporter already handles for every other control. Sanitizing at the one text
boundary the app owns is smaller and, measured, the only fatal byte. Delete-after-fail with no staging was rejected: it
still leaves the graph half-written during a multi-statement load.

## 2026-11-24 — FalkorDB connects lazily so a dead dependency is a 503, never a boot crash

**Decision.** The FalkorDB client is built on first use (a memoized `state.db`), not in the lifespan. Booting does not
require the database; a request that needs it and finds it down raises `RedisError` → 503, and a later call recovers.
**Evidence.** `FalkorDB(...)` connects in its constructor (`Is_Sentinel` probes `INFO`), so the eager lifespan build
raised `ConnectionError` during startup and `uvicorn` exited — `Application startup failed` — when the port was closed.
Proven live on a throwaway server: with a dead database the service now boots, `/health` answers 503
(`ConnectionError`, the Redis branch) and a build answers 503, while a dead docling answers 503 (`ConnectError`, the
httpx branch) and all-live `/health` answers 200.
**Rejected.** Wrapping the lifespan build in try/except and keeping the graph in the state tree "sealed at startup" —
the seal would be conditional and a restart after a DB outage would still crash; first-use construction is simpler and
self-heals.

## 2026-11-24 — template selection is a typed allowlist; `document` stays the default

**Decision.** A `template` form field is typed to a `Template` `StrEnum` whose members are the only import paths handed
to `run_pipeline`, so a request cannot name arbitrary code. The `document` template's `kind` is now a closed `EntityKind`
enum, and a new `paper` template (`Author`/`Concept`/`Dataset`/`Organization`) is offered per request; the service default
(`DG_TEMPLATE`) stays `document`.
**Evidence.** `rag.pdf` gave 240 of 341 entities as `person` — the paper's authors plus every cited author — under
`document`; the same document under `paper` is 116–109 typed nodes whose top authors are the real FAIR team and whose
concepts are RAG/DPR/BART/T5 (hand-checked on rag.pdf and docling.pdf). `kind` was free-text and had drifted (`dataset`
appeared in docling.pdf). Validation proven at the ASGI boundary: `templates.secret.Evil`, `../../etc/passwd` and
`os.system` are 422 before any dependency is touched; bank values pass.
**Rejected.** Making `paper` the default silently: it changes the graph shape every existing caller sees, and the
document type that wants it can ask. Dropping `person` from `document` instead: loses real people for non-paper documents
where they belong.
