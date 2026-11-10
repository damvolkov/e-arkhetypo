"""ports/auth: where accounts and grants are kept — the one contract an auth engine needs of a store.

Any store meets it by shape (Postgres today: `providers/drivers/auth/postgres`). Grants are kept by digest only; whether
a grant still holds (revoked, expired) is the engine's judgement, never the store's. The value types — accounts and
grants — are `infra/auth/models`."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from e_infra.infra.auth.models import Account, Grant


@runtime_checkable
class AuthPort(Provider, Protocol):
    """Accounts and their grants: make what is missing (an account made again keeps its segments), keep or revoke
    grants, set an account's segments or whether it is a delegate (None: no such account), and tell whose a digest is."""

    async def enroll(self, account: Account) -> Account: ...

    async def accounts(self) -> list[Account]: ...

    async def issue(self, grant: Grant) -> None: ...

    async def revoke(self, owner: str) -> int: ...

    async def segment(self, owner: str, segments: frozenset[str]) -> Account | None: ...

    async def delegate(self, owner: str, *, delegate: bool) -> Account | None: ...

    async def holder(self, digest: str) -> tuple[Account, Grant] | None: ...
