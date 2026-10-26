"""tests/unit: logic.models — provider parity with any-llm and core, the masked endpoint, usage arithmetic."""

from any_llm import LLMProvider

from e_graph.logic.models import LOCAL, STRICT, Endpoint, Provider, Usage
from infra.settings.agent import PROVIDERS


def test_provider_mirrors_any_llm_plus_custom() -> None:
    assert {provider.value for provider in Provider} == {provider.value for provider in LLMProvider} | {"custom"}


def test_provider_has_its_settings_row() -> None:
    assert set(PROVIDERS) == {provider.value for provider in Provider}


def test_local_and_strict_are_providers() -> None:
    assert Provider.CUSTOM in LOCAL
    assert LOCAL.isdisjoint(STRICT)


def test_endpoint_repr_masks_the_key() -> None:
    shown = repr(Endpoint(provider=Provider.OPENAI, model="m", api_key="sk-live"))
    assert "sk-live" not in shown
    assert "api_key='***'" in shown
    assert "api_key=''" in repr(Endpoint(provider=Provider.VLLM, model="m"))


def test_usage_adds_field_by_field() -> None:
    one = Usage(input_tokens=1, output_tokens=2, total_tokens=3, calls=1)
    assert one + one == Usage(input_tokens=2, output_tokens=4, total_tokens=6, calls=2)
    assert Usage() + one == one
