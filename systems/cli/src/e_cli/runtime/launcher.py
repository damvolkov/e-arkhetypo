"""runtime.launcher: the meta command every invocation passes through — global options, the run, the boundary.

cyclopts parses the global options here and hands the remaining tokens to the real tree. `parse_args`
returns the resolved command (lazily imported by then), its bound CLI arguments and the parameters it
declared as injected; the launcher opens the run's lifespan, injects those by type and awaits the command.
`CliError` is caught once, here: the message goes to stderr and its class decides the exit code. Every
mounted command is a coroutine function; the only sync callables the tree resolves are cyclopts' own
(help on a bare group), which run as they are, outside any lifespan."""

import inspect
from collections.abc import Callable, Coroutine, Iterable, Mapping
from inspect import BoundArguments
from typing import Annotated, Any

from cyclopts import App, Parameter
from rich.console import Console
from rich.markup import escape

from core.settings import settings as st
from e_cli.models.command import CommandCard
from e_cli.models.error import CliError
from e_cli.models.identity import Identity, IdentityOrigin
from e_cli.models.session import Session
from e_cli.runtime.lifespan import lifespan


##### TYPES #####
class Launcher:
    """Bound to the root app and the card table: knows each command's path without importing any command."""

    __slots__ = ("_app", "_paths")

    def __init__(self, app: App, cards: Iterable[CommandCard]) -> None:
        self._app = app
        self._paths = {card.target: card.path for card in cards}

    ##### PRIVATE METHODS #####

    def _run_path(self, command: Callable[..., object]) -> str:
        name = getattr(command, "__name__", "")
        return self._paths.get(f"{command.__module__}:{name}", name)

    @staticmethod
    def _run_identity(token: str) -> Identity | None:
        """The flag beats CLI_TOKEN; neither leaves the stored login to `Deps`."""
        env = st.cli.cli_token
        offered = ((token, IdentityOrigin.FLAG), ("" if env is None else env.get_secret_value(), IdentityOrigin.ENV))
        return next((Identity(origin=origin, token=value) for value, origin in offered if value), None)

    @staticmethod
    async def _run_command(
        command: Callable[..., Coroutine[Any, Any, None]],
        bound: BoundArguments,
        injected: Mapping[str, type],
        session: Session,
    ) -> int:
        """One run: the lifespan around the awaited command, its injected parameters resolved, the error boundary."""
        try:
            async with lifespan(session) as deps:
                await command(*bound.args, **bound.kwargs, **await deps.inject(injected))
        except CliError as exc:
            ### messages quote user input and regexes: escaped, or rich would read `[a-z]` as markup and eat it.
            Console(stderr=True).print(f"[bold red]✗[/] {escape(exc.message)}")
            return exc.exit_code
        return 0

    ############################################################

    ##### PUBLIC #####

    async def run(
        self,
        *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
        token: str = "",
        verbose: bool = False,
    ) -> int:
        """Global options, valid before any command.

        Args:
            token: credential for this run only; beats CLI_TOKEN and the stored login.
            verbose: diagnostics on stderr at debug level.
        """
        command, bound, injected = self._app.parse_args(tokens)
        match inspect.iscoroutinefunction(command):
            case True:
                session = Session(command=self._run_path(command), verbose=verbose, identity=self._run_identity(token))
                return await self._run_command(command, bound, injected, session)
            case _:
                ### cyclopts' own sync actions (the help of a bare group): not a run — no session, no lifespan.
                command(*bound.args, **bound.kwargs)
                return 0
