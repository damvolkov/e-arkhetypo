"""infra/settings/agent: the agnostic agent's edge — per-provider key and base, tier endpoints, retries, timeout.

Every provider the agent can reach has two optional settings, `<provider>_api_key` and
`<provider>_api_base`, read under the provider's own standard variable names (OPENAI_API_KEY,
ANTHROPIC_API_KEY, GEMINI_API_KEY or GOOGLE_API_KEY, OLLAMA_HOST, AWS_BEARER_TOKEN_BEDROCK...), the very
names any-llm and the official SDKs use; where a provider declares none, the `<PROVIDER>_API_KEY` /
`<PROVIDER>_API_BASE` convention stands. All default to None: there is no contract until a call names a
provider, so a missing credential is caught by the agent at run time, never at boot. Providers that
authenticate through their cloud's own chain (Vertex AI via ADC, SageMaker via AWS credentials) carry a
base only. `CUSTOM` is any OpenAI-compatible endpoint.

Tiers (AGENT_HIGH / AGENT_MEDIUM / AGENT_LOW) are typed sub-settings, one `TierSettings` each, set field by
field (`AGENT_HIGH__PROVIDER=vllm`, `AGENT_HIGH__MODEL=qwen3.6-27b`, `AGENT_HIGH__API_BASE=...`) or whole as
JSON; a tier declared is validated at load — a provider outside the table or a missing model fails the
boot, while a tier left unset fails only the call that asks for it. AGENT_RETRIES bounds the validation
retries, AGENT_TIMEOUT each provider call."""

from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, create_model

from infra.settings.base import BaseSettings, Secret

if TYPE_CHECKING:
    from collections.abc import Mapping

type EnvNames = tuple[str, ...]

### provider → (key variables, base variables), first name wins; read 2026-10-13 from any-llm-sdk 1.30 (its
### ENV_API_KEY_NAME / ENV_API_BASE_NAME), the convention where it declares none; `()` = no key, cloud credentials.
PROVIDERS: Final[Mapping[str, tuple[EnvNames, EnvNames]]] = MappingProxyType(
    {
        "anthropic": (("ANTHROPIC_API_KEY",), ("ANTHROPIC_BASE_URL",)),
        "bedrock": (("AWS_BEARER_TOKEN_BEDROCK",), ("AWS_ENDPOINT_URL_BEDROCK_RUNTIME",)),
        "azure": (("AZURE_API_KEY",), ("AZURE_AI_CHAT_ENDPOINT",)),
        "azureanthropic": (("AZURE_ANTHROPIC_API_KEY",), ("AZURE_ANTHROPIC_API_BASE",)),
        "azureopenai": (("AZURE_OPENAI_API_KEY",), ("AZURE_OPENAI_ENDPOINT",)),
        "atlascloud": (("ATLASCLOUD_API_KEY",), ("ATLASCLOUD_API_BASE",)),
        "cascadia": (("CASCADIA_API_KEY",), ("CASCADIA_API_BASE",)),
        "cerebras": (("CEREBRAS_API_KEY",), ("CEREBRAS_API_BASE",)),
        "cohere": (("COHERE_API_KEY",), ("COHERE_BASE_URL",)),
        "databricks": (("DATABRICKS_TOKEN", "DATABRICKS_API_KEY"), ("DATABRICKS_HOST", "DATABRICKS_API_BASE")),
        "deepseek": (("DEEPSEEK_API_KEY",), ("DEEPSEEK_API_BASE",)),
        "fireworks": (("FIREWORKS_API_KEY",), ("FIREWORKS_API_BASE",)),
        "gemini": (("GEMINI_API_KEY", "GOOGLE_API_KEY"), ("GOOGLE_GEMINI_BASE_URL",)),
        "github": (("GITHUB_TOKEN",), ("GITHUB_MODELS_API_BASE",)),
        "gmi": (("GMI_API_KEY",), ("GMI_API_BASE",)),
        "groq": (("GROQ_API_KEY",), ("GROQ_BASE_URL",)),
        "huggingface": (("HF_TOKEN",), ("HUGGINGFACE_API_BASE",)),
        "inception": (("INCEPTION_API_KEY",), ("INCEPTION_API_BASE",)),
        "kenari": (("KENARI_API_KEY",), ("KENARI_API_BASE",)),
        "llama": (("LLAMA_API_KEY",), ("LLAMA_API_BASE",)),
        "lmstudio": (("LM_STUDIO_API_KEY",), ("LM_STUDIO_API_BASE",)),
        "llamafile": (("LLAMAFILE_API_KEY",), ("LLAMAFILE_API_BASE",)),
        "llamacpp": (("LLAMACPP_API_KEY",), ("LLAMACPP_API_BASE",)),
        "meta": (("MODEL_API_KEY",), ("META_API_BASE",)),
        "mistral": (("MISTRAL_API_KEY",), ("MISTRAL_API_BASE",)),
        "moonshot": (("MOONSHOT_API_KEY",), ("MOONSHOT_API_BASE",)),
        "mzai": (("MZAI_API_KEY",), ("MZAI_API_BASE",)),
        "neosantara": (("NEOSANTARA_API_KEY",), ("NEOSANTARA_API_BASE",)),
        "nebius": (("NEBIUS_API_KEY",), ("NEBIUS_API_BASE",)),
        "ollama": (("OLLAMA_API_KEY",), ("OLLAMA_HOST",)),
        "openai": (("OPENAI_API_KEY",), ("OPENAI_BASE_URL", "OPENAI_API_BASE")),
        "otari": (("OTARI_API_KEY",), ("OTARI_API_BASE",)),
        "openrouter": (("OPENROUTER_API_KEY",), ("OPENROUTER_API_BASE",)),
        "portkey": (("PORTKEY_API_KEY",), ("PORTKEY_API_BASE",)),
        "qiniu": (("QINIU_API_KEY",), ("QINIU_API_BASE",)),
        "requesty": (("REQUESTY_API_KEY",), ("REQUESTY_API_BASE",)),
        "sambanova": (("SAMBANOVA_API_KEY",), ("SAMBANOVA_API_BASE",)),
        "sagemaker": ((), ("SAGEMAKER_ENDPOINT_URL",)),
        "together": (("TOGETHER_API_KEY",), ("TOGETHER_API_BASE",)),
        "vertexai": ((), ("VERTEXAI_API_BASE",)),
        "vertexaianthropic": ((), ("VERTEXAI_ANTHROPIC_API_BASE",)),
        "vllm": (("VLLM_API_KEY",), ("VLLM_API_BASE",)),
        "voyage": (("VOYAGE_API_KEY",), ("VOYAGE_API_BASE",)),
        "watsonx": (("WATSONX_API_KEY",), ("WATSONX_URL",)),
        "xai": (("XAI_API_KEY",), ("XAI_API_BASE",)),
        "perplexity": (("PERPLEXITY_API_KEY",), ("PERPLEXITY_API_BASE",)),
        "minimax": (("MINIMAX_API_KEY",), ("MINIMAX_API_BASE",)),
        "dashscope": (("DASHSCOPE_API_KEY",), ("DASHSCOPE_API_BASE",)),
        "deepinfra": (("DEEPINFRA_API_KEY",), ("DEEPINFRA_API_BASE",)),
        "edenai": (("EDENAI_API_KEY",), ("EDENAI_API_BASE",)),
        "zai": (("ZAI_API_KEY",), ("ZAI_BASE_URL",)),
        "telnyx": (("TELNYX_API_KEY",), ("TELNYX_API_BASE",)),
        "custom": (("CUSTOM_API_KEY",), ("CUSTOM_API_BASE",)),
    }
)


class TierSettings(BaseModel):
    """One agent tier: the endpoint a capability class resolves to; base and key fall back to the provider's own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal[tuple(PROVIDERS)]  # ty: ignore[invalid-type-form] — the table is the closed set
    model: str = Field(min_length=1)
    api_base: str | None = None
    api_key: Secret | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class AgentBase(BaseSettings):
    """The agent's own knobs; `AgentSettings` adds every provider's key and base on top."""

    agent_high: TierSettings | None = None
    agent_medium: TierSettings | None = None
    agent_low: TierSettings | None = None
    agent_retries: int = Field(default=2, ge=0)
    agent_timeout: timedelta = timedelta(seconds=60)


def provider_fields(table: Mapping[str, tuple[EnvNames, EnvNames]]) -> dict[str, Any]:
    """One optional key field (when the provider takes one) and one optional base field per provider."""
    keys = {
        f"{name}_api_key": (Secret | None, Field(default=None, validation_alias=AliasChoices(*names)))
        for name, (names, _) in table.items()
        if names
    }
    bases = {
        f"{name}_api_base": (str | None, Field(default=None, validation_alias=AliasChoices(*names)))
        for name, (_, names) in table.items()
    }
    return keys | bases


### built from the table, so a provider is one row; `__module__` keeps it this module's own for the composer.
AgentSettings: Any = create_model(
    "AgentSettings", __base__=AgentBase, __module__=__name__, **provider_fields(PROVIDERS)
)
