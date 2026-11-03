"""tests/unit/e_infra/infra/auth/guard: an entry's declared access met by the user the middleware resolved — the
refusal each earns, public never authenticated, an undeclared access failing loud."""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient

    from unit.e_infra.conftest import Logs

ANA = {"Authorization": "Bearer t-ana"}
ROOT = {"Authorization": "Bearer t-root"}


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/public", {}, 200),
        ("/public", {"Authorization": "Bearer stolen"}, 200),
        ("/anonymous", {}, 200),
        ("/user", {}, 401),
        ("/user", ANA, 200),
        ("/admin", {}, 401),
        ("/admin", ANA, 403),
        ("/admin", ROOT, 200),
    ],
    ids=["public", "public-bad-key", "anyone", "user-nobody", "user-ana", "admin-nobody", "admin-ana", "admin-root"],
)
async def test_guard_meets_the_declared_access(
    client: AsyncTestClient[Litestar], path: str, headers: dict[str, str], status: int
) -> None:
    assert (await client.get(path, headers=headers)).status_code == status


async def test_guard_refusals_speak_the_policys_words(client: AsyncTestClient[Litestar], logs: Logs) -> None:
    nobody, short = await client.get("/user"), await client.get("/admin", headers=ANA)
    assert (nobody.json()["detail"], nobody.headers["www-authenticate"], short.json()["detail"]) == (
        "user access: send a key (Authorization: Bearer)",
        "Bearer",
        "admin access: this key's account is user",
    )
    assert logs.at("warning") == ["auth guard refused", "auth guard refused"]


async def test_guard_options_declares_no_access(client: AsyncTestClient[Litestar]) -> None:
    assert (await client.options("/admin")).status_code == 204


async def test_guard_an_entry_without_access_fails_loud(client: AsyncTestClient[Litestar]) -> None:
    assert (await client.get("/undeclared", headers=ANA)).status_code == 500
