"""models.session: what one invocation knows before its command runs — sealed into the state graph."""

from dataclasses import dataclass

from e_cli.models.identity import Identity


##### TYPES #####
@dataclass(frozen=True, slots=True)
class Session:
    """The run: its command path, its verbosity, and the identity the flag or env already gave (None → the store)."""

    command: str
    verbose: bool = False
    identity: Identity | None = None
