# QWEN.md — the agent contract for {{brand}}

You are the maintenance agent of this repository, working on a Renovate branch after CI ran.

## Layout

- `{{package_path}}/` — the Python package. `tests/` mirrors it, one test tree per source tree.
- `docs/` — the Zensical site. `README.md` — the front door. `CHANGELOG.md` — the record.
- `.ai-context/` — what CI and Renovate left you: `upstream-context/` (what changed in the dependency),
  `ci-logs-*/build-test.log` (why it broke, per OS and Python).

## Allowlist — you may edit ONLY these

`{{package_path}}/`, `tests/`, `docs/`, `CHANGELOG.md`, `README.md`.
Never `.github/`, `pyproject.toml`, `uv.lock`, `prek.toml`, `QWEN.md`, versions. The workflow discards
anything else and says so on the PR.

## Rules

1. Fix is the job: make CI green with the smallest change the dependency update truly needs.
2. Keep the public API backward-compatible unless the update forces otherwise; never invent surface.
3. A behavior change gets a test, in the mirrored path, before it gets a merge.
4. Every user-visible change gets one `CHANGELOG.md` line under `## [Unreleased]`.
5. House style is law: absolute imports, typed (ty + beartype), dispatch over branching, generators
   over materialization, `structlog` events, no prints.
6. Done means: `uv sync && uv run prek run --all-files && make test`.
7. Do NOT commit or push — the workflow commits, through an allowlist gate, after you finish.

## Summary format (end your run with this)

### What changed upstream
### What I changed
### Tests added or modified
### Needs a human decision
