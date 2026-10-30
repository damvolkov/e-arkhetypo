"""infra/config/providers/drivers/embed/tei: the embedding edge — a text-embeddings-inference server and its model."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class TeiEmbedSettings(BaseSettings):
    """EMBED_URL — TEI base; EMBED_TIMEOUT — one request; EMBED_BATCH — texts per request; EMBED_CONCURRENCY — requests
    in flight; EMBED_MODEL — the HF id whose tokenizer sizes chunks; EMBED_DIMENSIONS — vector width;
    EMBED_QUERY_PREFIX — the instruction a query carries (Qwen3-Embedding embeds queries with one, documents without)."""

    model_config = SettingsConfigDict(env_prefix="EMBED_")

    url: str = "http://127.0.0.1:45110"
    timeout: timedelta = timedelta(seconds=60)
    batch: int = Field(default=32, ge=1)
    concurrency: int = Field(default=2, ge=1)
    model: str = "Qwen/Qwen3-Embedding-0.6B"
    dimensions: int = Field(default=1024, ge=1)
    query_prefix: str = "Instruct: Given a question, retrieve the passages that answer it\nQuery: "
