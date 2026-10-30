"""tests/unit/e_infra/infra/config: AgentSettings — every provider's key and base under its standard names."""

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from e_infra.infra.config.agent import PROVIDERS, AgentSettings
from e_infra.infra.settings import settings as st

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No provider variable from the host leaks in: the machine running tests may hold real credentials."""
    names = {name for keys, bases in PROVIDERS.values() for name in (*keys, *bases)}
    for name in names | {"AGENT_HIGH", "AGENT_MEDIUM", "AGENT_LOW", "AGENT_RETRIES", "AGENT_TIMEOUT"}:
        monkeypatch.delenv(name, raising=False)
    ### and no .env from the working directory either.
    monkeypatch.chdir(tmp_path)


def test_every_provider_has_a_base_and_keyed_ones_a_key() -> None:
    fields = set(AgentSettings.model_fields)
    assert {f"{name}_api_base" for name in PROVIDERS} <= fields
    assert {f"{name}_api_key" for name, (keys, _) in PROVIDERS.items() if keys} <= fields
    assert "vertexai_api_key" not in fields


def test_everything_defaults_to_none_and_the_knobs_to_sane_values() -> None:
    agent = AgentSettings()
    assert all(
        getattr(agent, field) is None for field in AgentSettings.model_fields if field.endswith(("_key", "_base"))
    )
    assert (agent.medium, agent.retries, agent.timeout) == (None, 2, timedelta(seconds=60))


def test_standard_names_feed_the_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.test/v1")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    agent = AgentSettings()
    ### compared, never printed: a failing assert must not echo a credential.
    assert agent.openai_api_key.get_secret_value() == "sk-test", "OPENAI_API_KEY not read"
    assert agent.openai_api_base == "https://gateway.test/v1"
    assert agent.gemini_api_key.get_secret_value() == "g-test", "GOOGLE_API_KEY not read"
    assert agent.ollama_api_base == "http://ollama:11434"
    assert "sk-test" not in repr(agent)


def test_tiers_read_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HIGH", '{"provider": "anthropic", "model": "claude-sonnet-4-5"}')
    tier = AgentSettings().high
    assert (tier.provider, tier.model, tier.api_base, tier.api_key, tier.options) == (
        "anthropic",
        "claude-sonnet-4-5",
        None,
        None,
        {},
    )


def test_tiers_read_field_by_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_LOW__PROVIDER", "vllm")
    monkeypatch.setenv("AGENT_LOW__MODEL", "qwen3.6-27b")
    monkeypatch.setenv("AGENT_LOW__API_BASE", "http://localhost:45100/v1")
    monkeypatch.setenv("AGENT_LOW__API_KEY", "k-tier")
    monkeypatch.setenv("AGENT_LOW__OPTIONS", '{"region": "eu"}')
    tier = AgentSettings().low
    assert (tier.provider, tier.model, tier.api_base, tier.options) == (
        "vllm",
        "qwen3.6-27b",
        "http://localhost:45100/v1",
        {"region": "eu"},
    )
    assert tier.api_key.get_secret_value() == "k-tier", "tier key not read"
    assert "k-tier" not in repr(tier)


@pytest.mark.parametrize(
    "declared",
    [
        {"provider": "nobody", "model": "m"},
        {"provider": "vllm"},
        {"provider": "vllm", "model": ""},
        {"provider": "vllm", "model": "m", "typo": 1},
    ],
)
def test_tier_declared_wrong_fails_at_load(declared: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentSettings(medium=declared)


def test_retries_never_negative() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(retries=-1)


def test_composite_exposes_the_agent_scope() -> None:
    assert st.agent.retries >= 0
