"""tests/unit/conftest: how the template customizes the pytest-resources plugin.

The `resources` fixture and the lazy index come from the plugin (auto-loaded via its pytest11
entry point). A project adds two bindings through the hook: e-serde as the official codec
table, and any extra canonical loader the table lacks. And the one provider every document read needs.
"""

import csv
import io
from typing import TYPE_CHECKING

import pytest
from pytest_resources import FileType, eserde_loaders

from providers.adapters.liteparse import LiteparseAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def pytest_resource_loaders(register) -> None:
    """Make e-serde the project's loader, then add a canonical CSV binding on top."""
    register(eserde_loaders())
    register({FileType.CSV: lambda raw: list(csv.DictReader(io.StringIO(raw.decode())))})


@pytest.fixture(scope="session")
async def pages() -> AsyncIterator[LiteparseAdapter]:
    """The in-process fast pass the DocProcessor reads every page with, opened once per worker."""
    async with LiteparseAdapter() as adapter:
        yield adapter
