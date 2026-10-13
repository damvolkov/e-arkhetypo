"""core/settings/base: pydantic-settings — frozen, typed, layered config.

This module wires the five layers every scope shares: config file < secrets < .env < environment <
kwargs. `Secret` is pydantic's `SecretStr`: masked through repr, str and f-strings, readable only
via `.get_secret_value()`. All sub-settings inherit from here."""

from typing import Final

from pydantic import SecretStr
from pydantic_settings import (
    BaseSettings as SettingsBase,
)
from pydantic_settings import (
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)

Secret = SecretStr

FILE_SOURCES: Final = (
    ("toml_file", TomlConfigSettingsSource),
    ("yaml_file", YamlConfigSettingsSource),
    ("json_file", JsonConfigSettingsSource),
)


class BaseSettings(SettingsBase):
    """Subclass and declare typed fields; the constructor merges every layer in one pass.

    A scope narrows its own sources through ``model_config``: ``env_prefix``, ``env_file``,
    ``toml_file`` / ``yaml_file`` / ``json_file``, ``secrets_dir`` (set ``/run/secrets`` there when
    it is containerized — an absent default directory warns). Complex values in env or .env are
    JSON-decoded; enums, paths and timedeltas validate on load, never at runtime."""

    model_config = SettingsConfigDict(
        frozen=True,
        ### every scope reads the one shared .env: each takes its own keys and ignores the others' — forbidding
        ### extras would make any foreign key (REDIS_URL, SECRET...) abort every other scope at load.
        extra="ignore",
        env_file=".env",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
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
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            *cls._settings_customise_files(settings_cls),
        )

    @staticmethod
    def _settings_customise_files(settings_cls: type[SettingsBase]) -> tuple[PydanticBaseSettingsSource, ...]:
        """The configured config-file sources only: absent format, absent source."""
        return tuple(source(settings_cls) for key, source in FILE_SOURCES if settings_cls.model_config.get(key))
