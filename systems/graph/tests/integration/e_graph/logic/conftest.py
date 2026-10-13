"""tests/integration/e_graph/logic: the agent against a real model — recorded once, replayed offline.

The endpoint defaults to the local vLLM; AGENT_MEDIUM points it anywhere else when recording. Cassettes
never hold a credential: every auth header is redacted before a request is written."""

from typing import Any, Final

import pytest

from core.settings.agent import AgentSettings
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.models import Endpoint, Provider, Tier

VLLM: Final[Endpoint] = Endpoint(provider=Provider.VLLM, model="qwen3.6-27b", api_base="http://localhost:45100/v1")
SECRET_HEADERS: Final[tuple[str, ...]] = ("authorization", "api-key", "x-api-key", "x-goog-api-key", "cookie")


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    return {
        "filter_headers": [(name, "REDACTED") for name in SECRET_HEADERS],
        "filter_query_parameters": [("key", "REDACTED"), ("api_key", "REDACTED")],
        "decode_compressed_response": True,
    }


@pytest.fixture
def settings() -> Any:
    return AgentSettings()


@pytest.fixture
def endpoint(settings: Any) -> Endpoint | Tier:
    """The MEDIUM tier when its sub-settings declare one, else the local vLLM."""
    return VLLM if settings.agent_medium is None else Tier.MEDIUM


@pytest.fixture
async def agent(settings: Any) -> Any:
    async with AgnosticAgent(settings) as live:
        yield live
