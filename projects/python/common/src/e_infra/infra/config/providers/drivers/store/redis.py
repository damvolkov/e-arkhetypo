"""infra/config/providers/drivers/store/redis: the redis client — REDIS_URL, connection bound and socket timeout."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


class RedisSettings(BaseSettings):
    """REDIS_URL — anything redis.asyncio.from_url understands, password included; REDIS_POOL — connections the pool
    opens at most; REDIS_TIMEOUT — connecting, and one round trip."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: Secret = Secret("redis://localhost:6379/0")
    pool: int = Field(default=10, ge=1)
    timeout: timedelta = timedelta(seconds=5)
