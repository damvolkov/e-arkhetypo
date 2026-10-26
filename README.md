# e-arkhetypo

<p align="center">
  <img src="assets/logo.svg" alt="e-arkhetypo" height="110" />
</p>

The **e-stack** archetypes: project blueprints, infrastructure stacks and CI/CD sources — data, not
tooling. No Python project lives at this root: every project is self-contained under `projects/<language>/`
(`python/` today, `rust/` reserved), infrastructure stacks under `stack/`, CI/CD sources under `infra/`.
The deterministic engine that assembles, materializes and generates from them is
[e-taxis](https://github.com/damvolkov/e-taxis); it reads the registry `projects/templates.yml`.
One style: materialize over import, drift-gate over trust, gates as code.

One triumvirate, all Greek — the mind decides, the archetypes hold the forms, the order executes:

<p align="center">
  <img src="assets/triumvirate.svg" alt="e-nous · e-arkhetypo · e-taxis" height="230" />
</p>

| Pillar | Is | Changes here |
|---|---|---|
| [e-nous](https://github.com/damvolkov/e-nous) | the mind — persona, skills, agents, commands, workflows, evals, and the transpiler | doctrine |
| **e-arkhetypo** | the archetypes — project blueprints, stacks, CI sources; data only | templates |
| [e-taxis](https://github.com/damvolkov/e-taxis) | the order — the deterministic engine that turns archetypes into running things and installs the mind into each harness | tools |

##### PROJECTS — the templates #####

Each is an independent uv project with its own `pyproject.toml`, `Makefile`, tests, docs and CI/CD.
App vs library is what changes, not the rules: `ruff · ty · tach · pytest+coverage · strict docs ·
zizmor`, git-tag releases, all publishing gates inert by default.

- `projects/python/infra` — **e-infra**: the shared source of truth. Layered settings composer, structured logger,
  state, ops agnostic tools (file discovery, crypto), service adapters. Services do not import `e_infra` — they
  **materialize** it. Edit shared code only here, never in a service's `src/infra/`.
- `projects/python/api` — **e-api**: Litestar + Granian API service template, msgspec end to end.
- `projects/python/graph` — **e-graph**: LangGraph runtime, rustworkx topology, React Flow canvas over
  Litestar + Granian (api + canvas).
- `projects/python/mcp` — **e-mcp**: in-process `MCPServer` over Streamable HTTP, granian factory, bearer gate
  on loopback.
- `projects/python/cli` — **e-cli**: cyclopts on uv, lazy declarative commands, typed injection, undo journal.
- `projects/python/tui` — **e-tui**: config-driven responsive layout mini-framework over Textual, fillable
  static/dynamic frames, snapshot gallery.

##### STACK — the services #####

Self-hosted infrastructure, one folder per service: `stack/<category>/<service>/compose.yml`, with its
configs, entrypoints and assets beside it. Categories by role: databases by data model (`rdb`, `cdb`,
`vdb`, `gdb`, `ddb`, `tdb`), infra (`queue`, `proxy`, `auth`, `watch`, `storage`, `llm`, `speech`, `rag`,
`mem`, `agent`, `front`, `media`, `tools`). One shared network `stack`; services see each other by
hostname. Upstream default ports, explicit overrides. `:latest` unless the tag fixes a format.
Indivisible pairs are `include`d and health-gated. Details in `stack/README.md`.

##### INFRA — CI/CD as source #####

`infra/` is to every project's `.github/` what `projects/python/infra` is to its `src/`: the source of truth,
materialized and assembled — a feature map (`features.yml`), atomic jobs, workflow shells with token
slots, one-time install instructions, and the generated contract test (`test_ci_contract.py`) that
validates manifest vs workflows in both directions. No workflow is hand-written twice; e-taxis
assembles them. Two `infra/`, two jobs, never confused: this one assembles CI/CD; `projects/python/infra`
materializes the python modules and the shared root files.

The repo keeps its three mutable areas honest with `repo-maintain`: Renovate opens PRs for
`projects/python/` deps, `stack/` images and the action pins of `infra/` and every committed `.github/`;
`sync-projects`/`sync-stack` follow each area; `health-areas` reports stack · projects · infra monthly;
`maintenance` mends what a bump breaks. Every maintenance line lands in `CHANGELOG.md` under its area.

##### USE #####

```bash
cd projects/python/api && make install   # materializes infra/ops + shared files, syncs deps, installs git hooks
make -C projects/python/api check        # lint + type + arch + validate + drift + tests
make -C projects/python/api ci           # every CI gate in one command
make update                      # re-materialize projects/python/api from its sources (infra + shared files)
make check                       # the fast gate of every project
```

`make` (no target) lists every command in any project.
