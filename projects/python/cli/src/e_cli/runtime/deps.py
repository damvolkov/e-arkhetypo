"""runtime.deps: injection by declared type — the one place ports meet providers, built on demand, once per run.

This is the composition root of the hexagon: `SqliteDriver` is named here and nowhere else, wrapped in the
undo journal and handed to the services as a bare `StorePort`. `Inject[T]` marks a parameter cyclopts must not parse (and `--help` must not show); the launcher resolves
each one from its type through `Deps.PROVIDERS`, a frozen table type → builder. A builder runs at most once
per run, and every resource it opens enters the run's exit stack, so edges close in reverse on the way out.
A command that never asks for the store never opens sqlite; one that never asks for an `Identity` never
needs a login. Adding an injectable is one builder and one row in the table."""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from types import MappingProxyType
from typing import Annotated, ClassVar, TypeVar, cast

from cyclopts import Parameter
from rich.console import Console

from e_cli.models.identity import Identity
from e_cli.runtime.journal import StoreJournal
from e_cli.services.auth import AuthService
from e_cli.services.project import ProjectService
from infra.settings import settings as st
from infra.state import State
from ports.store import StorePort
from providers.drivers.sqlite import SqliteDriver

T = TypeVar("T")
### cyclopts reads `Annotated` metadata but does not unwrap PEP 695 `type` aliases: the classic generic alias is what it sees.
Inject = Annotated[T, Parameter(parse=False)]

type Builder = Callable[[Deps], Awaitable[object]]


##### TYPES #####
class Deps:
    """The run's provider: builds what a command declares, caches it for the run, owns nothing past the stack."""

    __slots__ = ("_built", "_stack", "_state")

    def __init__(self, stack: AsyncExitStack, state: State) -> None:
        self._stack = stack
        self._state = state
        self._built: dict[Builder, object] = {}

    ##### PRIVATE METHODS #####

    async def _resolve_state(self) -> State:
        return self._state

    async def _resolve_console(self) -> Console:
        return Console()

    async def _resolve_store(self) -> StoreJournal:
        """The local store behind the undo journal: every command write is revertible by construction."""
        store = await self._stack.enter_async_context(SqliteDriver())
        journal = StoreJournal(store, command=self._state.session.command, depth=st.cli.cli_history)
        return await self._stack.enter_async_context(journal)

    async def _resolve_projects(self) -> ProjectService:
        return ProjectService(await self.resolve(StoreJournal))

    async def _resolve_auth(self) -> AuthService:
        return AuthService(await self.resolve(StoreJournal))

    async def _resolve_identity(self) -> Identity:
        return await (await self.resolve(AuthService)).identify(self._state.session.identity)

    ############################################################

    ##### PUBLIC #####

    PROVIDERS: ClassVar[Mapping[type, Builder]] = MappingProxyType(
        {
            State: _resolve_state,
            Console: _resolve_console,
            StorePort: _resolve_store,
            StoreJournal: _resolve_store,
            ProjectService: _resolve_projects,
            AuthService: _resolve_auth,
            Identity: _resolve_identity,
        }
    )

    async def resolve[K](self, kind: type[K]) -> K:
        """The run's single instance of `kind`, built on first ask."""
        try:
            build = self.PROVIDERS[kind]
        except KeyError:
            msg = f"no provider for {kind.__name__}: add a builder to Deps.PROVIDERS"
            raise TypeError(msg) from None
        match build in self._built:
            case False:
                self._built[build] = await build(self)
            case _:
                pass
        return cast("K", self._built[build])

    async def inject(self, wanted: Mapping[str, type]) -> dict[str, object]:
        """Every non-parsed parameter of a command, by name, resolved from its declared type."""
        return {name: await self.resolve(kind) for name, kind in wanted.items()}
