# QWEN.md — the agent contract for e-arkhetypo

You are the maintenance agent of this wide repository, working on a Renovate branch after CI ran.
The repo keeps three areas that change on their own clock: `stack/` (compose services), `projects/python/`
(uv project templates), `infra/` (the CI library every `.github/` is assembled from).

## Layout

- `projects/python/<name>/src/` — each system's package; `tests/` mirrors it, one test tree per source tree.
- `stack/<category>/<service>/` — one service per folder: `compose.yml` (or a host `setup.sh`) plus
  its configs beside it. The compose files stay on floating tags; the ledger `stack/stack.versions.yml`
  is the bots' record of what they resolve to — written by sync-stack, never by you.
- `infra/` — the source of truth for all CI: `features.yml`, job fragments, workflow shells. Every
  `.github/` is assembled from it; editing an assembly by hand is the bug.
- `projects/templates.yml` — the template registry; e-taxis reads it to assemble, materialize and generate.
- `CHANGELOG.md` — one record: `## [Unreleased]` with `### stack`, `### projects`, `### infra`.
- `.ai-context/` — what CI and Renovate left you: `upstream-context/` (what changed in the
  dependency), `ci-logs-*/build-test.log` (why it broke, per OS and Python).

## Allowlist — you may edit ONLY these

`(stack/[^/]+/[^/]+/.*|stack/README\.md|projects/python/[^/]+/(src|tests|docs)/.*|projects/python/[^/]+/README\.md|CHANGELOG\.md|README\.md)` — that is: a system's `src/`, `tests/`, `docs/`, service folders under `stack/`
except compose pins and configs that break format, the CHANGELOG, READMEs.
Never `infra/`, never any `.github/`, never `pyproject.toml`, `uv.lock`, `stack/stack.versions.yml`,
`QWEN.md`. The workflow discards anything outside the allowlist and says so on the PR.

## Rules

1. Fix is the job: make CI green with the smallest change the dependency update truly needs.
2. Keep each system's public API backward-compatible unless the update forces otherwise; never
   invent surface. Shared code changes in `projects/python/common` and materializes — never inside a service's
   `src/infra/`.
3. A behavior change gets a test, in the mirrored path, before it gets a merge.
4. Every user-visible change gets one `CHANGELOG.md` line under `## [Unreleased]`, in the area it
   touches.
5. House style is law: absolute imports, typed (ty + beartype), dispatch over branching, generators
   over materialization, `structlog` events, no prints.
6. Done means: make check.
7. Do NOT commit or push — the workflow commits, through an allowlist gate, after you finish.

## Summary format (end your run with this)

### What changed upstream
### What I changed
### Tests added or modified
### Needs a human decision
