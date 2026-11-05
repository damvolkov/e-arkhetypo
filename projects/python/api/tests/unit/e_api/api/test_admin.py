"""tests/unit/e_api/api/admin: `python -m e_api admin` — the first key, minted on the service's own database through the
same engine."""

from typing import TYPE_CHECKING

import pytest

from e_api.api import admin
from infra.errors import AuthClosedError
from infra.settings import Settings

if TYPE_CHECKING:
    from support.auth import FakeAuth
    from support.psqlpy import FakePsqlpyServer


async def test_mint_rotates_the_admins_key(
    keys: FakeAuth, psqlpy: FakePsqlpyServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database provisioned, the store opened, the admin's key issued: it resolves as the admin."""
    monkeypatch.setattr(admin, "PostgresAuthDriver", lambda _database: keys)
    issued = await admin.mint()
    assert issued.name == "admin"
    assert any(grant.owner == issued.owner and grant.revoked is None for grant in keys.grants.values())
    assert any("pg_database" in sql for sql in psqlpy.sql())


async def test_mint_without_a_secret_is_refused(keys: FakeAuth, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin, "PostgresAuthDriver", lambda _database: keys)
    monkeypatch.setattr(admin, "st", Settings(AUTH_SECRET=None))
    with pytest.raises(AuthClosedError):
        await admin.mint()
