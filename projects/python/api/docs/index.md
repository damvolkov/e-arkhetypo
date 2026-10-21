# e-api

Generic **e-stack** API service template: **uv · ruff · ty · tach · prek · pytest · properdocs · docker**.
Litestar + Granian + msgspec end to end, Rust-backed tooling.

## Quickstart

```bash
make install    # materialize core/ops/adapters + shared files, uv sync, git hooks
make check      # lint + types + architecture + drift + tests
make run        # python -m e_api
make docs       # serve this site at http://localhost:8000
make up         # docker compose up
```

## Layout

The service lives in `src/e_api/`, layered by [tach](https://tach.dev). `src/core/`, `src/ops/` and
`src/adapters/` are **materialized** from the common core by `make core` — edit them there, never here:

| Module | Layer | Purpose |
|---|---|---|
| [`e_api.main`](reference/e_api/main.md) | api | Composition root: explicit registration only, `create_app` for granian |
| [`e_api.api.security`](reference/e_api/api/security.md) | api | Bearer enforcement and the OpenAPI contract |
| [`e_api.api.middlewares`](reference/e_api/api/middlewares.md) | api | Correlation id, CORS and the middleware chain |
| [`e_api.api.deps`](reference/e_api/api/deps.md) | api | Dependency chains: store access, current user, graph |
| [`e_api.api.lifespan.core`](reference/e_api/api/lifespan/core.md) | api | One-time load of the core singletons, mirrored into `state.core` |
| [`adapters.ports`](reference/adapters/ports.md) | adapters | Structural contracts — StorePort, HttpPort; sqlite, redis, http implement them (materialized) |
| [`e_api.models.user`](reference/e_api/models/user.md) | models | msgspec DTO families — the only place data crosses trust boundaries |
| [`e_api.websockets.telemetry`](reference/e_api/websockets/telemetry.md) | api | Typed websocket listeners — structured frames in and out |
| [`core.settings`](reference/core/settings/index.md) | core | Composed settings: one BaseSettings reader, per-scope structs (materialized) |
| [`core.logger`](reference/core/logger.md) | core | Structured logging: JSON in prod, ordered plain text in dev (materialized) |
| [`core.crypto`](reference/core/crypto.md) | core | Password hashing, JWS/JWE tokens, signatures, AEAD (materialized) |
| [`ops.file`](reference/ops/file.md) | ops | Package discovery — the settings composer's engine (materialized) |

Reference pages are generated automatically from the sources: drop a new module under `src/` and it
appears here on the next build.
