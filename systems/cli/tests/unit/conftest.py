"""tests/unit/conftest: how the template customizes the pytest-resources plugin.

The `resources` fixture and the lazy index come from the plugin (auto-loaded via its pytest11
entry point). A project adds two bindings through the hook: e-serde as the official codec
table, and any extra canonical loader the table lacks.
"""

import csv
import io

from pytest_resources import FileType, eserde_loaders


def pytest_resource_loaders(register) -> None:
    """Make e-serde the project's loader, then add a canonical CSV binding on top."""
    register(eserde_loaders())
    register({FileType.CSV: lambda raw: list(csv.DictReader(io.StringIO(raw.decode())))})
