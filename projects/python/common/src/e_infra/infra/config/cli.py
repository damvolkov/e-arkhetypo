"""infra/config/cli: the command-line edge of this app — CLI_TOKEN, CLI_HISTORY."""

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret

##### DEFAULTS #####
DEFAULT_HISTORY: int = 50


class CliSettings(BaseSettings):
    """CLI_TOKEN authenticates a run without a stored login; CLI_HISTORY caps how many runs the journal keeps."""

    model_config = SettingsConfigDict(env_prefix="CLI_")

    token: Secret | None = None
    history: int = DEFAULT_HISTORY
