"""infra/config/rerank: the reranking edge — a text-embeddings-inference server holding a cross-encoder (RERANK_*)."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class RerankSettings(BaseSettings):
    """RERANK_URL — the TEI base serving a reranker; RERANK_BATCH — texts per request; RERANK_TIMEOUT — one request."""

    model_config = SettingsConfigDict(env_prefix="RERANK_")

    url: str = "http://127.0.0.1:45111"
    batch: int = Field(default=64, ge=1)
    timeout: timedelta = timedelta(seconds=30)
