### projects

- e-nous law 26 (literals live in banks) as a gate: `projects/python/common/semgrep.yml` — `bank-sql-inline`,
  `bank-prose-pattern`, `bank-prose-literal`, `bank-port-takes-text`, `bank-literalstring-cast` — materialized into
  every project (`templates.yml` materials, each blueprint's `make common` / `common-check`) and run by the prek hook
  `banks`, stage `manual` for now: `uv run prek run --hook-stage manual banks --all-files`. Calibrated on aivo-agents
  before its `refactor/guard` (`6581f7a`): every inline prompt, bilingual guard regex, Spanish advice phrase,
  `sql: str` port and `LiteralString` cast caught; PII, module-path and template regexes and tests' prose left alone.
  Not blocking yet: `common` itself carries ~45 inline statements and a `DatabasePort` that takes `sql: str`; `api`
  (`mcp/instructions.py`) and `graph` (`logic/orchestrator/fusion.py`) one prose literal each.
- e-nous law 23: no `services` as a layer word. `api`: `lifespan/services.py` → `lifespan/crypto.py` (it mounts
  `system.crypto`). `graph`: split into `lifespan/crypto.py` and `lifespan/execution.py` (`infra.engines`,
  `infra.processors`), one branch one module. `cli`: `services/` → `logic/stores/{auth,project}/store.py`
  (`AuthStore`, `ProjectStore`) seen by the commands through `logic/stores/ports.py`; tach layer `services` → `logic`.
  Evidence: api 169, cli 88, graph 770 unit tests green; lint, ty and tach clean on the three.
