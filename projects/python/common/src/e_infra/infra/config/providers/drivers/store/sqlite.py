"""infra/config/providers/drivers/store/sqlite: the embedded sqlite store — DB_PATH and the busy timeout."""

from datetime import timedelta
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class SqliteSettings(BaseSettings):
    """DB_PATH — the file and its parent directories are created on connect; DB_TIMEOUT — how long a statement waits
    for another connection's lock."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    path: Path = Path("data/app.db")
    timeout: timedelta = timedelta(seconds=5)
