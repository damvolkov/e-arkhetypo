"""infra/config/providers: the edges of the providers — one block per driver and adapter, every field its variable."""

from datetime import timedelta
from enum import StrEnum, auto
from pathlib import Path
from typing import Annotated, Any, ClassVar, Self

from pydantic import (
    ByteSize,
    Field,
    HttpUrl,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    PostgresDsn,
    RedisDsn,
    Secret,
    SecretStr,
    field_validator,
    model_validator,
)

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class DoclingFormat(StrEnum):
    """What a conversion hands back: markdown, the lossless DoclingDocument JSON, html, plain text, doctags."""

    MD = auto()
    JSON = auto()
    HTML = auto()
    TEXT = auto()
    DOCTAGS = auto()


class DoclingImages(StrEnum):
    """How pictures come back: a placeholder only, embedded as base64 data URIs, or referenced by path."""

    PLACEHOLDER = auto()
    EMBEDDED = auto()
    REFERENCED = auto()


class DoclingTables(StrEnum):
    """TableFormer's mode: `accurate` recovers merged cells and headers, `fast` trades that for speed."""

    FAST = auto()
    ACCURATE = auto()


class DoclingBackend(StrEnum):
    """The PDF parser: docling's own (layout-faithful) or pypdfium2 (lighter, plainer)."""

    DOCLING_PARSE = auto()
    PYPDFIUM2 = auto()


class OTelProtocol(StrEnum):
    """The OTLP transport to the collector: HTTP/protobuf (`<endpoint>/v1/traces`) or gRPC (`host:port`)."""

    HTTP = auto()
    GRPC = auto()


##### SETTINGS #####
class ProviderSettings(BaseSettings):
    """The providers' edges: where each driver speaks, how long it waits, how much it holds; a block per module.

    A URL that may be absent reads the string `none` as absent (`GLINER_URL=none`): the NER and the reranker are off."""

    ##### DRIVERS #####

    ### ASYNCPG
    ### the database, password included: PgQueuer on this driver wants a database of its own (`app_background`).
    ASYNCPG_DSN: Secret[PostgresDsn] = Secret(PostgresDsn("postgresql://postgres:postgres@127.0.0.1:45011/app"))
    ASYNCPG_POOL_MIN: NonNegativeInt = 1
    ### PgQueuer's managers, scheduler and LISTEN all draw from the pool: a queue's database wants at least six.
    ASYNCPG_POOL: PositiveInt = 8
    ASYNCPG_TIMEOUT: timedelta = timedelta(seconds=30)

    ### PSQLPY
    ### the service's database on the local ParadeDB, created at startup when missing.
    POSTGRES_DSN: Secret[PostgresDsn] = Secret(PostgresDsn("postgresql://postgres:postgres@127.0.0.1:45011/app"))
    POSTGRES_POOL: PositiveInt = 8
    POSTGRES_TIMEOUT: timedelta = timedelta(seconds=30)

    ### AWA AND PGQUEUER
    ### the queue's dedicated database, `<service>_background`: one per service, two sharing one would share queue names.
    QUEUE_DSN: Secret[PostgresDsn] = Secret(
        PostgresDsn("postgresql://postgres:postgres@127.0.0.1:45011/app_background")
    )
    ### awa opens every connection at connect, and below six a started runtime deadlocks on shutdown.
    QUEUE_POOL: Annotated[int, Field(ge=6)] = 10
    ### a call on the pool before work falls back to memory; both queues read the one bound, poll and drain.
    QUEUE_TIMEOUT: timedelta = timedelta(seconds=5)
    QUEUE_POLL: timedelta = timedelta(milliseconds=200)
    QUEUE_DRAIN: timedelta = timedelta(seconds=5)
    ### PgQueuer re-picks a job whose heartbeat is older than this: a loop blocked for longer runs the job twice.
    QUEUE_HEARTBEAT: Annotated[timedelta, Field(gt=timedelta(0))] = timedelta(seconds=30)
    QUEUE_RESTART: timedelta = timedelta(seconds=1)

    ### DOCLING
    ### unset, documents are read by liteparse and anytomd alone.
    DOCLING_URL: HttpUrl | None = None
    DOCLING_TIMEOUT: timedelta = timedelta(seconds=60)
    DOCLING_DEADLINE: timedelta = timedelta(minutes=15)
    DOCLING_POLL: timedelta = timedelta(seconds=1)
    DOCLING_PAGE_TIMEOUT: timedelta | None = None
    DOCLING_FORMATS: tuple[DoclingFormat, ...] = (DoclingFormat.MD, DoclingFormat.JSON)
    DOCLING_IMAGES: DoclingImages = DoclingImages.EMBEDDED
    DOCLING_IMAGES_SCALE: PositiveFloat = 2.0
    DOCLING_TABLES: DoclingTables = DoclingTables.ACCURATE
    DOCLING_OCR: bool = True
    DOCLING_FORCE_OCR: bool = False
    DOCLING_OCR_ENGINE: str = "auto"
    DOCLING_OCR_LANG: tuple[str, ...] = ()
    DOCLING_BACKEND: DoclingBackend = DoclingBackend.DOCLING_PARSE
    DOCLING_FORMULAS: bool = False
    DOCLING_PICTURES: bool = False
    DOCLING_CHARTS: bool = False
    DOCLING_CODE: bool = False

    ### TEI EMBED
    EMBED_URL: HttpUrl = HttpUrl("http://127.0.0.1:45110")
    EMBED_TIMEOUT: timedelta = timedelta(seconds=60)
    EMBED_BATCH: PositiveInt = 32
    EMBED_CONCURRENCY: PositiveInt = 2
    EMBED_MODEL: str = "Qwen/Qwen3-Embedding-0.6B"
    EMBED_DIMENSIONS: PositiveInt = 1024
    EMBED_QUERY_PREFIX: str = "Instruct: Given a question, retrieve the passages that answer it\nQuery: "

    ### TEI RERANK
    RERANK_URL: HttpUrl | None = HttpUrl("http://127.0.0.1:45111")
    RERANK_TIMEOUT: timedelta = timedelta(seconds=30)
    RERANK_BATCH: PositiveInt = 64

    ### WREQ
    HTTP_BASE_URL: HttpUrl = HttpUrl("https://httpbin.org")
    HTTP_TIMEOUT: timedelta = timedelta(seconds=10)
    ### sites that serve robots ask who asks and where to reach them: Wikimedia answers 403 without.
    HTTP_AGENT: str = "e-infra/1 (+https://github.com/damvolkov/e-arkhetypo)"
    ### sent to every service the process reaches: never one service's credential, which travels per call.
    HTTP_HEADERS: dict[str, str] = Field(default_factory=dict)

    ### OPENAI
    LLM_URL: HttpUrl = HttpUrl("http://127.0.0.1:45100/v1")
    ### the local stack's development key (`stack/llm/vllm`: `--api-key local-dev`), no secret: the default URL refuses it.
    LLM_KEY: SecretStr | None = SecretStr("local-dev")
    LLM_TIMEOUT: timedelta = timedelta(seconds=120)
    LLM_CONCURRENCY: PositiveInt = 8
    LLM_RPM: PositiveInt = 120
    LLM_MAX_TOKENS: Annotated[int, Field(ge=16)] = 4096
    ### the stack's served alias (`stack/llm/vllm`: `--served-model-name … demian-model`): stable across the models.
    LLM_MODEL: str = "demian-model"
    ### a provider's own body fields, merged into every chat-completions request.
    LLM_EXTRA: dict[str, Any] = Field(default_factory=dict)

    ### GLINER
    GLINER_URL: HttpUrl | None = HttpUrl("http://127.0.0.1:45120")
    GLINER_TIMEOUT: timedelta = timedelta(seconds=60)
    ### a request's body must fit the socket's buffers, or the client's TCP_USER_TIMEOUT (30 s) aborts the connection.
    GLINER_BATCH: PositiveInt = 16

    ### REDIS
    REDIS_URL: Secret[RedisDsn] = Secret(RedisDsn("redis://localhost:6379/0"))
    REDIS_POOL: PositiveInt = 10
    REDIS_TIMEOUT: timedelta = timedelta(seconds=5)

    ### SQLITE
    DB_PATH: Path = Path("data/app.db")
    DB_TIMEOUT: timedelta = timedelta(seconds=5)

    ### OTEL
    ### a collector's base, or gRPC's `host:port`: not always a URL. Empty, spans are minted and never exported.
    OTEL_ENDPOINT: str = ""
    OTEL_PROTOCOL: OTelProtocol = OTelProtocol.HTTP
    OTEL_HEADERS: dict[str, SecretStr] = Field(default_factory=dict)
    OTEL_TIMEOUT: timedelta = timedelta(seconds=10)
    OTEL_FLUSH: timedelta = timedelta(seconds=5)
    OTEL_SERVICE: str = "e-stack"
    OTEL_ATTRIBUTES: dict[str, str] = Field(default_factory=dict)
    OTEL_SAMPLE: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0

    ### GCS
    ### the bucket, and where under it this deployment's keys live (`test/run/` in tests).
    GCS_BUCKET: str = "local"
    GCS_PREFIX: str = ""
    ### the emulator's base; unset for Google with ADC. STORAGE_EMULATOR_HOST wins over GCS_API_ROOT.
    STORAGE_EMULATOR_HOST: str | None = None
    GCS_API_ROOT: str | None = None
    ### one request, seconds; objects a listing asks for at once.
    GCS_TIMEOUT: PositiveInt = 30
    GCS_PAGE: PositiveInt = 1000

    ### GOOGLE
    ### the Gemini API's key (unused on Vertex).
    GENAI_API_KEY: SecretStr | None = None
    ### Vertex instead of the Gemini API, its project and region: the model's and the embedder's alike.
    GENAI_ENTERPRISE: bool = False
    GENAI_PROJECT: str | None = None
    GENAI_LOCATION: str = "europe-southwest1"
    ### the model, set per tier by the root; one answer's ceiling. No sampling parameter: Gemini answers best with its own.
    GENAI_MODEL: str = "gemini-3.8-flash"
    GENAI_MAX_TOKENS: Annotated[int, Field(ge=16)] = 8192
    ### one call, milliseconds; unset, the model's and the embedder's own default below.
    GENAI_TIMEOUT_MS: PositiveInt | None = None
    GENAI_LLM_TIMEOUT_MS: ClassVar[int] = 120_000
    GENAI_EMBED_TIMEOUT_MS: ClassVar[int] = 60_000
    ### the embedder, the width asked (768: the house standard, halfvec), texts per request.
    GENAI_EMBED_MODEL: str = "gemini-embedding-001"
    GENAI_EMBED_DIMENSIONS: PositiveInt = 768
    GENAI_EMBED_BATCH: PositiveInt = 100

    ##### ADAPTERS #####

    ### THEINE
    ### the in-memory cache and the Postgres cache driver read the one TTL: None in code is until evicted.
    CACHE_SIZE: PositiveInt = 50_000
    CACHE_TTL: timedelta | None = timedelta(days=1)

    ### LINGUA
    ### a closed set of ISO 639-1 codes: smaller is faster and surer; another language is answered as the nearest.
    LANGUAGE_LANGUAGES: tuple[str, ...] = ("en", "es")

    ### ANYTOMD
    MD_VISION_BASE_URL: HttpUrl = HttpUrl("https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1")
    MD_VISION_API_KEY: SecretStr | None = None
    MD_VISION_MODEL: str = "qwen3.8-flash"
    MD_VISION_PROMPT: str = "Describe this image for an AI agent in plain Markdown: what it shows, any text in it."
    MD_IMAGE_DESCRIBE: bool = True
    MD_MAX_INPUT_BYTES: Annotated[ByteSize, Field(ge=1)] = ByteSize(100 * 1024 * 1024)
    MD_PDF_WORKERS: NonNegativeInt = 0
    MD_PDF_OCR: bool = False
    MD_PDF_LANGUAGE: str = "eng"
    MD_STRICT: bool = False
    MD_EXTRACT_COMMENTS: bool = False

    ### LITEPARSE
    DOC_WORKERS: NonNegativeInt = 0
    DOC_OCR: bool = False
    DOC_TESSDATA: Path | None = None
    DOC_OCR_LANGUAGE: str = "eng"

    ### OXIGRAPH
    ### rows a `select` takes from the store per thread hop: the stream's grain.
    OXIGRAPH_PAGE: PositiveInt = 1000

    @field_validator("RERANK_URL", "GLINER_URL", mode="before")
    @classmethod
    def _url_none(cls, value: object) -> object:
        ### the string `none` is the service off, as the variable always said.
        return None if value == "none" else value

    @model_validator(mode="after")
    def _asyncpg_bounds(self) -> Self:
        match self.ASYNCPG_POOL_MIN <= self.ASYNCPG_POOL:
            case True:
                return self
            case False:
                msg = f"ASYNCPG_POOL_MIN {self.ASYNCPG_POOL_MIN} is above ASYNCPG_POOL {self.ASYNCPG_POOL}"
                raise ValueError(msg)
