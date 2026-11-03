"""infra/config/providers/drivers/rerank/tei: the reranking edge — a text-embeddings-inference server and a cross-encoder."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class TeiRerankSettings(BaseSettings):
    """RERANK_URL — the TEI base serving a reranker; RERANK_TIMEOUT — one request; RERANK_BATCH — texts per request."""

    model_config = SettingsConfigDict(env_prefix="RERANK_")

    url: str = "http://127.0.0.1:45111"
    timeout: timedelta = timedelta(seconds=30)
    batch: int = Field(default=64, ge=1)
