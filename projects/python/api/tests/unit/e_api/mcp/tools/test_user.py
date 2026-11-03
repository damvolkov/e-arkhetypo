"""tests/unit/e_api/mcp/tools/user: the user records as tools, under both handshakes — an account reads, the admin writes,
a refusal is the API's own words, a record that is gone is the route's 404."""

from typing import TYPE_CHECKING

import pytest

from support.mcp import MODES, call, refused

if TYPE_CHECKING:
    from support.mcp import Connect

NEW = {"username": "bob", "email": "bob@example.com", "password": "s3cret-passphrase", "quota": "3.50"}
GHOST = "9d1a5b58-0e0e-4a5e-9a3f-000000000000"


@pytest.mark.parametrize("mode", MODES)
async def test_user_create_then_read_and_list(
    connect: Connect, ana_key: dict[str, str], root_key: dict[str, str], mode: str
) -> None:
    created = await call(connect, "api_user_create", NEW, root_key, mode)
    read = await call(connect, "api_user_read", {"user_id": created["id"]}, ana_key, mode)
    listed = await call(connect, "api_user_list", {}, ana_key, mode)
    assert (created["username"], "password" not in created, read == created, listed["result"] == [created]) == (
        "bob",
        True,
        True,
        True,
    )


async def test_user_update_keeps_what_is_left_out(connect: Connect, root_key: dict[str, str]) -> None:
    created = await call(connect, "api_user_create", NEW, root_key)
    changed = await call(connect, "api_user_update", {"user_id": created["id"], "email": "bob@e.gov"}, root_key)
    assert (changed["email"], changed["quota"]) == ("bob@e.gov", "3.50")


async def test_user_delete_is_idempotent(connect: Connect, ana_key: dict[str, str], root_key: dict[str, str]) -> None:
    created = await call(connect, "api_user_create", NEW, root_key)
    first = await call(connect, "api_user_delete", {"user_id": created["id"]}, root_key)
    again = await call(connect, "api_user_delete", {"user_id": created["id"]}, root_key)
    assert (first, again, await call(connect, "api_user_list", {}, ana_key)) == (
        {"result": None},
        {"result": None},
        {"result": []},
    )


@pytest.mark.parametrize("mode", MODES)
async def test_user_anonymous_is_refused_at_a_user_tool(connect: Connect, mode: str) -> None:
    assert await refused(connect, "api_user_list", {}, mode=mode) == "user access: send a key (Authorization: Bearer)"


@pytest.mark.parametrize("mode", MODES)
async def test_user_account_is_refused_at_an_admin_tool(connect: Connect, ana_key: dict[str, str], mode: str) -> None:
    assert await refused(connect, "api_user_create", NEW, ana_key, mode) == "admin access: this key's account is user"


async def test_user_missing_record_is_the_routes_404(connect: Connect, ana_key: dict[str, str]) -> None:
    assert await refused(connect, "api_user_read", {"user_id": GHOST}, ana_key) == "No such user"


async def test_user_update_of_a_missing_record(connect: Connect, root_key: dict[str, str]) -> None:
    assert await refused(connect, "api_user_update", {"user_id": GHOST, "quota": "1.00"}, root_key) == "No such user"


async def test_user_invalid_arguments_name_the_fields(connect: Connect, root_key: dict[str, str]) -> None:
    assert (await refused(connect, "api_user_create", {"username": "BOB"}, root_key)).startswith("invalid arguments:")
