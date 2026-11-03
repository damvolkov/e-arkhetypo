"""services.auth: the credential use cases — keep a login, drop it, and decide who a run acts as.

Identity resolution is the one place auth policy lives: a run's own identity (flag or CLI_TOKEN, already
in the session) wins; otherwise the stored login; otherwise `IdentityError`. A command opts into it by
declaring `Inject[Identity]`, and the provider asks this service."""

from typing import TYPE_CHECKING

from e_cli.models.error import IdentityError
from e_cli.models.identity import Identity, IdentityOrigin

if TYPE_CHECKING:
    from ports.store import StorePort

##### DEFAULTS #####
KEY: str = "auth:token"


##### TYPES #####
class AuthService:
    """The stored login over any `StorePort`, and the resolution order around it."""

    __slots__ = ("_store",)

    def __init__(self, store: StorePort) -> None:
        self._store = store

    async def login(self, token: str) -> Identity:
        await self._store.set(KEY, token.encode())
        return Identity(origin=IdentityOrigin.STORE, token=token)

    async def logout(self) -> None:
        await self._store.delete(KEY)

    async def identify(self, given: Identity | None) -> Identity:
        """The run's own identity, else the stored login, else refused."""
        match (given, await self._store.get(KEY) if given is None else None):
            case (Identity() as run, _):
                return run
            case (None, bytes() as raw):
                return Identity(origin=IdentityOrigin.STORE, token=raw.decode())
            case _:
                raise IdentityError
