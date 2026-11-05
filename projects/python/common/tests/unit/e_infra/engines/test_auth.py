"""tests/unit/e_infra/engines/auth: accounts made by name, keys rotated, revoked and expired, headers resolved."""

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from e_infra.engines.auth import AuthEngine
from e_infra.infra.auth.models import ANONYMOUS, Role
from e_infra.infra.errors import AuthClosedError, AuthNameError, UnknownTokenError
from e_infra.ops.crypto import Crypto
from e_infra.ports.auth import AuthPort
from support.auth import FakeAuth
from unit.e_infra.conftest import auth_args

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs


def bearer(token: str) -> str:
    return f"Bearer {token}"


async def test_auth_store_meets_the_port(fake_auth: FakeAuth) -> None:
    assert isinstance(fake_auth, AuthPort)


async def test_auth_ensure_makes_the_admin(auth: AuthEngine, logs: Logs) -> None:
    """The admin's account, made once, keyed by its name; no key issued."""
    first, again = await auth.ensure(), await auth.ensure()
    assert (first.owner, again.owner, [account.role for account in await auth.accounts()]) == (
        Crypto.identify("k", "admin"),
        Crypto.identify("k", "admin"),
        [Role.ADMIN],
    )
    assert logs.at("info") == ["auth admin ensured", "auth admin ensured"]


async def test_auth_rotate_resolves(auth: AuthEngine) -> None:
    issued = await auth.rotate("damien")
    caller = await auth.resolve(bearer(issued.token))
    assert (caller.owner, caller.name, caller.role, issued.expires) == (
        Crypto.identify("k", "damien"), "damien", Role.USER, None,
    )  # fmt: skip


@pytest.mark.parametrize(
    "name", ["Damien", "damien@x.org", "", "d" * 33, "_d"], ids=["upper", "mail", "empty", "long", "lead"]
)
async def test_auth_plain_names(auth: AuthEngine, name: str) -> None:
    with pytest.raises(AuthNameError):
        await auth.rotate(name)


async def test_auth_rotate_admin(auth: AuthEngine) -> None:
    issued = await auth.rotate(auth.admin)
    assert (await auth.resolve(bearer(issued.token))).role is Role.ADMIN


async def test_auth_rotate_revokes_the_earlier(auth: AuthEngine) -> None:
    first, second = await auth.rotate("ana"), await auth.rotate("ana")
    with pytest.raises(UnknownTokenError, match="revoked"):
        await auth.resolve(bearer(first.token))
    assert (await auth.resolve(bearer(second.token))).name == "ana"


async def test_auth_revoke(auth: AuthEngine) -> None:
    issued = await auth.rotate("ana")
    assert (await auth.revoke("ana"), await auth.revoke("ana")) == (1, 0)
    with pytest.raises(UnknownTokenError):
        await auth.resolve(bearer(issued.token))


async def test_auth_expires(fake_auth: FakeAuth) -> None:
    """Past AUTH_TTL a key is refused; within it, it holds."""
    expired = AuthEngine(fake_auth, **auth_args(ttl=timedelta(seconds=-1)))
    held = AuthEngine(FakeAuth(), **auth_args(ttl=timedelta(days=1)))
    gone, kept = await expired.rotate("ana"), await held.rotate("ana")
    with pytest.raises(UnknownTokenError, match="expired"):
        await expired.resolve(bearer(gone.token))
    assert (await held.resolve(bearer(kept.token))).name == "ana"


@pytest.mark.parametrize("header", ["", "Basic x", "Bearer ", "  Bearer  "], ids=["none", "scheme", "empty", "blank"])
async def test_auth_no_bearer_is_nobody(auth: AuthEngine, fake_auth: FakeAuth, header: str) -> None:
    assert (await auth.resolve(header), fake_auth.lookups) == (ANONYMOUS, 0)


async def test_auth_a_spaced_bearer_is_a_key_nobody_holds_never_nobody(auth: AuthEngine, fake_auth: FakeAuth) -> None:
    """What follows the scheme is the token whole: a malformed key is refused, not read as an anonymous caller."""
    with pytest.raises(UnknownTokenError):
        await auth.resolve("Bearer a b")
    assert fake_auth.lookups == 1


async def test_auth_scheme_is_caseless(auth: AuthEngine) -> None:
    issued = await auth.rotate("ana")
    assert (await auth.resolve(f"bearer {issued.token}")).name == "ana"


async def test_auth_unknown(auth: AuthEngine) -> None:
    with pytest.raises(UnknownTokenError, match="unknown"):
        await auth.resolve(bearer("stolen"))


@pytest.mark.parametrize("call", ["ensure", "rotate", "revoke"])
async def test_auth_closed(fake_auth: FakeAuth, call: str) -> None:
    """With no secret, no account is made, rotated or revoked."""
    closed = AuthEngine(fake_auth, **auth_args(secret=None))
    arguments = {"ensure": (), "rotate": ("ana",), "revoke": ("ana",)}[call]
    with pytest.raises(AuthClosedError):
        await getattr(closed, call)(*arguments)
