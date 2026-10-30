"""infra/config/llm: a chat model answering under a JSON schema — an OpenAI-compatible server (LLM_*)."""

from datetime import timedelta
from typing import Any

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


class LlmSettings(BaseSettings):
    """LLM_URL — OpenAI-compatible base (`/v1`); LLM_MODEL — served name; LLM_KEY — bearer, unset for a server without
    one; LLM_CONCURRENCY — calls in flight; LLM_RPM — calls a minute; LLM_MAX_TOKENS — one answer's ceiling;
    LLM_TIMEOUT — one call; LLM_EXTRA — a provider's own body fields, as JSON (`{"enable_thinking": false}`), merged
    into every chat-completions request."""

    model_config = SettingsConfigDict(env_prefix="LLM_")

    url: str = "http://127.0.0.1:45100/v1"
    model: str = "local-model"
    key: Secret | None = None
    concurrency: int = Field(default=8, ge=1)
    rpm: int = Field(default=120, ge=1)
    max_tokens: int = Field(default=4096, ge=16)
    timeout: timedelta = timedelta(seconds=120)
    extra: dict[str, Any] = Field(default_factory=dict)
