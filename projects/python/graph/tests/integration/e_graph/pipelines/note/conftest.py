"""tests/integration/e_graph/pipelines/note: the note's cassettes replay against the endpoint they were recorded on.

The shared integration conftest pins replay to the local vLLM (the filing and agent cassettes). These two
cassettes were captured against an Alibaba custom endpoint; a cassette is self-describing — the model lives
in its request body — so the pin follows the cassette, not the other way round. `make record` with the tiers
pointed at Alibaba rewrites them together."""

from typing import Any, Final

import pytest

from core.settings.agent import AgentSettings

### the endpoint these cassettes were recorded against; the key never lands here — CUSTOM is a local-server
### provider and the agent supplies a dummy, while the header is redacted before the request is written.
ALIBABA: Final = {"provider": "custom", "model": "qwen3.8-flash", "api_base": "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"}  # fmt: skip


@pytest.fixture
def settings(request: pytest.FixtureRequest) -> Any:
    """Every tier pinned to the recorded endpoint; only the recorders may retarget from the environment."""
    recording = str(request.config.getoption("--record-mode", "none")).lower() in {"all", "rewrite", "new_episodes"}
    match recording:
        case True:
            return AgentSettings()
        case _:
            return AgentSettings(agent_medium=ALIBABA, agent_high=ALIBABA, agent_low=ALIBABA)
