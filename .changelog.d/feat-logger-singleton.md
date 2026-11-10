- common's gates gain `logger-singleton` (law 16): `get_logger()` only inside `infra/logger.py`, every other module
  imports the one `logger` — a call-site logger escapes the setup, its redact stage and its tracer hook. From the
  reverse-distill of aivo-agents feat/canon (should, upheld). Evidence: the rule's cases pass `gates.engine test`;
  common has zero hits today.
