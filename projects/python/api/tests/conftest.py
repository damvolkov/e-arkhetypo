"""tests/conftest: the environment every tier runs in, seeded before `infra.settings` is ever imported.

`settings = Settings()` reads the environment when `infra.settings` is first imported, so this module imports nothing of
the app: `os.environ` stays untouched at module import (doctrine: no side-effect between imports), the seeding rides
`pytest_configure`, which pytest runs before collection — before any test module or lower conftest imports the app. The
fakes behind the live app live one level down, in `tests/unit/conftest.py`."""

import os
import tempfile
from pathlib import Path

import pytest  # noqa: TC002 — pytest evaluates the hook's annotations at runtime


def pytest_configure(config: pytest.Config) -> None:
    """Seed the secrets and a private DB_PATH before any collection-time settings touch; external env wins."""
    ### the xdist controller collects nothing, and what it exports its workers would all share: only a process that runs
    ### tests seeds its own file.
    if config.getoption("dist", "no") != "no" and not hasattr(config, "workerinput"):
        return
    os.environ.setdefault("CRYPTO__SECRET", "unit-test-secret-0123456789")
    os.environ.setdefault("AUTH_SECRET", "unit-test-auth-secret-0123456789")
    os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp(prefix="e-api-tests-")) / "test.db"))
