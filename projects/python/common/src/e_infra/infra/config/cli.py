"""infra/config/cli: the command-line edge of this app — a stored-login-free token, the journal's depth."""

from pydantic import NonNegativeInt, SecretStr

from e_infra.infra.config.base import BaseSettings


##### SETTINGS #####
class CliSettings(BaseSettings):
    """The command line: a run authenticates by token, and the journal keeps the last runs."""

    ### authenticates a run without a stored login.
    CLI_TOKEN: SecretStr | None = None
    ### how many runs the journal keeps.
    CLI_HISTORY: NonNegativeInt = 50
