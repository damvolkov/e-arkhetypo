"""infra/config/providers/adapters/cache/theine: the in-memory cache — how many entries it keeps, for how long (CACHE_*)."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class TheineSettings(BaseSettings):
    """CACHE_SIZE — entries a namespace keeps in memory (the durable layer keeps all); CACHE_TTL — how long a value is
    kept (`timedelta`: seconds in kwargs, `P180D` in env; None in code: until evicted). Each cache may be built on
    its own copy — a ledger kept forever beside annotations kept 180 days —, never one TTL for every scope."""

    model_config = SettingsConfigDict(env_prefix="CACHE_")

    size: int = Field(default=50_000, ge=1)
    ttl: timedelta | None = timedelta(days=1)
