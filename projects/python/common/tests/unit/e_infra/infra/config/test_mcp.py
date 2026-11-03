"""tests/unit/e_infra/infra/config/mcp: McpSettings — where the endpoint answers and which Host and Origin it accepts."""

from typing import TYPE_CHECKING

from e_infra.infra.config.mcp import McpSettings

if TYPE_CHECKING:
    import pytest


def test_mcp_defaults() -> None:
    assert (McpSettings().path, McpSettings().hosts, McpSettings().origins) == ("/mcp", [], [])


def test_mcp_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_PATH", "/agents")
    monkeypatch.setenv("MCP_HOSTS", '["api.example.org"]')
    monkeypatch.setenv("MCP_ORIGINS", '["https://api.example.org"]')
    conf = McpSettings()
    assert (conf.path, conf.hosts, conf.origins) == ("/agents", ["api.example.org"], ["https://api.example.org"])
