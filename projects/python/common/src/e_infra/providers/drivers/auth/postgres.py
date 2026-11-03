"""providers/drivers/auth/postgres: accounts and grants in Postgres — the `AuthPort` over any `DatabasePort`.

Two tables: `auth_account` (an account: its keyed id, name, role, since when) and `auth_grant` (a grant: its digest,
account, kind, issue, expiry and revocation). Opening the driver creates them when missing. `enroll` makes an account or
renames it in place; `revoke` stamps every live grant of an account, never deletes one. The database is the lifespan's
to open and close, not this driver's."""

from typing import TYPE_CHECKING, ClassVar, Final, Self

from e_infra.infra.auth.models import Account, Grant, GrantKind, Role
from e_infra.infra.errors import ProviderError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from e_infra.ports.database import DatabasePort, Row

##### SQL #####
SCHEMA: Final[tuple[str, ...]] = (
    """CREATE TABLE IF NOT EXISTS auth_account (
    id text PRIMARY KEY, name text NOT NULL, role text NOT NULL, created timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS auth_grant (
    digest text PRIMARY KEY, owner text NOT NULL REFERENCES auth_account (id) ON DELETE CASCADE,
    kind text NOT NULL DEFAULT 'key', created timestamptz NOT NULL DEFAULT now(), expires timestamptz,
    revoked timestamptz)""",
    "CREATE INDEX IF NOT EXISTS auth_grant_owner ON auth_grant (owner) WHERE revoked IS NULL",
)
ENROLL: Final[str] = """
INSERT INTO auth_account (id, name, role) VALUES ($1, $2, $3)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role
RETURNING id, name, role, created"""
ACCOUNTS: Final[str] = "SELECT id, name, role, created FROM auth_account ORDER BY created"
ISSUE: Final[str] = (
    "INSERT INTO auth_grant (digest, owner, kind, created, expires) VALUES ($1, $2, $3, coalesce($4, now()), $5)"
)
REVOKE: Final[str] = "UPDATE auth_grant SET revoked = now() WHERE owner = $1 AND revoked IS NULL RETURNING digest"
HOLDER: Final[str] = """
SELECT a.id, a.name, a.role, a.created, g.digest, g.kind, g.created AS issued, g.expires, g.revoked
FROM auth_grant g JOIN auth_account a ON a.id = g.owner WHERE g.digest = $1"""


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
        return Account(owner=row["id"], name=row["name"], role=Role(row["role"]), created=row["created"])

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        _ = [await self._db.execute(statement) for statement in SCHEMA]
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
        row = await self._db.row(ENROLL, [account.owner, account.name, account.role.value])
        logger.debug("auth postgres enroll", owner=account.owner, role=account.role.value)
        return self._common_account(row) if row else account

    async def accounts(self) -> list[Account]:
        return [self._common_account(row) for row in await self._db.fetch(ACCOUNTS)]

    async def issue(self, grant: Grant) -> None:
        await self._db.execute(ISSUE, [grant.digest, grant.owner, grant.kind.value, grant.created, grant.expires])
        logger.debug("auth postgres issue", owner=grant.owner, kind=grant.kind.value)

    async def revoke(self, owner: str) -> int:
        revoked = len(await self._db.fetch(REVOKE, [owner]))
        logger.debug("auth postgres revoke", owner=owner, revoked=revoked)
        return revoked

    async def holder(self, digest: str) -> tuple[Account, Grant] | None:
        match await self._db.row(HOLDER, [digest]):
            case None:
                return None
            case row:
                grant = Grant(
                    digest=row["digest"], owner=row["id"], kind=GrantKind(row["kind"]), created=row["issued"],
                    expires=row["expires"], revoked=row["revoked"],
                )  # fmt: skip
                return self._common_account(row), grant
