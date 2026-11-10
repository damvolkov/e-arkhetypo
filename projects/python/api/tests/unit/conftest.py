"""tests/unit/conftest: the services behind the live app, faked (`support.app`), and how the template customizes
pytest-resources.

The `resources` fixture and the lazy index come from the plugin (auto-loaded via its
pytest11 entry point): a project adds two bindings through the hook, e-serde as the official codec table, and any extra
canonical loader the table lacks.
"""

import csv
import io

from pytest_resources import FileType, eserde_loaders
from pytest_resources.hooks import Register  # noqa: TC002 — at run time: pluggy resolves the hook's annotations

from support.app import keys, psqlpy, redis_server

__all__ = ["keys", "psqlpy", "redis_server"]


def pytest_resource_loaders(register: Register) -> None:
    """Make e-serde the project's loader, then add a canonical CSV binding on top."""
    register(eserde_loaders())
    register({FileType.CSV: lambda raw: list(csv.DictReader(io.StringIO(raw.decode())))})
