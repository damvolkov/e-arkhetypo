# e-templates

Collection of **e-stack** project templates. No Python project lives at this root: every project
is a self-contained system under `systems/`, and infrastructure stacks live under `stack/`.

##### STRUCTURE #####

```
systems/core/   # e-core — the common core: settings, logger, crypto, state, ops (+ common/: shared project files)
systems/api/    # e-api  — Litestar + Granian API service template (full stack: Docker, compose, CI/CD)
systems/mcp/    # e-mcp  — MCP server template: MCPServer over Streamable HTTP + granian, bearer gate on loopback
stack/          # infrastructure services (auth, db, queue, proxy, ...) — containers, not Python projects
```

Each system is an independent uv project with its own `pyproject.toml`, `Makefile`, tests, docs and
CI/CD. App vs library is what changes, not the rules: `ruff · ty · tach · pytest+coverage · strict
docs · zizmor`, git-tag releases, all publishing gates inert by default.

##### COMMON #####

`systems/core` is double-sourced: services do not import `e_core` — they **materialize** it.

- `make core` copies `core/` + `ops/` into the service's own `src/` (import paths rewritten to bare
  `core.*` / `ops.*`); `make common` copies the shared project files from `systems/core/common/`
  (pre-commit, gitattributes, dependabot, CODEOWNERS, python-version).
- `make core-check` / `make common-check` fail the moment a materialized copy drifts from its source.
- Edit the shared code **only** in `systems/core/src/e_core/` — never in a service's `src/core/`.

##### USAGE #####

```bash
cd systems/core && make install    # the common library + shared file sources
cd systems/api  && make install    # materializes core/ops/common, syncs deps, git hooks
make -C systems/api check          # lint + type + arch + validate + drift + tests
make -C systems/api ci             # every CI gate in one command
```

Each project's `make` (no target) lists its commands.
