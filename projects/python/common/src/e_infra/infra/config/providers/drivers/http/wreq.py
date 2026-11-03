"""infra/config/providers/drivers/http/wreq: the outbound HTTP client — HTTP_BASE_URL and HTTP_TIMEOUT."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class WreqSettings(BaseSettings):
    """HTTP_BASE_URL — joined to a relative path; HTTP_TIMEOUT — a request unless the call names its own (`timedelta`:
    plain seconds in config file or kwargs, `PT12.5S` in env)."""

    model_config = SettingsConfigDict(env_prefix="HTTP_")

    base_url: str = "https://httpbin.org"
    timeout: timedelta = timedelta(seconds=10)
