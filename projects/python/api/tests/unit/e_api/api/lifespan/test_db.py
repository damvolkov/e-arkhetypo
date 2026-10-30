"""tests/unit/e_api/api/lifespan/db: every database the settings name, provisioned in order; a failure only warns."""

from typing import ClassVar

import pytest
from litestar import Litestar

from e_api.api.lifespan import db
from infra.config.base import Secret
from infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from infra.errors import DatabaseError


class FakeDriver:
    """A postgres driver whose `provision` logs the DSN it was built over: created unless the name ends in `down`,
    refused when it does."""

    log: ClassVar[list[str]] = []

    def __init__(self, settings: PsqlpySettings) -> None:
        self.dsn = settings.dsn.get_secret_value()

    async def provision(self) -> bool:
        self.log.append(self.dsn)
        match self.dsn.endswith("down"):
            case True:
                msg = "unreachable"
                raise DatabaseError(msg)
            case False:
                return True


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeDriver]:
    FakeDriver.log = []
    monkeypatch.setattr(db, "PsqlpyDriver", FakeDriver)
    return FakeDriver


async def test_db_provisions_every_row(fake: type[FakeDriver]) -> None:
    async with db.lifespan(Litestar()):
        assert fake.log == [settings.dsn.get_secret_value() for settings in db.databases().values()]


async def test_db_failure_warns(fake: type[FakeDriver]) -> None:
    """A database that cannot be provisioned reads as not created; startup goes on."""
    assert await db.provision("app", PsqlpySettings(dsn=Secret("postgresql://h:1/down"))) is False
    assert await db.provision("app", PsqlpySettings(dsn=Secret("postgresql://h:1/up"))) is True


def test_db_rows_are_the_service_database() -> None:
    """The template's one database is the service's own, the psqlpy scope POSTGRES_DSN configures."""
    assert list(db.databases()) == ["app"]
