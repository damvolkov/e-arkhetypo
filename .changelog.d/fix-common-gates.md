- common passes its own house gates and the gate now runs on every commit and in CI: 76 `check` violations (comment-form
  30, loop 23, bank-sql-inline 10, module-function 5, mutable-global 4, settings-case, private-function, constant-case,
  bank-prose-literal) and 46 `semantic` ones (private-genealogy) fixed with behaviour kept — private methods renamed to
  `_<public>_<what>` / `_common_<what>` (`CheckedStruct._check` is now `_post_init_check`, `SecretsEnv.app_env` is
  `APP_ENV`), SQL of `queue/awa` and `store/sqlite` moved into `AwaQuery` / `SqliteQuery` in `infra/query.py`, the
  `tui` font tables frozen as `MappingProxyType`, the two guards are callable classes (`AuthGuard`, `MCPGuard`; the
  `guard` / `internal` instances keep their names), the OTel exporters are `OTelExporter.http|grpc`, compose merge and
  logo strokes are expressions. Two rules narrowed, each with its cases in `gates.engine test`: `loop` admits, inside
  an `async def`, a `while` that awaits or yields, a `for` that yields (an async generator has no `yield from`) and an
  `async for` that awaits (an unbounded drain no comprehension expresses); `bank-prose-literal` ignores the members of
  an `Enum` bank, where a statement's description belongs. The `gates` hook leaves `stages = ["manual"]` and runs at
  pre-commit; `tests/unit/gates/test_rules.py` runs `test`, `check` and `semantic` over the project, so the unit suite
  in CI holds them (the CI workflow is assembled from `infra/jobs/ci/quality.yml`, outside common: untouched). Evidence:
  `make gates` green, `make test` equal to main (2 failed, 7 errors: gcs, gemini and vision credentials), ruff, ty, tach
  green.
