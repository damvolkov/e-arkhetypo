"""infra/config/engines/auth: the auth engine — the secret ids are minted under, a key's lifetime, the admin's name."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


class AuthSettings(BaseSettings):
    """AUTH_SECRET — the key account ids are minted under (HMAC of a name): never rotated, or every account becomes
    someone new; unset, no account can be made. AUTH_TTL — how long a key holds once issued (`timedelta`: seconds in
    kwargs, `P30D` in env); unset, until revoked. AUTH_ADMIN — the admin account's name."""

    model_config = SettingsConfigDict(env_prefix="AUTH_")

    secret: Secret | None = None
    ttl: timedelta | None = None
    admin: str = "admin"
