"""core/settings/db: the embedded sqlite store — DB_PATH."""

from pathlib import Path

from e_core.core.settings.base import BaseSettings


class DbSettings(BaseSettings):
    """DB_PATH — the file and its parent directories are created on connect."""

    db_path: Path = Path("data/app.db")
