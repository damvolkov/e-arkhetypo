"""Fixtures: the settings the tests assemble the app from."""

import pytest

from e_mcp.config.mcp import McpSettings
from infra.config.base import Secret


@pytest.fixture
def settings() -> McpSettings:
    return McpSettings(token=Secret("t"))
