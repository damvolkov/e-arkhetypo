"""tests/integration/e_graph: the agent against a real model — recorded once, replayed offline.

The MEDIUM tier defaults to the local vLLM; AGENT_MEDIUM__* point it anywhere else when recording. Cassettes
never hold a credential: every auth header is redacted before a request is written."""

import os
from typing import Any, Final

import pytest

from core.settings.agent import AgentSettings
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.models import Endpoint, Provider, Tier

VLLM: Final[Endpoint] = Endpoint(provider=Provider.VLLM, model="gemma4-26b-a4b", api_base="http://localhost:45100/v1")
SECRET_HEADERS: Final[tuple[str, ...]] = ("authorization", "api-key", "x-api-key", "x-goog-api-key", "cookie")


def pytest_configure() -> None:
    """The cassette records the model and nothing else: the exporter stays mute whatever `.env` points it at."""
    os.environ["OTEL_ENDPOINT"] = ""


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """Body in the match: a section issues several calls to one endpoint at once, and order is not guaranteed.

    `decode_compressed_response` keeps bodies readable; without it a replay would compare the same bytes
    as text, since both sides share the transport. The model is deterministic by seed and temperature 0
    at the server, so a replayed body is byte-for-byte the recorded one."""
    return {
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"],
        "filter_headers": [(name, "REDACTED") for name in SECRET_HEADERS],
        "filter_query_parameters": [("key", "REDACTED"), ("api_key", "REDACTED")],
        "decode_compressed_response": True,
    }


@pytest.fixture
def settings() -> Any:
    """The agent's settings from the environment, the MEDIUM tier pointed at the local vLLM unless declared."""
    declared = AgentSettings()
    match declared.agent_medium:
        case None:
            local = {"provider": VLLM.provider, "model": VLLM.model, "api_base": VLLM.api_base}
            return AgentSettings(agent_medium=local)
        case _:
            return declared


@pytest.fixture
def endpoint() -> Tier:
    """The MEDIUM tier: the local vLLM unless AGENT_MEDIUM__* declare another."""
    return Tier.MEDIUM


@pytest.fixture
async def agent(settings: Any) -> Any:
    async with AgnosticAgent(settings) as live:
        yield live
