"""infra/settings/redis: the redis edge — REDIS_URL."""

from infra.settings.base import BaseSettings


class RedisSettings(BaseSettings):
    """REDIS_URL — anything redis.asyncio.from_url understands."""

    redis_url: str = "redis://localhost:6379/0"
