"""models.error: the typed failure tree of the cli — every error a command raises carries its own exit code.

The launcher catches the root once and prints the message: a command raises, it never prints a failure
or calls `sys.exit` itself."""

from typing import ClassVar


##### ROOT #####
class CliError(Exception):
    """All expected cli failures. Anything else is a bug and keeps its traceback."""

    exit_code: ClassVar[int] = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


##### SPECIFIC #####
class IdentityError(CliError):
    """The command needs a caller and none was given: no --token, no CLI_TOKEN, no stored login."""

    exit_code: ClassVar[int] = 3

    def __init__(self) -> None:
        super().__init__("not authenticated: run `ecli auth login TOKEN`, pass --token or set CLI_TOKEN")


class JournalError(CliError):
    """The journal has nothing to undo."""

    exit_code: ClassVar[int] = 4


class ProjectError(CliError):
    """A project the command names does not exist, or already does."""

    exit_code: ClassVar[int] = 5
