"""Fixtures: the settings the tests assemble the app from."""

import pytest

from core.settings.base import Secret
from e_mcp.config.mcp import McpSettings


@pytest.fixture
def settings() -> McpSettings:
    return McpSettings(token=Secret("t"))
