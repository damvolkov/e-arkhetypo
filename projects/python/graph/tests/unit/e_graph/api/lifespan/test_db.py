"""tests/unit/e_graph/api/lifespan/db: every database the settings name, provisioned in order; a failure only warns."""

from typing import ClassVar

import pytest
from litestar import Litestar

from adapters.postgres import PostgresError
from e_graph.api.lifespan import db
from infra.config.base import Secret
from infra.config.postgres import PostgresSettings


class FakeAdapter:
    """A postgres adapter whose `provision` logs the DSN it was built over: created unless the name ends in `down`,
    refused when it does."""

    log: ClassVar[list[str]] = []

    def __init__(self, settings: PostgresSettings) -> None:
        self.dsn = settings.dsn.get_secret_value()

    async def provision(self) -> bool:
        self.log.append(self.dsn)
        match self.dsn.endswith("down"):
            case True:
                msg = "unreachable"
                raise PostgresError(msg)
            case False:
                return True


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeAdapter]:
    FakeAdapter.log = []
    monkeypatch.setattr(db, "PostgresAdapter", FakeAdapter)
    return FakeAdapter


async def test_db_provisions_every_row(fake: type[FakeAdapter]) -> None:
    async with db.lifespan(Litestar()):
        assert fake.log == [settings.dsn.get_secret_value() for settings in db.databases().values()]


async def test_db_failure_warns(fake: type[FakeAdapter]) -> None:
    """A database that cannot be provisioned reads as not created; startup goes on."""
    assert await db.provision("background", PostgresSettings(dsn=Secret("postgresql://h:1/down"))) is False
    assert await db.provision("background", PostgresSettings(dsn=Secret("postgresql://h:1/up"))) is True


def test_db_rows_are_the_queue() -> None:
    """The template's one database is the background queue's: the test run seeds its own, never the default."""
    assert {
        concern: settings.dsn.get_secret_value().rpartition("/")[2] for concern, settings in db.databases().items()
    } == {"background": "e_graph_test_background"}
