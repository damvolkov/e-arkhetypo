"""providers/drivers/auth/postgres: accounts and grants in Postgres — the `AuthPort` over any `DatabasePort`.

Two tables: `auth_account` (an account: its keyed id, name, role, since when) and `auth_grant` (a grant: its digest,
account, kind, issue, expiry and revocation). Opening the driver creates them when missing, under a transaction-level advisory lock. `enroll` makes an account or
renames it in place; `revoke` stamps every live grant of an account, never deletes one. The database is the lifespan's
to open and close, not this driver's."""

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Final, Self

import msgspec

from e_infra.infra.auth.models import Account, Grant, GrantKind, Role
from e_infra.infra.auth.query import AuthQuery
from e_infra.infra.errors import ProviderError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from e_infra.ports.database import DatabasePort, Row

### the tables, in the order they exist: the grant's owner references the account.
SCHEMA: Final[tuple[AuthQuery, ...]] = (
    AuthQuery.ACCOUNT_TABLE,
    AuthQuery.GRANT_TABLE,
    AuthQuery.GRANT_INDEX,
    AuthQuery.SEGMENTS_COLUMN,
    AuthQuery.DELEGATE_COLUMN,
)


##### WIRE #####
class PostgresAccount(msgspec.Struct, frozen=True, kw_only=True):
    """The account columns of a row, as the database names them."""

    id: str
    name: str
    role: Role
    created: datetime | None = None
    segments: tuple[str, ...] = ()
    delegate: bool = False


class PostgresHolder(PostgresAccount, frozen=True, kw_only=True):
    """A grant joined to its account: the grant's own columns (`issued` is its `created`)."""

    digest: str
    kind: GrantKind
    issued: datetime | None = None
    expires: datetime | None = None
    revoked: datetime | None = None


##### DRIVER #####
class PostgresAuthDriver:
    """Accounts and grants in the service's Postgres, over whichever `DatabasePort` it is handed."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("auth-postgres", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_db",)

    def __init__(self, db: DatabasePort) -> None:
        self._db = db

    ##### PRIVATE #####

    @staticmethod
    def _common_account(row: Row) -> Account:
        found = msgspec.convert(row, PostgresAccount, strict=False)
        return Account(
            owner=found.id,
            name=found.name,
            role=found.role,
            created=found.created,
            segments=frozenset(found.segments),
            delegate=found.delegate,
        )

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        async with self._db.transaction() as tx:
            await tx.execute(AuthQuery.LOCK)
            _ = [await tx.execute(statement) for statement in SCHEMA]
        logger.info("auth postgres opened")
        return self

    async def __aexit__(self, *exc: object) -> None:
        """The database is the lifespan's to close, not this driver's."""
        logger.info("auth postgres closed")

    async def health(self) -> bool:
        try:
            return await self._db.health()
        except ProviderError as error:
            logger.warning("auth postgres unhealthy", error=str(error))
            raise

    async def enroll(self, account: Account) -> Account:
        row = await self._db.row(AuthQuery.ENROLL, [account.owner, account.name, account.role.value])
        logger.debug("auth postgres enroll", owner=account.owner, role=account.role.value)
        return self._common_account(row) if row else account

    async def accounts(self) -> list[Account]:
        return [self._common_account(row) for row in await self._db.fetch(AuthQuery.ACCOUNTS)]

    async def issue(self, grant: Grant) -> None:
        await self._db.execute(
            AuthQuery.ISSUE, [grant.digest, grant.owner, grant.kind.value, grant.created, grant.expires]
        )
        logger.debug("auth postgres issue", owner=grant.owner, kind=grant.kind.value)

    async def revoke(self, owner: str) -> int:
        revoked = len(await self._db.fetch(AuthQuery.REVOKE, [owner]))
        logger.debug("auth postgres revoke", owner=owner, revoked=revoked)
        return revoked

    async def segment(self, owner: str, segments: frozenset[str]) -> Account | None:
        row = await self._db.row(AuthQuery.SEGMENT, [owner, sorted(segments)])
        logger.debug("auth postgres segment", owner=owner, segments=len(segments))
        return None if row is None else self._common_account(row)

    async def delegate(self, owner: str, *, delegate: bool) -> Account | None:
        row = await self._db.row(AuthQuery.DELEGATE, [owner, delegate])
        logger.debug("auth postgres delegate", owner=owner, delegate=delegate)
        return None if row is None else self._common_account(row)

    async def holder(self, digest: str) -> tuple[Account, Grant] | None:
        match await self._db.row(AuthQuery.HOLDER, [digest]):
            case None:
                return None
            case row:
                found = msgspec.convert(row, PostgresHolder, strict=False)
                grant = Grant(
                    digest=found.digest, owner=found.id, kind=found.kind, created=found.issued,
                    expires=found.expires, revoked=found.revoked,
                )  # fmt: skip
                return self._common_account(row), grant
