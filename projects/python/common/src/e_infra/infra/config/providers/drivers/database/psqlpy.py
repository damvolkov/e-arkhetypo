"""infra/config/providers/drivers/database/psqlpy: the psqlpy pool — POSTGRES_DSN, pool size and statement limit."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


class PsqlpySettings(BaseSettings):
    """POSTGRES_DSN — the service's database on the local ParadeDB (`app` by default; created at startup when missing),
    password included; POSTGRES_POOL — connections held; POSTGRES_TIMEOUT — one statement's ceiling."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    dsn: Secret = Secret("postgresql://postgres:postgres@127.0.0.1:45011/app")
    pool: int = Field(default=8, ge=1)
    timeout: timedelta = timedelta(seconds=30)
