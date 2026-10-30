"""infra/config/providers/drivers/database/asyncpg: the asyncpg pool — ASYNCPG_DSN, pool bounds and command limit."""

from datetime import timedelta
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


class AsyncpgSettings(BaseSettings):
    """ASYNCPG_DSN — the database, password included (PgQueuer on this driver wants a database of its own:
    `app_background` beside the service's `app`); ASYNCPG_POOL_MIN / ASYNCPG_POOL — connections kept warm and the most
    held at once, the pool's own: PgQueuer's dedicated connections (one per queue, one for the scheduler) are opened
    beside it, not from it; ASYNCPG_TIMEOUT — connecting, and one command."""

    model_config = SettingsConfigDict(env_prefix="ASYNCPG_")

    dsn: Secret = Secret("postgresql://postgres:postgres@127.0.0.1:45011/app")
    pool_min: int = Field(default=1, ge=0)
    pool: int = Field(default=8, ge=1)
    timeout: timedelta = timedelta(seconds=30)

    @model_validator(mode="after")
    def _pool_bounds(self) -> Self:
        match self.pool_min <= self.pool:
            case True:
                return self
            case False:
                msg = f"pool_min {self.pool_min} is above the pool {self.pool}"
                raise ValueError(msg)
