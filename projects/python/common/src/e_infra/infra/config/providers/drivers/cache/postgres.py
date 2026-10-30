"""infra/config/providers/drivers/cache/postgres: the durable cache in Postgres — how long a value lives."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class CachePostgresSettings(BaseSettings):
    """CACHE_TTL — how long a value is kept (`timedelta`: seconds in kwargs, `P180D` in env); unset in code (None),
    until it is replaced. The database is the one the driver rides: its DSN is that driver's."""

    model_config = SettingsConfigDict(env_prefix="CACHE_")

    ttl: timedelta | None = timedelta(days=1)
