"""engines/auth: accounts and long-lived keys over any `AuthPort` — agnostic of store and door.

An account is made by a plain name (`damien`), never by itself: its id is `Crypto.identify` of the name under the
engine's secret, so the same name is the same account from every harness, and the id gives nothing back. A key is
`Crypto.token`, handed out once and kept as its `hash_bytes` digest; `rotate` revokes an account's keys and issues one,
creating the account when missing. A key holds until revoked, or past `ttl` when one is set. `resolve` turns an
`Authorization` header into a caller: no bearer is nobody; a bearer nobody holds, revoked or expired is refused, never
read as nobody. `ensure` makes the admin's account at startup and issues nothing: the admin's key comes only from
`rotate`. Without a secret the engine mints nothing. An OAuth2 engine is a sibling over the same port and records
(`GrantKind`)."""

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from e_infra.infra.auth.models import ANONYMOUS, Account, Caller, Grant, GrantKind, Issued, Role
from e_infra.infra.errors import AuthClosedError, AuthNameError, UnknownTokenError
from e_infra.infra.logger import logger
from e_infra.ops.crypto import Crypto
from e_infra.ops.hash import hash_bytes

if TYPE_CHECKING:
    from datetime import timedelta

    from pydantic import SecretStr

    from e_infra.ports.auth import AuthPort

### what any account's name is: plain, the same typed in every harness's config.
NAME: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
SCHEME: Final[str] = "bearer"


class AuthEngine:
    """Accounts and keys over an auth store: resolve a header, rotate and revoke an account's key, list accounts."""

    __slots__ = ("_admin", "_port", "_secret", "_ttl")

    def __init__(self, port: AuthPort, *, secret: SecretStr | None, ttl: timedelta | None, admin: str) -> None:
        self._port = port
        self._secret = secret.get_secret_value() if secret else ""
        self._ttl = ttl
        self._admin = admin

    ##### PRIVATE #####

    def _common_account(self, name: str) -> Account:
        """The account a name makes: its id keyed under the secret; the admin's name is the admin's alone."""
        match (self._secret, NAME.fullmatch(name)):
            case ("", _):
                message = "no secret: set AUTH_SECRET to make accounts"
                raise AuthClosedError(message)
            case (_, None):
                message = f"{name!r} is no account name: lower case letters, digits, '-' and '_', 1 to 32"
                raise AuthNameError(message)
            case _:
                role = Role.ADMIN if name == self._admin else Role.USER
                return Account(owner=Crypto.identify(self._secret, name), name=name, role=role)

    @staticmethod
    def _resolve_bearer(header: str) -> str:
        """The token an `Authorization: Bearer` header carries (scheme in any case); empty when it carries none. What
        follows the scheme is the token whole: `Bearer a b` is a key nobody holds — refused —, never nobody."""
        scheme, _, token = header.strip().partition(" ")
        return token.strip() if scheme.casefold() == SCHEME else ""

    @staticmethod
    def _resolve_held(account: Account, grant: Grant, now: datetime) -> Caller:
        """The account as a caller, while its grant holds."""
        match grant:
            case Grant(revoked=datetime()):
                message = "revoked token: ask for a new one"
                raise UnknownTokenError(message)
            case Grant(expires=datetime() as expires) if expires <= now:
                message = "expired token: ask for a new one"
                raise UnknownTokenError(message)
            case _:
                return Caller(
                    owner=account.owner, name=account.name, role=account.role, segments=account.segments,
                    delegate=account.delegate,
                )  # fmt: skip

    ############################################################

    ##### PUBLIC #####

    @property
    def admin(self) -> str:
        """The admin account's name."""
        return self._admin

    async def ensure(self) -> Account:
        """The admin's account, made when missing; no key is issued here."""
        account = await self._port.enroll(self._common_account(self._admin))
        logger.info("auth admin ensured", owner=account.owner, name=account.name)
        return account

    async def resolve(self, header: str) -> Caller:
        """The caller an `Authorization` header names: nobody without a bearer."""
        match self._resolve_bearer(header):
            case "":
                return ANONYMOUS
            case token:
                match await self._port.holder(hash_bytes(token.encode())):
                    case None:
                        message = "unknown token: it names no account"
                        raise UnknownTokenError(message)
                    case held:
                        return self._resolve_held(*held, datetime.now(UTC))

    async def rotate(self, name: str) -> Issued:
        """The account of `name` (made when missing; the admin's under its name) with one fresh key, every earlier one
        revoked; shown once."""
        account = await self._port.enroll(self._common_account(name))
        token, now = Crypto.token(), datetime.now(UTC)
        expires = now + self._ttl if self._ttl else None
        revoked = await self._port.revoke(account.owner)
        grant = Grant(
            digest=hash_bytes(token.encode()), owner=account.owner, kind=GrantKind.KEY, created=now, expires=expires
        )
        await self._port.issue(grant)
        logger.info("auth key rotated", owner=account.owner, name=account.name, revoked=revoked)
        return Issued(owner=account.owner, name=account.name, role=account.role, token=token, expires=expires)

    async def revoke(self, name: str) -> int:
        """Every live key of the account of `name` revoked; how many."""
        revoked = await self._port.revoke(self._common_account(name).owner)
        logger.info("auth keys revoked", name=name, revoked=revoked)
        return revoked

    async def accounts(self) -> list[Account]:
        """Every account, the admin's included."""
        return await self._port.accounts()

    async def delegate(self, name: str, *, delegate: bool) -> Account:
        """Whether the account of `name` acts for the people it serves; an unknown account is refused."""
        match await self._port.delegate(self._common_account(name).owner, delegate=delegate):
            case None:
                message = f"no account {name!r}: issue it a key first"
                raise AuthNameError(message)
            case account:
                logger.info("auth delegate set", owner=account.owner, name=name, delegate=delegate)
                return account

    async def segment(self, name: str, segments: frozenset[str]) -> Account:
        """The segments the account of `name` reads beyond the general, set whole; an unknown account is refused."""
        match await self._port.segment(self._common_account(name).owner, segments):
            case None:
                message = f"no account {name!r}: issue it a key first"
                raise AuthNameError(message)
            case account:
                logger.info("auth segments set", owner=account.owner, name=name, segments=sorted(segments))
                return account
