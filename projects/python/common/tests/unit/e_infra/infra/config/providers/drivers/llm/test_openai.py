"""tests/unit/e_infra/infra/config/providers/drivers/llm/openai: OpenaiSettings — an OpenAI-compatible server, its gates and its extras."""

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.llm.openai import OpenaiSettings


def test_llm_default_has_no_key() -> None:
    assert (OpenaiSettings().key, OpenaiSettings().concurrency, OpenaiSettings().extra) == (None, 8, {})


def test_llm_env_carries_the_key_and_json_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_KEY", "secret")
    monkeypatch.setenv("LLM_EXTRA", '{"enable_thinking": false}')
    conf = OpenaiSettings()
    assert (conf.key.get_secret_value() if conf.key else None, conf.extra) == ("secret", {"enable_thinking": False})
    assert "secret" not in repr(conf)


def test_llm_max_tokens_has_a_floor() -> None:
    with pytest.raises(ValidationError):
        OpenaiSettings(max_tokens=1)
