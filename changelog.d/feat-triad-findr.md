- common (`projects/python/common`): what findr-ground generalized, back in the spine (findr-ground `TODO_triad` step 1,
  `taxis reverse-distill` by hand). New ports `BlobPort`, `TriplesPort`, `ShapesPort`; providers `GCSBlobDriver`,
  `GoogleLLMDriver`, `GoogleEmbedDriver`, `OxigraphTriplesAdapter`, `PyshaclShapesAdapter`, `RudofShapesAdapter`;
  engines `LLMEngine` (tiers, retries, `ModelCache` in RECORD/REPLAY/OFF, one call per key in flight) and
  `ReleaseEngine` (WORM versions on a `BlobPort`, one conditional-write pointer; the graph namespace is a constructor
  argument); their errors, the `LLM_*` / `RELEASE_PREFIX` / `GCS_*` / `GENAI_*` / `OXIGRAPH_PAGE` settings, tests
  (contract tests over the memory double and a GCS JSON-API stand-in, `tests/support/{blob,gcs,models}.py`,
  `MemoryCache`), the five libraries and their ruff banned-api rows. Spine fixes: transport errors translated at the
  border (GCS, Google LLM/embed, TEI tokenizer); last arm of an exhaustive `match` as `case _` (`ops/file`, `ops/registry`,
  `infra/config/api`, `wreq`, `otel`, `telemetry`, `doc`); `HealthEngine.watch(name, provider, *, required=False)`;
  `make offline`. `PostgresCacheDriver` and `PostgresAuthDriver` create their tables under
  `pg_advisory_xact_lock(hashtext(...))` in a transaction: with the lock removed, eight instances opening at once fail
  `tests/.../test_postgres_real.py::test_*_opened_at_once_*` on the test Postgres (at least one of the two failed in each of 3 runs), with it
  they pass; statement order is also held in the unit tests. The four templates exclude the new modules in their
  `scripts/materialize.py` (opt-in, each brings its library): `make check` green in api, cli, tui, graph (graph's
  `test_services_startup_logs_each_verdict` flakes 4 of 6 runs on main as well). Gates in common: lint, type, arch,
  validate, `make cov` 98.9% (gate 90%), docs-build strict. Not brought: the RDF extension table of `SniffProcessor`
  (the processor and its `Format` model are findr's, common has no sniff processor), the cache row `owner` column
  (pending, not designed). Known red on main, not touched: `test_full_stack` (stack holds 45 services, the test pins 44).
