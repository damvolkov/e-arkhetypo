# e-infra

The python **infra blueprint** of the e-stack template systems: every module that systems materialize
(`infra/`: settings composer, logger, state, errors, background · `ops/`: package discovery, crypto —
a closed registry of tool categories) lives once here. It is not a runtime dependency: services
materialize these files into their own `src/` with `make infra`, and the e-taxis wizard reads this
tree to offer the optional parts when it exports a new project — this project is the source of truth.

##### LAYOUT #####

```
src/e_infra/    # the library, layered by tach: infra → ops
prek.toml       # the shared root files of EVERY system — with .gitattributes, .python-version,
                #   .github/dependabot.yml and .github/CODEOWNERS; their `make infra` copies them
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

Editing rule: `src/e_infra/` and the shared root files change here; systems re-materialize.
`make infra-check` in any system fails when its copies drift. `docs/index.md` details every module
and holds the closed registry of the `ops/` categories.
