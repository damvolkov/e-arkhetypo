"""infra/config/providers/drivers/ner/gliner: the NER edge — a gliner service answering zero-shot entities."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class GlinerSettings(BaseSettings):
    """GLINER_URL — the service's base; GLINER_TIMEOUT — the longest wait for the next line of a streamed answer, never
    for the whole of it; GLINER_BATCH — the most texts one request carries: a document's chunks go in requests of this
    many, one after the other, so a request's body always fits in the socket's buffers. A body the busy service reads
    slower than it is sent stays unacknowledged, and the client's TCP_USER_TIMEOUT (30 s) aborts the connection."""

    model_config = SettingsConfigDict(env_prefix="GLINER_")

    url: str = "http://127.0.0.1:45120"
    timeout: timedelta = timedelta(seconds=60)
    batch: int = Field(default=16, ge=1)
