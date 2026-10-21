# e-core

Common core of the **e-stack** template systems: every module that systems import by default
(`core/`: settings composer, logger, crypto, state, errors, background · `ops/`: package discovery) lives once here.
Services materialize these files into their own `src/` with `make core` — this repo is the source of truth.

##### LAYOUT #####

```
src/e_core/     # the library, layered by tach: core → ops
common/         # shared project files for EVERY system (materialized by `make common`)
tests/unit/     # mirrors src, import-mode=importlib; includes the CI-gate contract test
Makefile        # uv · ruff · ty · tach · pytest — no Docker: it is a library
```

##### USAGE #####

```bash
make install      # materialize shared files + uv sync
make check        # lint + type + arch + validate + drift + test
make cov          # coverage gate (≥90%)
make docs         # serve docs at :8000
```

Editing rule: `src/e_core/` changes here; systems re-materialize. `make core-check` in any system
fails when its copies drift.
