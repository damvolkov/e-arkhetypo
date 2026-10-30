"""infra/config/app: process-level knobs — APP_ENV, APP_HOST, APP_PORT."""

from enum import StrEnum

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class Env(StrEnum):
    PROD = "prod"
    DEV = "dev"
    LOCAL = "local"


class AppSettings(BaseSettings):
    """APP_ENV (dev | local | prod) drives the logger; APP_HOST/APP_PORT drive the granian runner.

    The env is validated on decode: a typo (`deV`) fails the load, it never reaches runtime."""

    model_config = SettingsConfigDict(env_prefix="APP_")

    env: Env = Env.DEV
    host: str = "127.0.0.1"
    port: int = 8000
