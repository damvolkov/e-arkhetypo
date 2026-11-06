"""infra/config/engines: the engines' knobs — a block per engine."""

from datetime import timedelta
from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict, NonNegativeInt, SecretStr

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class QueueEngine(StrEnum):
    """The durable queue behind the background, for a composition root that offers the choice."""

    AWA = auto()
    PGQUEUER = auto()


class Tier(StrEnum):
    """How hard a task is: what a caller asks for, never a model."""

    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()


class Vendor(StrEnum):
    """Who serves a tier (never `Provider`: in this tree a provider is a driver or an adapter): the Gemini API (a key),
    Vertex (ADC), or any OpenAI-compatible server (vLLM, a gateway)."""

    GEMINI = auto()
    VERTEX = auto()
    OPENAI = auto()


class Embedder(StrEnum):
    """Who embeds: the local TEI, the Gemini API or Vertex. Each writes its own space: changing it is a reindex."""

    TEI = auto()
    GEMINI = auto()
    VERTEX = auto()


class CacheMode(StrEnum):
    """What the model agent does with its cache: OFF asks the model every time; RECORD reads first and keeps every new
    answer; REPLAY reads only — a miss is an error, so an evaluation never calls a model."""

    OFF = auto()
    RECORD = auto()
    REPLAY = auto()


##### TYPES #####
class LlmTier(BaseModel):
    """One tier's value: its vendor, its model, and an OpenAI-compatible base when the vendor is one."""

    model_config = ConfigDict(frozen=True)

    vendor: Vendor
    model: str
    api_base: str | None = None


##### SETTINGS #####
class EngineSettings(BaseSettings):
    """The engines: who may sign in, which queue backs the background, which model serves each tier, where releases
    live, how long a health check may take."""

    ### AUTH
    ### the key account ids are minted under (HMAC of a name): never rotated, or every account becomes someone new.
    AUTH_SECRET: SecretStr | None = None
    ### how long a key holds once issued (`P30D` in env); unset, until revoked.
    AUTH_TTL: timedelta | None = None
    AUTH_ADMIN: str = "admin"

    ### DISPATCH
    QUEUE_ENGINE: QueueEngine = QueueEngine.PGQUEUER
    ### how often at most a job's progress is written; the last snapshot is always written when it ends.
    QUEUE_THROTTLE: timedelta = timedelta(seconds=0.5)

    ### LLM
    ### each tier (`__VENDOR`, `__MODEL`, `__API_BASE`); a reply that does not decode is sent back LLM_RETRIES times.
    LLM_HIGH: LlmTier = LlmTier(vendor=Vendor.GEMINI, model="gemini-3.1-pro-preview")
    LLM_MEDIUM: LlmTier = LlmTier(vendor=Vendor.GEMINI, model="gemini-3.8-flash")
    LLM_LOW: LlmTier = LlmTier(vendor=Vendor.OPENAI, model="gemma4-26b-a4b")
    LLM_RETRIES: NonNegativeInt = 2
    LLM_EMBEDDER: Embedder = Embedder.TEI
    ### answers and vectors kept by content in the database's `cache` table (CACHE_TTL), shared by every instance.
    LLM_CACHE: CacheMode = CacheMode.RECORD

    ### RELEASE
    ### the folder under the blob store's own prefix every version and the current pointer live in.
    RELEASE_PREFIX: str = "releases/"

    ### HEALTH
    ### how long one provider's health check may take before it counts as down, at startup and on `GET /ready`.
    PING_TIMEOUT: timedelta = timedelta(seconds=2)

    def llm_tier(self, tier: Tier) -> LlmTier:
        """The value of one tier."""
        return {Tier.HIGH: self.LLM_HIGH, Tier.MEDIUM: self.LLM_MEDIUM, Tier.LOW: self.LLM_LOW}[tier]
