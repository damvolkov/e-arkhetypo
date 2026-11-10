"""infra/config/agent: the agnostic agent's edge — per-provider key and base, tier endpoints, retries, timeout.

Every provider the agent can reach has an optional key and an optional base, each under the provider's own standard
variable name (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY or GOOGLE_API_KEY, OLLAMA_HOST,
AWS_BEARER_TOKEN_BEDROCK...), the very names any-llm and the official SDKs use; where a provider declares none, the
`<PROVIDER>_API_KEY` / `<PROVIDER>_API_BASE` convention stands. A provider with two names for one value has two fields:
`PROVIDERS` lists them first-wins, and the composition root takes the first that is set. All default to None: there is
no contract until a call names a provider, so a missing credential is caught by the agent at run time, never at boot.
Providers that authenticate through their cloud's own chain (Vertex AI via ADC, SageMaker via AWS credentials) carry a
base only. `CUSTOM` is any OpenAI-compatible endpoint. A base is handed to the SDK as written (`OLLAMA_HOST` is a
`host:port`, not always a URL): a string.

Tiers (AGENT_HIGH / AGENT_MEDIUM / AGENT_LOW) are typed values, one `AgentTier` each, set field by field
(`AGENT_HIGH__PROVIDER=vllm`, `AGENT_HIGH__MODEL=qwen3.6-27b`, `AGENT_HIGH__API_BASE=...`) or whole as JSON; a tier
declared is validated at load — a provider outside the table or a missing model fails the boot, while a tier left
unset fails only the call that asks for it."""

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, SecretStr

from e_infra.infra.config.base import BaseSettings
from e_infra.infra.payload import JSON

type EnvNames = tuple[str, ...]

### provider → (key variables, base variables), first name wins; read 2026-10-13 from any-llm-sdk 1.30 (its
### ENV_API_KEY_NAME / ENV_API_BASE_NAME), the convention where it declares none; `()` = no key, cloud credentials.
PROVIDERS: Final[MappingProxyType[str, tuple[EnvNames, EnvNames]]] = MappingProxyType(
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


##### TYPES #####
class AgentTier(BaseModel):
    """One agent tier: the endpoint a capability class resolves to; base and key fall back to the provider's own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal[tuple(PROVIDERS)]  # ty: ignore[invalid-type-form] — the table is the closed set
    model: str = Field(min_length=1)
    api_base: str | None = None
    api_key: SecretStr | None = None
    options: Mapping[str, JSON] = Field(default_factory=dict)


##### SETTINGS #####
class AgentSettings(BaseSettings):
    """The agent's own knobs, then every provider's key and base."""

    ### AGENT
    AGENT_TIMEOUT: timedelta = timedelta(seconds=60)
    ### bounds the validation retries.
    AGENT_RETRIES: NonNegativeInt = 2
    AGENT_HIGH: AgentTier | None = None
    AGENT_MEDIUM: AgentTier | None = None
    AGENT_LOW: AgentTier | None = None

    ### ANTHROPIC
    ANTHROPIC_API_KEY: SecretStr | None = None
    ANTHROPIC_BASE_URL: str | None = None

    ### BEDROCK
    AWS_BEARER_TOKEN_BEDROCK: SecretStr | None = None
    AWS_ENDPOINT_URL_BEDROCK_RUNTIME: str | None = None

    ### AZURE
    AZURE_API_KEY: SecretStr | None = None
    AZURE_AI_CHAT_ENDPOINT: str | None = None

    ### AZUREANTHROPIC
    AZURE_ANTHROPIC_API_KEY: SecretStr | None = None
    AZURE_ANTHROPIC_API_BASE: str | None = None

    ### AZUREOPENAI
    AZURE_OPENAI_API_KEY: SecretStr | None = None
    AZURE_OPENAI_ENDPOINT: str | None = None

    ### ATLASCLOUD
    ATLASCLOUD_API_KEY: SecretStr | None = None
    ATLASCLOUD_API_BASE: str | None = None

    ### CASCADIA
    CASCADIA_API_KEY: SecretStr | None = None
    CASCADIA_API_BASE: str | None = None

    ### CEREBRAS
    CEREBRAS_API_KEY: SecretStr | None = None
    CEREBRAS_API_BASE: str | None = None

    ### COHERE
    COHERE_API_KEY: SecretStr | None = None
    COHERE_BASE_URL: str | None = None

    ### DATABRICKS
    DATABRICKS_TOKEN: SecretStr | None = None
    DATABRICKS_API_KEY: SecretStr | None = None
    DATABRICKS_HOST: str | None = None
    DATABRICKS_API_BASE: str | None = None

    ### DEEPSEEK
    DEEPSEEK_API_KEY: SecretStr | None = None
    DEEPSEEK_API_BASE: str | None = None

    ### FIREWORKS
    FIREWORKS_API_KEY: SecretStr | None = None
    FIREWORKS_API_BASE: str | None = None

    ### GEMINI
    GEMINI_API_KEY: SecretStr | None = None
    GOOGLE_API_KEY: SecretStr | None = None
    GOOGLE_GEMINI_BASE_URL: str | None = None

    ### GITHUB
    GITHUB_TOKEN: SecretStr | None = None
    GITHUB_MODELS_API_BASE: str | None = None

    ### GMI
    GMI_API_KEY: SecretStr | None = None
    GMI_API_BASE: str | None = None

    ### GROQ
    GROQ_API_KEY: SecretStr | None = None
    GROQ_BASE_URL: str | None = None

    ### HUGGINGFACE
    HF_TOKEN: SecretStr | None = None
    HUGGINGFACE_API_BASE: str | None = None

    ### INCEPTION
    INCEPTION_API_KEY: SecretStr | None = None
    INCEPTION_API_BASE: str | None = None

    ### KENARI
    KENARI_API_KEY: SecretStr | None = None
    KENARI_API_BASE: str | None = None

    ### LLAMA
    LLAMA_API_KEY: SecretStr | None = None
    LLAMA_API_BASE: str | None = None

    ### LMSTUDIO
    LM_STUDIO_API_KEY: SecretStr | None = None
    LM_STUDIO_API_BASE: str | None = None

    ### LLAMAFILE
    LLAMAFILE_API_KEY: SecretStr | None = None
    LLAMAFILE_API_BASE: str | None = None

    ### LLAMACPP
    LLAMACPP_API_KEY: SecretStr | None = None
    LLAMACPP_API_BASE: str | None = None

    ### META
    MODEL_API_KEY: SecretStr | None = None
    META_API_BASE: str | None = None

    ### MISTRAL
    MISTRAL_API_KEY: SecretStr | None = None
    MISTRAL_API_BASE: str | None = None

    ### MOONSHOT
    MOONSHOT_API_KEY: SecretStr | None = None
    MOONSHOT_API_BASE: str | None = None

    ### MZAI
    MZAI_API_KEY: SecretStr | None = None
    MZAI_API_BASE: str | None = None

    ### NEOSANTARA
    NEOSANTARA_API_KEY: SecretStr | None = None
    NEOSANTARA_API_BASE: str | None = None

    ### NEBIUS
    NEBIUS_API_KEY: SecretStr | None = None
    NEBIUS_API_BASE: str | None = None

    ### OLLAMA
    OLLAMA_API_KEY: SecretStr | None = None
    OLLAMA_HOST: str | None = None

    ### OPENAI
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_API_BASE: str | None = None

    ### OTARI
    OTARI_API_KEY: SecretStr | None = None
    OTARI_API_BASE: str | None = None

    ### OPENROUTER
    OPENROUTER_API_KEY: SecretStr | None = None
    OPENROUTER_API_BASE: str | None = None

    ### PORTKEY
    PORTKEY_API_KEY: SecretStr | None = None
    PORTKEY_API_BASE: str | None = None

    ### QINIU
    QINIU_API_KEY: SecretStr | None = None
    QINIU_API_BASE: str | None = None

    ### REQUESTY
    REQUESTY_API_KEY: SecretStr | None = None
    REQUESTY_API_BASE: str | None = None

    ### SAMBANOVA
    SAMBANOVA_API_KEY: SecretStr | None = None
    SAMBANOVA_API_BASE: str | None = None

    ### SAGEMAKER
    SAGEMAKER_ENDPOINT_URL: str | None = None

    ### TOGETHER
    TOGETHER_API_KEY: SecretStr | None = None
    TOGETHER_API_BASE: str | None = None

    ### VERTEXAI
    VERTEXAI_API_BASE: str | None = None

    ### VERTEXAIANTHROPIC
    VERTEXAI_ANTHROPIC_API_BASE: str | None = None

    ### VLLM
    VLLM_API_KEY: SecretStr | None = None
    VLLM_API_BASE: str | None = None

    ### VOYAGE
    VOYAGE_API_KEY: SecretStr | None = None
    VOYAGE_API_BASE: str | None = None

    ### WATSONX
    WATSONX_API_KEY: SecretStr | None = None
    WATSONX_URL: str | None = None

    ### XAI
    XAI_API_KEY: SecretStr | None = None
    XAI_API_BASE: str | None = None

    ### PERPLEXITY
    PERPLEXITY_API_KEY: SecretStr | None = None
    PERPLEXITY_API_BASE: str | None = None

    ### MINIMAX
    MINIMAX_API_KEY: SecretStr | None = None
    MINIMAX_API_BASE: str | None = None

    ### DASHSCOPE
    DASHSCOPE_API_KEY: SecretStr | None = None
    DASHSCOPE_API_BASE: str | None = None

    ### DEEPINFRA
    DEEPINFRA_API_KEY: SecretStr | None = None
    DEEPINFRA_API_BASE: str | None = None

    ### EDENAI
    EDENAI_API_KEY: SecretStr | None = None
    EDENAI_API_BASE: str | None = None

    ### ZAI
    ZAI_API_KEY: SecretStr | None = None
    ZAI_BASE_URL: str | None = None

    ### TELNYX
    TELNYX_API_KEY: SecretStr | None = None
    TELNYX_API_BASE: str | None = None

    ### CUSTOM
    CUSTOM_API_KEY: SecretStr | None = None
    CUSTOM_API_BASE: str | None = None

    ##### VIEWS — what the root hands the agent #####

    def agent_credentials(self) -> Mapping[str, tuple[SecretStr | None, str | None]]:
        """Every provider's key and base, each the first of its variables that is set."""
        return MappingProxyType(
            {
                provider: (
                    next((value for name in keys if (value := getattr(self, name)) is not None), None),
                    next((value for name in bases if (value := getattr(self, name)) is not None), None),
                )
                for provider, (keys, bases) in PROVIDERS.items()
            }
        )

    def agent_tiers(self) -> Mapping[str, AgentTier | None]:
        """The declared tiers by name — `high`, `medium`, `low` — each unset as None."""
        return MappingProxyType({"high": self.AGENT_HIGH, "medium": self.AGENT_MEDIUM, "low": self.AGENT_LOW})
