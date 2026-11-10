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
from enum import StrEnum, auto
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, SecretStr

from e_infra.infra.config.base import BaseSettings
from e_infra.infra.payload import JSON

type EnvNames = tuple[str, ...]


class Provider(StrEnum):
    """Every provider the agent can reach, by the name any-llm gives it."""

    ANTHROPIC = auto()
    BEDROCK = auto()
    AZURE = auto()
    AZUREANTHROPIC = auto()
    AZUREOPENAI = auto()
    ATLASCLOUD = auto()
    CASCADIA = auto()
    CEREBRAS = auto()
    COHERE = auto()
    DATABRICKS = auto()
    DEEPSEEK = auto()
    FIREWORKS = auto()
    GEMINI = auto()
    GITHUB = auto()
    GMI = auto()
    GROQ = auto()
    HUGGINGFACE = auto()
    INCEPTION = auto()
    KENARI = auto()
    LLAMA = auto()
    LMSTUDIO = auto()
    LLAMAFILE = auto()
    LLAMACPP = auto()
    META = auto()
    MISTRAL = auto()
    MOONSHOT = auto()
    MZAI = auto()
    NEOSANTARA = auto()
    NEBIUS = auto()
    OLLAMA = auto()
    OPENAI = auto()
    OTARI = auto()
    OPENROUTER = auto()
    PORTKEY = auto()
    QINIU = auto()
    REQUESTY = auto()
    SAMBANOVA = auto()
    SAGEMAKER = auto()
    TOGETHER = auto()
    VERTEXAI = auto()
    VERTEXAIANTHROPIC = auto()
    VLLM = auto()
    VOYAGE = auto()
    WATSONX = auto()
    XAI = auto()
    PERPLEXITY = auto()
    MINIMAX = auto()
    DASHSCOPE = auto()
    DEEPINFRA = auto()
    EDENAI = auto()
    ZAI = auto()
    TELNYX = auto()
    CUSTOM = auto()


### provider → (key variables, base variables), first name wins; read 2026-10-13 from any-llm-sdk 1.30 (its
### ENV_API_KEY_NAME / ENV_API_BASE_NAME), the convention where it declares none; `()` = no key, cloud credentials.
PROVIDERS: Final[MappingProxyType[Provider, tuple[EnvNames, EnvNames]]] = MappingProxyType(
    {
        Provider.ANTHROPIC: (("ANTHROPIC_API_KEY",), ("ANTHROPIC_BASE_URL",)),
        Provider.BEDROCK: (("AWS_BEARER_TOKEN_BEDROCK",), ("AWS_ENDPOINT_URL_BEDROCK_RUNTIME",)),
        Provider.AZURE: (("AZURE_API_KEY",), ("AZURE_AI_CHAT_ENDPOINT",)),
        Provider.AZUREANTHROPIC: (("AZURE_ANTHROPIC_API_KEY",), ("AZURE_ANTHROPIC_API_BASE",)),
        Provider.AZUREOPENAI: (("AZURE_OPENAI_API_KEY",), ("AZURE_OPENAI_ENDPOINT",)),
        Provider.ATLASCLOUD: (("ATLASCLOUD_API_KEY",), ("ATLASCLOUD_API_BASE",)),
        Provider.CASCADIA: (("CASCADIA_API_KEY",), ("CASCADIA_API_BASE",)),
        Provider.CEREBRAS: (("CEREBRAS_API_KEY",), ("CEREBRAS_API_BASE",)),
        Provider.COHERE: (("COHERE_API_KEY",), ("COHERE_BASE_URL",)),
        Provider.DATABRICKS: (("DATABRICKS_TOKEN", "DATABRICKS_API_KEY"), ("DATABRICKS_HOST", "DATABRICKS_API_BASE")),
        Provider.DEEPSEEK: (("DEEPSEEK_API_KEY",), ("DEEPSEEK_API_BASE",)),
        Provider.FIREWORKS: (("FIREWORKS_API_KEY",), ("FIREWORKS_API_BASE",)),
        Provider.GEMINI: (("GEMINI_API_KEY", "GOOGLE_API_KEY"), ("GOOGLE_GEMINI_BASE_URL",)),
        Provider.GITHUB: (("GITHUB_TOKEN",), ("GITHUB_MODELS_API_BASE",)),
        Provider.GMI: (("GMI_API_KEY",), ("GMI_API_BASE",)),
        Provider.GROQ: (("GROQ_API_KEY",), ("GROQ_BASE_URL",)),
        Provider.HUGGINGFACE: (("HF_TOKEN",), ("HUGGINGFACE_API_BASE",)),
        Provider.INCEPTION: (("INCEPTION_API_KEY",), ("INCEPTION_API_BASE",)),
        Provider.KENARI: (("KENARI_API_KEY",), ("KENARI_API_BASE",)),
        Provider.LLAMA: (("LLAMA_API_KEY",), ("LLAMA_API_BASE",)),
        Provider.LMSTUDIO: (("LM_STUDIO_API_KEY",), ("LM_STUDIO_API_BASE",)),
        Provider.LLAMAFILE: (("LLAMAFILE_API_KEY",), ("LLAMAFILE_API_BASE",)),
        Provider.LLAMACPP: (("LLAMACPP_API_KEY",), ("LLAMACPP_API_BASE",)),
        Provider.META: (("MODEL_API_KEY",), ("META_API_BASE",)),
        Provider.MISTRAL: (("MISTRAL_API_KEY",), ("MISTRAL_API_BASE",)),
        Provider.MOONSHOT: (("MOONSHOT_API_KEY",), ("MOONSHOT_API_BASE",)),
        Provider.MZAI: (("MZAI_API_KEY",), ("MZAI_API_BASE",)),
        Provider.NEOSANTARA: (("NEOSANTARA_API_KEY",), ("NEOSANTARA_API_BASE",)),
        Provider.NEBIUS: (("NEBIUS_API_KEY",), ("NEBIUS_API_BASE",)),
        Provider.OLLAMA: (("OLLAMA_API_KEY",), ("OLLAMA_HOST",)),
        Provider.OPENAI: (("OPENAI_API_KEY",), ("OPENAI_BASE_URL", "OPENAI_API_BASE")),
        Provider.OTARI: (("OTARI_API_KEY",), ("OTARI_API_BASE",)),
        Provider.OPENROUTER: (("OPENROUTER_API_KEY",), ("OPENROUTER_API_BASE",)),
        Provider.PORTKEY: (("PORTKEY_API_KEY",), ("PORTKEY_API_BASE",)),
        Provider.QINIU: (("QINIU_API_KEY",), ("QINIU_API_BASE",)),
        Provider.REQUESTY: (("REQUESTY_API_KEY",), ("REQUESTY_API_BASE",)),
        Provider.SAMBANOVA: (("SAMBANOVA_API_KEY",), ("SAMBANOVA_API_BASE",)),
        Provider.SAGEMAKER: ((), ("SAGEMAKER_ENDPOINT_URL",)),
        Provider.TOGETHER: (("TOGETHER_API_KEY",), ("TOGETHER_API_BASE",)),
        Provider.VERTEXAI: ((), ("VERTEXAI_API_BASE",)),
        Provider.VERTEXAIANTHROPIC: ((), ("VERTEXAI_ANTHROPIC_API_BASE",)),
        Provider.VLLM: (("VLLM_API_KEY",), ("VLLM_API_BASE",)),
        Provider.VOYAGE: (("VOYAGE_API_KEY",), ("VOYAGE_API_BASE",)),
        Provider.WATSONX: (("WATSONX_API_KEY",), ("WATSONX_URL",)),
        Provider.XAI: (("XAI_API_KEY",), ("XAI_API_BASE",)),
        Provider.PERPLEXITY: (("PERPLEXITY_API_KEY",), ("PERPLEXITY_API_BASE",)),
        Provider.MINIMAX: (("MINIMAX_API_KEY",), ("MINIMAX_API_BASE",)),
        Provider.DASHSCOPE: (("DASHSCOPE_API_KEY",), ("DASHSCOPE_API_BASE",)),
        Provider.DEEPINFRA: (("DEEPINFRA_API_KEY",), ("DEEPINFRA_API_BASE",)),
        Provider.EDENAI: (("EDENAI_API_KEY",), ("EDENAI_API_BASE",)),
        Provider.ZAI: (("ZAI_API_KEY",), ("ZAI_BASE_URL",)),
        Provider.TELNYX: (("TELNYX_API_KEY",), ("TELNYX_API_BASE",)),
        Provider.CUSTOM: (("CUSTOM_API_KEY",), ("CUSTOM_API_BASE",)),
    }
)


##### TYPES #####
class AgentTier(BaseModel):
    """One agent tier: the endpoint a capability class resolves to; base and key fall back to the provider's own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Provider
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

    def agent_credentials(self) -> Mapping[Provider, tuple[SecretStr | None, str | None]]:
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
