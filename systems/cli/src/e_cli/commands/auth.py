"""commands.auth: driving adapter for the credential — parse, call `AuthService`, render.

A command that needs a caller declares `Inject[Identity]`; there is no auth flag on the card. These three
only manage the stored login: `--token` and CLI_TOKEN always win over it for a single run."""

from rich.console import Console

from e_cli.models.identity import Identity
from e_cli.runtime.deps import Inject
from e_cli.services.auth import AuthService


async def login(token: str, *, auth: Inject[AuthService], console: Inject[Console]) -> None:
    """Store a credential for every later run.

    Args:
        token: the credential to keep in the local store.
    """
    me = await auth.login(token)
    console.print(f"[green]✓[/] logged in · {me.masked}")


async def status(*, me: Inject[Identity], console: Inject[Console]) -> None:
    """Show who this run acts as, and where that credential came from."""
    console.print(f"authenticated · {me.origin} · {me.masked}")


async def logout(*, auth: Inject[AuthService], console: Inject[Console]) -> None:
    """Drop the stored credential; --token and CLI_TOKEN still work per run."""
    await auth.logout()
    console.print("[green]✓[/] logged out")
