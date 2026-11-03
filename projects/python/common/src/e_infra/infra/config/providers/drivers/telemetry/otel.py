"""infra/config/providers/drivers/telemetry/otel: the telemetry edge — where spans go, how, how fast, how many."""

from datetime import timedelta
from enum import StrEnum, auto

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


##### ENUMS #####
class OtelProtocol(StrEnum):
    """The OTLP transport to the collector: HTTP/protobuf (`<endpoint>/v1/traces`) or gRPC (`host:port`)."""

    HTTP = auto()
    GRPC = auto()


##### SETTINGS #####
class OtelSettings(BaseSettings):
    """OTEL_ENDPOINT — collector base (empty: spans are minted, never exported); OTEL_PROTOCOL — http | grpc;
    OTEL_HEADERS — export headers as JSON, secret (a remote collector's key); OTEL_TIMEOUT — per-export deadline, which
    also bounds a shutdown against a dead collector; OTEL_FLUSH — how often the batch leaves (shorter: traces show
    sooner); OTEL_SERVICE — `service.name`; OTEL_ATTRIBUTES — extra resource attributes as JSON
    (`{"openinference.project.name": "e-graph"}`); OTEL_SAMPLE — share of traces kept, 0..1, parent-based. Read like
    every other setting (.env included) — the SDK's own OTEL_* variables only reach it from the real process
    environment."""

    model_config = SettingsConfigDict(env_prefix="OTEL_")

    endpoint: str = ""
    protocol: OtelProtocol = OtelProtocol.HTTP
    headers: dict[str, Secret] = Field(default_factory=dict)
    timeout: timedelta = timedelta(seconds=10)
    flush: timedelta = timedelta(seconds=5)
    service: str = "e-stack"
    attributes: dict[str, str] = Field(default_factory=dict)
    sample: float = Field(default=1.0, ge=0.0, le=1.0)
