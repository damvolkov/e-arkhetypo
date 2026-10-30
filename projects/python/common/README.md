# e-infra

The python **infra blueprint** of the e-stack template systems: every module that systems materialize
(`infra/`: settings composer, logger, state, errors, background supervisor · `ops/`: package discovery, crypto —
a closed registry of tool categories · `ports/`: one contract per capability · `providers/`: drivers for what lives
outside the process, adapters for libraries inside it · `engines/` and `processors/`: execution and transformation over
the ports) lives once here. It is not a runtime dependency: services
materialize these files into their own `src/` with `make common`, and the e-taxis wizard reads this
tree to offer the optional parts when it exports a new project — this project is the source of truth.

##### LAYOUT #####

```
src/e_infra/    # the library, layered by tach: engines | processors | providers → ports → infra → ops
prek.toml       # the shared root files of EVERY system — with .gitattributes, .python-version,
                #   .github/dependabot.yml and .github/CODEOWNERS; their `make common` copies them
tests/unit/     # mirrors src, import-mode=importlib; the CI-gate and ops-registry contract tests
Makefile        # uv · ruff · ty · tach · pytest — no Docker: it is a library
```

##### USAGE #####

```bash
make install      # sync deps + git hooks
make check        # lint + type + arch + validate + test
make cov          # coverage gate (≥90%)
make docs         # serve docs at :8000
```

The taxonomy in one line: a provider (singleton, opened by the lifespan, `health()` that never raises, a declared
`ProviderSpec`) is a **driver** when the work happens outside the process and an **adapter** when it happens inside;
engines and processors reach providers only through ports; only the composition root names a concrete class.

Editing rule: `src/e_infra/` and the shared root files change here; systems re-materialize.
`make common-check` in any system fails when its copies drift. `docs/index.md` details every module
and holds the closed registry of the `ops/` categories.
