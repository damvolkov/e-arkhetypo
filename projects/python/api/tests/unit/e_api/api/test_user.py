"""tests/unit: the user CRUD chain end to end — guard 401s, crypto tokens in, DTO families out."""

from uuid import UUID

import msgspec

from e_api.api.deps import USER_KEY
from e_api.models.user import UserRecord


def test_health_answers_without_graph_touching(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_oauth_registry_reports_empty_by_default(client) -> None:
    assert client.get("/oauth/providers").json() == {"providers": []}


def test_create_returns_read_model_without_credential(client) -> None:
    response = client.post(
        "/users",
        json={"username": "bob", "email": "bob@example.com", "password": "s3cret-passphrase"},
    )
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert "password" not in body
    assert "password_hash" not in body


def test_create_rejects_weak_input(client) -> None:
    response = client.post("/users", json={"username": "BOB", "email": "x", "password": "short"})
    assert response.status_code == 400


def test_guarded_routes_refuse_anonymous(client) -> None:
    assert client.get("/users").status_code == 401
    assert client.get("/users/9d1a5b58-0e0e-4a5e-9a3f-000000000000").status_code == 401


def test_unknown_subject_with_valid_token_is_refused(client, bearer) -> None:
    """The guard authenticates, chain 2 demands a real user — `read_user` is where the fake check runs."""
    response = client.get(f"/users/{UUID(int=1)}", headers=bearer("nobody"))
    assert response.status_code == 401


def test_list_read_update_delete_flow(client, bearer, created_user) -> None:
    user_id = created_user["id"]
    headers = bearer(user_id)

    assert [u["id"] for u in client.get("/users", headers=headers).json()] == [user_id]

    read = client.get(f"/users/{user_id}", headers=headers)
    assert read.status_code == 200
    assert read.json()["quota"] == "12.50"
    assert "x-request-id" in read.headers

    patched = client.patch(f"/users/{user_id}", json={"email": "alice@e.gov"}, headers=headers)
    assert patched.json()["email"] == "alice@e.gov"
    ### UNSET fields survive the patch
    assert patched.json()["quota"] == "12.50"

    assert client.delete(f"/users/{user_id}", headers=headers).status_code == 204
    ### identity died with the record: chain 2 refuses the now-unknown subject...
    assert client.get(f"/users/{user_id}", headers=headers).status_code == 401
    ### ...and for a still-valid identity, a missing target is a plain 404
    other = client.post(
        "/users",
        json={"username": "carol", "email": "carol@example.com", "password": "s3cret-passphrase"},
    ).json()["id"]
    assert client.get(f"/users/{UUID(int=9)}", headers=bearer(other)).status_code == 404


def test_tampered_token_is_rejected(client, bearer, created_user) -> None:
    headers = bearer(created_user["id"])
    forged = {"Authorization": headers["Authorization"][:-2] + "xx"}
    assert client.get("/users", headers=forged).status_code == 401


def test_credential_is_stored_only_as_an_argon2_hash(client, created_user) -> None:
    """The crypto-through-the-store chain end to end: what persists is a hash, verifiable and never the password."""
    graph = client.app.state.system
    with client.portal() as portal:
        raw = portal.call(graph.providers.store.get, USER_KEY + created_user["id"])
        record = msgspec.json.decode(raw, type=UserRecord)
        assert record.password_hash.startswith("$argon2id$")
        assert portal.call(graph.crypto.verify_password, "correct-horse-1", record.password_hash)


def test_patch_unknown_user_is_404(client, bearer, created_user) -> None:
    """The update chain reads the record first: identity is valid, target is gone."""
    headers = bearer(created_user["id"])
    assert client.patch(f"/users/{UUID(int=8)}", json={"quota": "1.00"}, headers=headers).status_code == 404
