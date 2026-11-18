- common resolves again: `exclude-newer = "7 days"`, as the four templates, instead of the fixed 2026-10-21 instant
  every dependency PR outran (#160 raised `awa-pg>=0.6.17`, `ruff>=0.17.5`, `ty>=0.0.104`, `pytest-asyncio>=1.5.0`,
  all younger than the window, so `uv lock`, `tach` and `gates` could not resolve on main). Those four floors drop to
  the newest release inside the window (0.6.16, 0.17.4, 0.0.101, 1.4.1); the `awa-pg` exemption goes. Damien,
  18/11: «la opción más completa».
- Renovate waits the same 7 days on pep621 (`minimumReleaseAge`, `internalChecksFilter: strict`) in
  `infra/files/renovate{,.repo}.json` and `.github/renovate.json`: a floor can no longer outrun the lock.
- ty 0.0.101 flagged `routes: object` called under a stale `ty: ignore[not-callable]`: typed as
  `Callable[[], list[HTTPRouteHandler]]`, ignore removed.
- Evidence: every `>=` floor checked against its PyPI upload time (four outside, now none); `uv lock` resolves;
  `make ci` in common: lint, ty, tach, validate, harden, docs, 1446 passed, coverage 98.15%; renovate-config-validator
  --strict: valid.
