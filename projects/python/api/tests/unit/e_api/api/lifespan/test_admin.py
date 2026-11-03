"""tests/unit/e_api/api/lifespan/admin: the admin's account made at startup, never a key; and `python -m e_api admin` —
the first key, minted on the service's own database through the same engine."""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import TestClient

from e_api.api import admin
from e_api.api.lifespan import engines
from e_api.main import create_app
from infra.auth.models import Role
from infra.errors import AuthClosedError
from infra.settings import Settings
from infra.settings import settings as st
from ops.crypto import Crypto

if TYPE_CHECKING:
    from support.auth import FakeAuth
    from support.psqlpy import FakePsqlpyServer


def test_startup_makes_the_admin_account_and_no_key(keys: FakeAuth) -> None:
    held = len(keys.grants)
    with TestClient(create_app()):
        made = keys.owners[Crypto.identify(st.engines.auth.secret.get_secret_value(), "admin")]
    assert (made.name, made.role, len(keys.grants)) == ("admin", Role.ADMIN, held)


def test_startup_without_a_secret_makes_no_account(monkeypatch: pytest.MonkeyPatch, keys: FakeAuth) -> None:
    monkeypatch.setattr(engines, "st", Settings.load(engines={"auth": {"secret": None}}))
    before = dict(keys.owners)
    with TestClient(create_app()):
        assert keys.owners == before


async def test_mint_rotates_the_admins_key(
    keys: FakeAuth, psqlpy: FakePsqlpyServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database provisioned, the store opened, the admin's key issued: it resolves as the admin."""
    monkeypatch.setattr(admin, "AuthPostgresDriver", lambda _database: keys)
    issued = await admin.mint()
    assert issued.name == "admin"
    assert any(grant.owner == issued.owner and grant.revoked is None for grant in keys.grants.values())
    assert any("pg_database" in sql for sql in psqlpy.sql())


async def test_mint_without_a_secret_is_refused(keys: FakeAuth, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin, "AuthPostgresDriver", lambda _database: keys)
    monkeypatch.setattr(admin, "st", Settings.load(engines={"auth": {"secret": None}}))
    with pytest.raises(AuthClosedError):
        await admin.mint()
