- No invalid state representable (e-nous law 13, plan `TODO_types` in e-nous). common's gate DEFAULTS gain ten rules
  over `src`, `scripts`, `gates`: `any-annotation` (Any where ruff ANN401 cannot see), `object-annotation` (avoidable,
  kept only marked with its reason), `cast`, `literal-alias`, `empty-sentinel`, `final-constant`, `mutable-field`,
  `string-getattr`, `not-open`, `type-ignore`; ruff `ANN` in every blueprint (tests ignore only ANN401). Baseline on
  common before: any 154, object 89, final-constant 62, empty-sentinel 42, mutable-field 30, not-open 19, cast 12,
  string-getattr 12; after: 0 on all, ruff, ty and tach clean, 1427 tests green. 20 marked escapes, each with its reason.
- common: `Opened[T]` (ports/provider) replaces the 19 hand-written "is not open" guards; one `JSON` alias
  (`infra/payload`, a tach leaf) replaces three; `Provider` StrEnum replaces `Literal[tuple(PROVIDERS)]  # ty: ignore`;
  absence is `X | None` (settings secrets, Caller, ProviderHealth.reason, documents); fields read-only. The gate engine
  passes its own rules (`Verbatim` for ast-grep's opaque YAML: msgspec 0.21.1 cannot analyse a recursive JSON alias,
  RecursionError, measured). beartype's claw over common fails collection (72 errors: ruff TC imports under
  TYPE_CHECKING) — not adopted.
- #138 (gates/engine.py, one folder) merged into this branch. common's lock unblocked: a dependency bot raised
  `awa-pg>=0.6.15` without relocking, and `exclude-newer = "2026-10-20"` read in the local zone locked a different
  cutoff than CI — now `2026-10-21T00:00:00Z` plus an `awa-pg` window to 2026-11-09; `ast-grep-cli` lands in the lock.
  `full_stack` golden follows c39caef (Hermes' secrets mount).
- The templates are frozen (Damien, 2026-11-10): prek hook `frozen-templates` refuses any staged path under `projects/`
  outside `projects/python/common` (`TEMPLATES_THAW=1` to retire one), tested in `tests/unit/hooks/test_prek.py`; CI's
  repo drift step no longer re-materializes them. This commit is the last thaw: api, cli and tui at zero on the type
  rules (170, 88, 179 tests green); graph keeps only the TID251 fix.
- TID251 over the tests of api, cli, graph, tui: the blanket ignore left the pytest-ghost ban off there (#139's miss);
  now only the conftests that read the environment are exempt. A probe `xfail` + `skip` gets 2 × TID251 in each.
