"""tests/support/auth: an `AuthPort` that keeps accounts and grants in dicts — the store an auth engine is tested over.

`FakeAuth` honours the port as Postgres does: `enroll` makes an account or renames it in place, `revoke` stamps every
live grant of an account and counts them, `holder` finds a grant by digest with its account. `key` seats an account with
a ready key whose digest is the token's, for the tests that send a header."""

from datetime import UTC, datetime
from typing import ClassVar, Self

import msgspec

from infra.auth.models import Account, Grant, GrantKind, Role
from ops.hash import hash_bytes
from ports.provider import Isolation, Locality, ProviderSpec, Workload


class FakeAuth:
    """Accounts by owner, grants by digest."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake-auth", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self) -> None:
        self.owners: dict[str, Account] = {}
        self.grants: dict[str, Grant] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    async def enroll(self, account: Account) -> Account:
        kept = self.owners.get(account.owner)
        self.owners[account.owner] = made = msgspec.structs.replace(
            account, created=kept.created if kept else datetime.now(UTC)
        )
        return made

    async def accounts(self) -> list[Account]:
        return list(self.owners.values())

    async def issue(self, grant: Grant) -> None:
        self.grants[grant.digest] = grant

    async def revoke(self, owner: str) -> int:
        live = [each for each in self.grants.values() if each.owner == owner and each.revoked is None]
        self.grants |= {each.digest: msgspec.structs.replace(each, revoked=datetime.now(UTC)) for each in live}
        return len(live)

    async def holder(self, digest: str) -> tuple[Account, Grant] | None:
        grant = self.grants.get(digest)
        return None if grant is None else (self.owners[grant.owner], grant)

    def key(self, token: str, name: str, role: Role = Role.USER) -> None:
        """An account of `name` with a live key `token`."""
        self.owners[name] = Account(owner=name, name=name, role=role, created=datetime.now(UTC))
        self.grants[hash_bytes(token.encode())] = Grant(
            digest=hash_bytes(token.encode()), owner=name, kind=GrantKind.KEY
        )
