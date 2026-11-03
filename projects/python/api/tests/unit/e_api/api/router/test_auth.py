"""tests/unit/e_api/api/router/auth: who the key names, and the admin's accounts and keys — the engine's rules at HTTP."""

from typing import TYPE_CHECKING

from litestar.testing import TestClient

from e_api.api.lifespan import engines
from e_api.main import create_app
from infra.settings import Settings

if TYPE_CHECKING:
    import pytest


def test_auth_me_names_the_caller(client: TestClient, ana_key: dict[str, str]) -> None:
    assert (client.get("/auth/me").json(), client.get("/auth/me", headers=ana_key).json()) == (
        {"owner": "", "name": "", "role": "anonymous"},
        {"owner": "ana", "name": "ana", "role": "user"},
    )


def test_auth_accounts_are_the_admins(client: TestClient, ana_key: dict[str, str], root_key: dict[str, str]) -> None:
    answered = (client.get("/auth/accounts", headers=ana_key), client.get("/auth/accounts", headers=root_key))
    assert (answered[0].status_code, sorted(account["name"] for account in answered[1].json())) == (
        403,
        ["admin", "ana", "root"],
    )


def test_auth_rotate_hands_out_a_key_that_resolves(client: TestClient, root_key: dict[str, str]) -> None:
    issued = client.post("/auth/accounts/carol/token", headers=root_key).json()
    named = client.get("/auth/me", headers={"Authorization": f"Bearer {issued['token']}"}).json()
    assert (issued["name"], issued["role"], named["name"], named["role"]) == ("carol", "user", "carol", "user")


def test_auth_revoke_ends_the_key(client: TestClient, root_key: dict[str, str]) -> None:
    issued = client.post("/auth/accounts/carol/token", headers=root_key).json()
    revoked = client.delete("/auth/accounts/carol/token", headers=root_key).json()
    after = client.get("/auth/me", headers={"Authorization": f"Bearer {issued['token']}"})
    assert (revoked, after.status_code) == ({"name": "carol", "revoked": 1}, 401)


def test_auth_a_name_that_is_no_name_is_a_400(client: TestClient, root_key: dict[str, str]) -> None:
    answered = client.post("/auth/accounts/Carol/token", headers=root_key)
    assert (answered.status_code, "no account name" in answered.json()["detail"]) == (400, True)


def test_auth_closed_engine_makes_no_account(monkeypatch: pytest.MonkeyPatch, root_key: dict[str, str]) -> None:
    """With no AUTH_SECRET the engine mints nothing: the route says 503, not a 500."""
    monkeypatch.setattr(engines, "st", Settings.load(engines={"auth": {"secret": None}}))
    with TestClient(create_app()) as client:
        answered = client.post("/auth/accounts/carol/token", headers=root_key)
    assert (answered.status_code, answered.json()["detail"]) == (503, "no secret: set AUTH_SECRET to make accounts")
