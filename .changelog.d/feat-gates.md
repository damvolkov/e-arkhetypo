### projects

- The house laws no tool names are gates, in one file every project carries: `gates/rules.yml` (one list, each rule
  tagged by level — `tree`, `shape`, `syntax` (ast-grep, each rule with its valid and invalid cases), `genealogy`,
  `parity`), typed by `gates/models.py` and run by `scripts/gate.py` (`check` · `semantic` · `test`). `common` holds
  the defaults; `templates.yml` materials, `make common` and `make common-check` carry them into every blueprint, and a
  project adds its own rules under `##### PROJECT #####`: `make common` keeps them, `common-check` compares only what
  comes before. Every Makefile gains `gates`. Built and calibrated on aivo-agents (`feat/gates`).
- Defaults: comment forms (law 6); no module-level function outside `ops/`/`operational/` or a dispatch handler, no
  loose private function (laws 1, 4); `if` only as a ternary or a one-statement guard, never in cascade — `elif`,
  `else`, nested, twice in a row, a block, a nested ternary (law 5); no `for`/`while` (law 7); no `isinstance` chain;
  a module-level literal or anything `Final` in CAPITALS, no mutable module state (laws 1, 22); a setting named as its
  environment variable (law 16); `_<public>_<what>` and privates before publics, framework overrides exempt (law 3).
- Law 26 (banks) moves from Semgrep to the gates: the five `bank-*` rules are ast-grep rules now, `semgrep.yml` and the
  `banks` hook are gone. Same findings: on aivo-agents, `common`, the four blueprints, e-taxis and e-nous every Semgrep
  finding has its ast-grep twin; ast-grep finds one more, a triple-quoted `SELECT` whose `FROM` is on another line
  (`common/.../queue/pgqueuer.py:68`). Tests stay out of the bank rules, as Semgrep's default ignore kept them.
  Bench (aivo-agents `src/`, three equivalent rules, n=10 interleaved): ast-grep 0.020 s, Semgrep 1.273 s median.
- What a tool already names moved to it: `os.environ`/`os.getenv` to ruff's banned-api (tests exempt), `__init__.py`
  to a prek `fail` hook `no-init`. The `gates` hook runs at stage `manual`, as `banks` did: the blueprints are not
  clean yet — static and semantic violations: `common` 107 + 46, `api` 73 + 45, `cli` 36 + 43, `graph` 180 + 81,
  `tui` 181 + 101. `make check` stays green on every template (api 170, cli 88, graph 770, tui 179 tests); `gates`
  is not part of it until they are.
- Left as found: `common/uv.lock` cannot be relocked on main (`awa-pg>=0.6.15` against `exclude-newer = 2026-10-20`),
  so its new dev dependency `ast-grep-cli` is not locked there; `common`'s `test_compose::test_full_stack` fails on main
  as before.
