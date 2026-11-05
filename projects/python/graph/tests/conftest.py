"""tests/conftest: the environment every tier runs in, seeded before `infra.settings` is ever imported.

`settings = Settings()` reads the environment when `infra.settings` is first imported, and pytest imports this module
before any test module or lower conftest — so the seed runs here, at import, and this module imports nothing of the
app. External env wins; a process that inherited another's seed (an xdist worker) takes a private DB_PATH and docling
port of its own."""

import os
import socket
import tempfile
from pathlib import Path
from typing import Final

### who seeded this environment: a worker that inherited its controller's seed re-seeds the per-process values.
SEEDER: Final[str] = "E_TESTS_SEEDER"


def seed() -> None:
    """The secret, a test queue database, a private DB_PATH and a docling port of the test run's own."""
    own = str(os.getpid())
    inherited = os.environ.get(SEEDER, own) != own
    ### the db lifespan provisions the queue database on the local ParadeDB: a test one, never the service's.
    os.environ.setdefault("QUEUE_DSN", "postgresql://postgres:postgres@127.0.0.1:45011/e_graph_test_background")
    os.environ.setdefault("CRYPTO__SECRET", "unit-test-secret-0123456789")
    fresh = inherited or "DB_PATH" not in os.environ
    os.environ["DB_PATH"] = (
        str(Path(tempfile.mkdtemp(prefix="e-graph-tests-")) / "test.db") if fresh else os.environ["DB_PATH"]
    )
    ### docling-serve is a local HTTP server in the test run, on a free port of its own — never the stack's.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        os.environ["DOCLING_URL"] = f"http://127.0.0.1:{probe.getsockname()[1]}"
    os.environ[SEEDER] = own


seed()
