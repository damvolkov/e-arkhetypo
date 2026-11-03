"""tests/unit/e_infra/infra/auth/middleware: the bearer resolved once into the request's user, an unknown key refused
before any route runs, an excluded route never resolved, and each refusal's HTTP answer."""

from typing import TYPE_CHECKING

import pytest
from litestar.status_codes import HTTP_200_OK, HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from e_infra.infra.auth.middleware import REFUSALS
from e_infra.infra.auth.models import ANONYMOUS, Role
from e_infra.infra.errors import AnonymousError, ForbiddenError, UnknownTokenError

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient

    from support.auth import FakeAuth
    from unit.e_infra.conftest import Logs


async def test_middleware_without_bearer_is_nobody_unread(client: AsyncTestClient[Litestar], keys: FakeAuth) -> None:
    answered = await client.get("/who")
    assert (answered.status_code, answered.json(), keys.lookups) == (
        HTTP_200_OK,
        {"name": ANONYMOUS.name, "role": Role.ANONYMOUS},
        0,
    )


async def test_middleware_bearer_resolved_once(client: AsyncTestClient[Litestar], keys: FakeAuth) -> None:
    answered = await client.get("/who", headers={"Authorization": "Bearer t-ana"})
    assert (answered.status_code, answered.json(), keys.lookups) == (HTTP_200_OK, {"name": "ana", "role": Role.USER}, 1)


async def test_middleware_unknown_key_refused(client: AsyncTestClient[Litestar], logs: Logs) -> None:
    answered = await client.get("/who", headers={"Authorization": "Bearer stolen"})
    assert (answered.status_code, answered.json()["detail"], answered.headers["www-authenticate"]) == (
        HTTP_401_UNAUTHORIZED,
        "unknown token: it names no account",
        'Bearer error="invalid_token"',
    )
    assert logs.at("warning") == ["auth key refused"]


async def test_middleware_excluded_route_never_resolved(client: AsyncTestClient[Litestar]) -> None:
    answered = await client.get("/open", headers={"Authorization": "Bearer stolen"})
    assert (answered.status_code, answered.json()) == (HTTP_200_OK, {"resolved": False})


@pytest.mark.parametrize(
    ("error", "status", "challenge"),
    [
        (UnknownTokenError, HTTP_401_UNAUTHORIZED, 'Bearer error="invalid_token"'),
        (AnonymousError, HTTP_401_UNAUTHORIZED, "Bearer"),
        (ForbiddenError, HTTP_403_FORBIDDEN, None),
    ],
    ids=["unknown", "anonymous", "forbidden"],
)
def test_middleware_refusals(error: type[UnknownTokenError], status: int, challenge: str | None) -> None:
    refused = REFUSALS[error](detail="why")
    assert (refused.status_code, refused.detail, (refused.headers or {}).get("WWW-Authenticate")) == (
        status,
        "why",
        challenge,
    )
