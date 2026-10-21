"""tests/unit/e_cli/services/auth: the resolution order — the run's identity, else the stored login, else refused."""

import pytest

from e_cli.models.error import IdentityError
from e_cli.models.identity import Identity, IdentityOrigin
from e_cli.services.auth import AuthService


async def test_auth_identify_prefers_the_run_identity(store) -> None:
    auth = AuthService(store)
    await auth.login("stored")
    given = Identity(origin=IdentityOrigin.FLAG, token="flag")
    assert await auth.identify(given) is given


async def test_auth_identify_falls_back_to_the_stored_login(store) -> None:
    auth = AuthService(store)
    await auth.login("stored")
    assert await auth.identify(None) == Identity(origin=IdentityOrigin.STORE, token="stored")


async def test_auth_identify_without_anything_is_refused(store) -> None:
    auth = AuthService(store)
    await auth.login("stored")
    await auth.logout()
    with pytest.raises(IdentityError):
        await auth.identify(None)
