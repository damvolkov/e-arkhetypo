### projects

- common: `QueryPort` takes a bank member (`Query`, a `NamedTuple` of literal SQL and description, in `e_infra.infra.query`; one enum per consumer: `DatabaseQuery`, `CacheQuery`, `QueueQuery`, `AuthQuery`) and `script` a `Script` NewType, never a raw string; both database drivers, the auth, cache and PgQueuer consumers and every test follow. The gate `bank-port-takes-text` goes 4 -> 0 and `bank-sql-inline` 39 -> 10, no other rule moves; ruff, ty and tach clean, 1445 unit tests and the 80 database integration tests pass on a live Postgres.
