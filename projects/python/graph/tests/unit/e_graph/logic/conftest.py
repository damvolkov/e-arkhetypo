"""tests/unit/e_graph/logic: agent settings built in a clean room — the host's provider keys never reach a test."""

from typing import TYPE_CHECKING, Any

import pytest

from infra.config.agent import PROVIDERS
from support.crafter import SpecCrafter
from support.root import agent_args

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_resources import Resources

### every variable AgentSettings reads besides the providers' own.
AGENT_VARS: tuple[str, ...] = ("AGENT_HIGH", "AGENT_MEDIUM", "AGENT_LOW", "AGENT_RETRIES", "AGENT_TIMEOUT")


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No provider or agent variable from the host, no `.env` in reach."""
    names = {name for keys, bases in PROVIDERS.values() for name in (*keys, *bases)} | set(AGENT_VARS)
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def settings(clean: None) -> Callable[..., dict[str, Any]]:
    """The agent's keyword arguments from explicit values only."""
    return agent_args


@pytest.fixture(params=[3, 17, 41], ids=lambda seed: f"seed{seed}")
def crafter(resources: Resources, tmp_path: Path, request: pytest.FixtureRequest) -> SpecCrafter:
    """A spec crafter over a fresh tree, at one of several seeds: each test meets several random pipelines."""
    return SpecCrafter(resources, tmp_path, seed=request.param)
