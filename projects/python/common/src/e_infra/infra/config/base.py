"""infra/config/base: pydantic-settings — frozen, typed, layered config.

This module wires the five layers every cluster shares: config file < secrets < .env < environment <
kwargs. The secrets are files under `secrets/<APP_ENV>/` (gitignored), one per key, named as its variable in lower case
(`secrets/dev/auth_secret` is AUTH_SECRET): the process of an environment reads its own — dev the dev keys, prod the
prod ones —; a cluster that names its own `secrets_dir` (`/run/secrets` in a container) reads that instead. Credentials
are pydantic's `SecretStr` or `Secret[T]`: masked through repr, str and f-strings, readable only via
`.get_secret_value()`. Every cluster inherits from here."""

from pathlib import Path
from typing import Final

from pydantic_settings import (
    BaseSettings as SettingsBase,
)
from pydantic_settings import (
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)

### the root of the secrets folders, one per environment; relative to the working directory, as `.env` is.
SECRETS: Final[Path] = Path("secrets")

FILE_SOURCES: Final = (
    ("toml_file", TomlConfigSettingsSource),
    ("yaml_file", YamlConfigSettingsSource),
    ("json_file", JsonConfigSettingsSource),
)


class SecretsEnv(SettingsBase):
    """The environment whose secrets a process reads: APP_ENV alone, from the environment or `.env` — read apart, before
    any cluster, so choosing the folder never needs the secrets it chooses."""

    model_config = SettingsConfigDict(extra="ignore", env_file=".env")

    app_env: str = "dev"


class BaseSettings(SettingsBase):
    """Subclass and declare typed UPPERCASE fields, each the name of its environment variable; the constructor merges
    every layer in one pass.

    A cluster narrows its sources through ``model_config``: ``env_file``, ``toml_file`` / ``yaml_file`` /
    ``json_file``, ``secrets_dir`` (set ``/run/secrets`` there when it is containerized; unset, the environment's folder
    under ``secrets/``, absent folder, absent source). Complex values in env or .env are JSON-decoded; enums, paths
    and timedeltas validate on load, never at runtime."""

    model_config = SettingsConfigDict(
        frozen=True,
        ### the one Settings reads the one shared .env: a foreign key in it must not abort the load.
        extra="ignore",
        env_file=".env",
        ### structured fields (an agent tier, a header map) take FIELD__KEY; no flat field is split on the delimiter.
        env_nested_delimiter="__",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[SettingsBase],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        ### pydantic-settings reads these first-to-highest: kwargs beat env, the config file is the floor.
        own = settings_cls.model_config.get("secrets_dir")
        secrets = (file_secret_settings,) if own else cls._settings_customise_secrets(settings_cls)
        return (init_settings, env_settings, dotenv_settings, *secrets, *cls._settings_customise_files(settings_cls))

    @staticmethod
    def _settings_customise_secrets(settings_cls: type[SettingsBase]) -> tuple[PydanticBaseSettingsSource, ...]:
        """The environment's secrets folder, when it exists: absent folder, absent source."""
        folder = SECRETS / SecretsEnv().app_env
        return (SecretsSettingsSource(settings_cls, secrets_dir=folder),) if folder.is_dir() else ()

    @staticmethod
    def _settings_customise_files(settings_cls: type[SettingsBase]) -> tuple[PydanticBaseSettingsSource, ...]:
        """The configured config-file sources only: absent format, absent source."""
        return tuple(source(settings_cls) for key, source in FILE_SOURCES if settings_cls.model_config.get(key))
