"""tests/unit/e_api/api/router/user: the user CRUD chain end to end — the key's access per route, DTO families out."""

from uuid import UUID

import msgspec

from e_api.api.deps import USER_KEY
from e_api.models.user import UserRecord

NEW = {"username": "bob", "email": "bob@example.com", "password": "s3cret-passphrase"}


def test_create_returns_read_model_without_credential(client, root_key) -> None:
    response = client.post("/users", json=NEW, headers=root_key)
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert "password" not in body
    assert "password_hash" not in body


def test_create_rejects_weak_input(client, root_key) -> None:
    response = client.post("/users", json={"username": "BOB", "email": "x", "password": "short"}, headers=root_key)
    assert response.status_code == 400


def test_every_route_refuses_nobody(client) -> None:
    uid = "9d1a5b58-0e0e-4a5e-9a3f-000000000000"
    answered = [
        client.post("/users", json=NEW),
        client.get("/users"),
        client.get(f"/users/{uid}"),
        client.patch(f"/users/{uid}", json={}),
        client.delete(f"/users/{uid}"),
    ]
    assert [response.status_code for response in answered] == [401] * 5
    assert answered[0].json()["detail"] == "admin access: send a key (Authorization: Bearer)"
    assert answered[1].json()["detail"] == "user access: send a key (Authorization: Bearer)"


def test_writing_is_the_admins(client, ana_key, created_user) -> None:
    """An account reads; creating, changing and deleting a record are refused it, in the guard's words."""
    uid = created_user["id"]
    answered = [
        client.post("/users", json=NEW, headers=ana_key),
        client.patch(f"/users/{uid}", json={"quota": "1.00"}, headers=ana_key),
        client.delete(f"/users/{uid}", headers=ana_key),
    ]
    assert [response.status_code for response in answered] == [403] * 3
    assert answered[0].json()["detail"] == "admin access: this key's account is user"


def test_a_key_nobody_holds_is_refused_where_keys_are_read(client) -> None:
    """A public route never reads the key; every other is refused before its route runs."""
    forged = {"Authorization": "Bearer stolen"}
    assert [client.get(path, headers=forged).status_code for path in ("/users", "/auth/me", "/health")] == [
        401,
        401,
        200,
    ]


def test_list_read_update_delete_flow(client, ana_key, root_key, created_user) -> None:
    user_id = created_user["id"]

    assert [u["id"] for u in client.get("/users", headers=ana_key).json()] == [user_id]

    read = client.get(f"/users/{user_id}", headers=ana_key)
    assert read.status_code == 200
    assert read.json()["quota"] == "12.50"
    assert "x-request-id" in read.headers

    patched = client.patch(f"/users/{user_id}", json={"email": "alice@e.gov"}, headers=root_key)
    assert patched.json()["email"] == "alice@e.gov"
    ### UNSET fields survive the patch
    assert patched.json()["quota"] == "12.50"

    assert client.delete(f"/users/{user_id}", headers=root_key).status_code == 204
    ### a missing target is a plain 404
    assert client.get(f"/users/{user_id}", headers=ana_key).status_code == 404
    assert client.get("/users", headers=ana_key).json() == []


def test_credential_is_stored_only_as_an_argon2_hash(client, created_user) -> None:
    """The crypto-through-the-store chain end to end: what persists is a hash, verifiable and never the password."""
    graph = client.app.state.system
    with client.portal() as portal:
        raw = portal.call(graph.providers.store.get, USER_KEY + created_user["id"])
        record = msgspec.json.decode(raw, type=UserRecord)
        assert record.password_hash.startswith("$argon2id$")
        assert portal.call(graph.crypto.verify_password, "correct-horse-1", record.password_hash)


def test_patch_unknown_user_is_404(client, root_key) -> None:
    assert client.patch(f"/users/{UUID(int=8)}", json={"quota": "1.00"}, headers=root_key).status_code == 404
