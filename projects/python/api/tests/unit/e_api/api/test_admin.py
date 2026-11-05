"""tests/unit/e_api/api/admin: `python -m e_api admin` — the first key, minted on the service's own database through the
same engine."""

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import PostgresDsn, Secret

from e_api.api import admin
from infra.errors import AuthClosedError
from infra.settings import settings as st

if TYPE_CHECKING:
    from support.auth import FakeAuth
    from support.psqlpy import FakePsqlpyServer


### what `__main__` hands `mint`: the service's database and the auth engine's values.
MINT: dict[str, Any] = {
    "dsn": Secret(PostgresDsn("postgresql://postgres:postgres@127.0.0.1:45011/app")),
    "pool": 2,
    "connect": st.POSTGRES_TIMEOUT,
    "secret": st.AUTH_SECRET,
    "ttl": None,
    "admin": "admin",
}


def without_secret() -> dict[str, Any]:
    """What `__main__` hands `mint` when no AUTH_SECRET is set."""
    return MINT | {"secret": None}


async def test_mint_rotates_the_admins_key(
    keys: FakeAuth, psqlpy: FakePsqlpyServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database provisioned, the store opened, the admin's key issued: it resolves as the admin."""
    monkeypatch.setattr(admin, "PostgresAuthDriver", lambda _database: keys)
    issued = await admin.mint(**MINT)
    assert issued.name == "admin"
    assert any(grant.owner == issued.owner and grant.revoked is None for grant in keys.grants.values())
    assert any("pg_database" in sql for sql in psqlpy.sql())


async def test_mint_without_a_secret_is_refused(keys: FakeAuth, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin, "PostgresAuthDriver", lambda _database: keys)
    with pytest.raises(AuthClosedError):
        await admin.mint(**without_secret())
