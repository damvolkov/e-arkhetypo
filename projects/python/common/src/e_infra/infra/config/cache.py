"""infra/config/cache: the caches a service takes — how many entries each keeps in memory, for how long (CACHE_*)."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class CacheSettings(BaseSettings):
    """CACHE_SIZE — entries a namespace keeps in memory (the durable layer keeps all); CACHE_TTL — how long a value is
    kept (`timedelta`: seconds in kwargs, `P180D` in env)."""

    model_config = SettingsConfigDict(env_prefix="CACHE_")

    size: int = Field(default=50_000, ge=1)
    ttl: timedelta = timedelta(days=1)
