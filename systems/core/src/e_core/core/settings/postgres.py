"""core/settings/postgres: the Postgres edge — POSTGRES_DSN, pool and statement limits (POSTGRES_*)."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_core.core.settings.base import BaseSettings, Secret


class PostgresSettings(BaseSettings):
    """POSTGRES_DSN — the service's database on the local ParadeDB (`app` by default; created at startup when missing);
    POSTGRES_POOL — connections held; POSTGRES_TIMEOUT — one statement's ceiling."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    dsn: Secret = Secret("postgresql://postgres:postgres@127.0.0.1:45011/app")
    pool: int = Field(default=8, ge=1)
    timeout: timedelta = timedelta(seconds=30)
