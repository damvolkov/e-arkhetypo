"""core/settings/cli: the command-line edge of this app — CLI_TOKEN, CLI_HISTORY."""

from e_core.core.settings.base import BaseSettings, Secret

##### DEFAULTS #####
DEFAULT_HISTORY: int = 50


class CliSettings(BaseSettings):
    """CLI_TOKEN authenticates a run without a stored login; CLI_HISTORY caps how many runs the journal keeps."""

    cli_token: Secret | None = None
    cli_history: int = DEFAULT_HISTORY
