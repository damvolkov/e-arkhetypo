# e-core

Common core of the e-stack template systems: **uv · ruff · ty · tach · prek · pytest · properdocs**.

## What this is

Every module that a system imports by default lives once here. Services do **not** depend on this
package at runtime: `make core` in any system copies `src/e_core/core` and `src/e_core/ops` into its
own `src/` (byte-identical except import paths), so each system ships self-contained and this stays
the single source of truth. `make core-check` fails the moment a copy drifts.

## Modules

All sources live under `src/e_core/`, layered by [tach](https://tach.dev):

| Module | Layer | Purpose |
|---|---|---|
| [`e_core.core.settings`](reference/e_core/core/settings/index.md) | core | Composed settings: one BaseSettings reader, per-scope structs discovered on import |
| [`e_core.core.logger`](reference/e_core/core/logger.md) | core | Structured logging: JSON in prod, ordered plain text in dev |
| [`e_core.core.errors`](reference/e_core/core/errors.md) | core | Typed exception hierarchy rooted at CoreError |
| [`e_core.core.crypto`](reference/e_core/core/crypto.md) | core | Password hashing, JWS/JWE tokens, signatures, AEAD |
| [`e_core.core.state`](reference/e_core/core/state.md) | core | The app resource graph: attribute-navigable, sealed after startup |
| [`e_core.ops.file`](reference/e_core/ops/file.md) | ops | Package discovery: modules, classes, functions — the settings composer's engine |

Reference pages are generated automatically from the sources: drop a new module under `src/` and it
appears here on the next build.
