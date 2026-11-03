"""tests/unit/e_infra/infra/config/providers/drivers/store/sqlite: SqliteSettings — the file and the busy timeout."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.store.sqlite import SqliteSettings

if TYPE_CHECKING:
    import pytest


def test_sqlite_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (SqliteSettings().path, SqliteSettings().timeout) == (Path("data/app.db"), timedelta(seconds=5))
    monkeypatch.setenv("DB_PATH", "/data/app.db")
    assert SqliteSettings().path == Path("/data/app.db")
