"""Fixtures: the settings the tests assemble the app from."""

import pytest

from e_mcp.config.mcp import McpSettings
from infra.settings.base import Secret


@pytest.fixture
def settings() -> McpSettings:
    return McpSettings(token=Secret("t"))
