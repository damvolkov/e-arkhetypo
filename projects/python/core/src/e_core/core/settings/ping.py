"""core/settings/ping: how long one adapter's ping may take — PING_TIMEOUT."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from e_core.core.settings.base import BaseSettings


class PingSettings(BaseSettings):
    """PING_TIMEOUT — how long one adapter's ping may take before it counts as down, at startup and on `GET /ready`
    (`timedelta`: plain seconds in a config file, `PT2S` in env)."""

    model_config = SettingsConfigDict(env_prefix="PING_")

    timeout: timedelta = timedelta(seconds=2)
