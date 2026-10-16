"""e_core.core.settings: five layered sources, frozen pydantic models, SecretStr, lazy singleton."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_settings import SettingsConfigDict

from e_core.core.settings import BaseSettings, Secret
from e_core.core.settings import settings as st
from e_core.core.settings.api import ApiSettings, HttpMethod
from e_core.core.settings.app import AppSettings, Env
from e_core.core.settings.crypto import CryptoSettings
from e_core.core.settings.db import DbSettings
from e_core.core.settings.http import HttpSettings


class DB(BaseModel):
    host: str = "localhost"
    port: int = 5432


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="E_", env_file=None)

    debug: bool = False
    port: int = 8000
    token: Secret = Secret("")
    db: DB = DB()


def _config(**kw: Any) -> SettingsConfigDict:
    """The test scope's config with one layer repointed."""
    return SettingsConfigDict(**{"env_prefix": "E_", "env_file": None, **kw})


##### LOAD #####
async def test_load_env_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E_PORT", "9000")
    monkeypatch.setenv("E_DEBUG", "true")
    monkeypatch.setenv("E_DB__PORT", "6543")
    settings = Settings()
    assert (settings.port, settings.debug, settings.db.port) == (9000, True, 6543)
    assert settings.db.host == "localhost"  # nested partial update keeps untouched defaults


async def test_load_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E_PORT", "9000")
    assert Settings(port=7000).port == 7000


@pytest.mark.parametrize(
    ("name", "body", "attr"),
    [
        ("c.toml", 'port = 5555\ntoken = "filetok"\n', "toml_file"),
        ("c.json", '{"port": 4321, "token": "filetok"}', "json_file"),
        ("c.yaml", "port: 7777\ntoken: filetok\n", "yaml_file"),
    ],
    ids=["toml", "json", "yaml"],
)
async def test_load_config_file_under_env(
    name: str, body: str, attr: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / name
    path.write_text(body)
    monkeypatch.setattr(Settings, "model_config", _config(**{attr: path}))
    monkeypatch.setenv("E_PORT", "6666")
    settings = Settings()
    assert (settings.port, settings.token.get_secret_value()) == (6666, "filetok")  # env beats file, file beats default


async def test_load_absent_file_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Settings, "model_config", _config(toml_file=tmp_path / "absent.toml"))
    assert Settings().port == 8000


async def test_load_corrupt_config_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c.toml"
    path.write_text("port = = =\n")
    monkeypatch.setattr(Settings, "model_config", _config(toml_file=path))
    with pytest.raises(Exception, match="Invalid value"):
        Settings()


async def test_load_secrets_never_leaks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "E_token").write_text("shh\n")
    monkeypatch.setattr(Settings, "model_config", _config(secrets_dir=tmp_path))
    settings = Settings()
    assert settings.token.get_secret_value() == "shh"
    assert "shh" not in repr(settings)


async def test_load_dotenv_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("export E_PORT='8123'\nE_DEBUG = true\n# junk\n")
    monkeypatch.setattr(Settings, "model_config", _config(env_file=tmp_path / ".env"))
    settings = Settings()
    assert (settings.port, settings.debug) == (8123, True)


async def test_env_json_decodes_complex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E_DB", '{"host": "fromjson", "port": 1}')
    assert Settings().db.host == "fromjson"


##### TYPES #####
async def test_secret_never_leaks() -> None:
    secret = Secret("hunter2")
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in f"{secret}"
    assert secret.get_secret_value() == "hunter2"


async def test_timedelta_and_path_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_TIMEOUT", "PT12.5S")
    monkeypatch.setenv("DB_PATH", "/data/app.db")
    assert HttpSettings().http_timeout == timedelta(seconds=12.5)
    assert DbSettings().db_path == Path("/data/app.db")


##### FROZEN #####
async def test_frozen_blocks_mutation() -> None:
    with pytest.raises(ValidationError):
        Settings().port = 1


##### ENUMS #####
async def test_app_env_decodes_to_typed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    assert AppSettings().app_env is Env.LOCAL
    assert AppSettings(app_env="dev").app_env in set(Env)


async def test_app_env_rejects_a_typo() -> None:
    with pytest.raises(ValidationError, match="validation error"):
        AppSettings(app_env="deV")


async def test_allow_methods_decode_to_typed_verbs() -> None:
    assert ApiSettings(allow_methods=["GET", "DELETE"]).allow_methods == [HttpMethod.GET, HttpMethod.DELETE]
    assert set(ApiSettings().allow_methods) <= set(HttpMethod)


async def test_allow_methods_rejects_a_foreign_verb() -> None:
    with pytest.raises(ValidationError, match="BREW"):
        ApiSettings(allow_methods=["BREW"])


##### LAZY SINGLETON #####
async def test_settings_proxy_loads_once_per_process() -> None:
    """The first attribute access builds the composite; later touches reuse the same instance."""
    assert st.app is st.app
    assert isinstance(st.app.app_env, Env)


async def test_composite_scopes_discovered() -> None:
    """Every settings module in the package became a scope on the composite."""
    assert all(
        hasattr(st, scope) for scope in ("api", "app", "cli", "crypto", "db", "http", "oauth", "otel", "redis", "ui")
    )


async def test_shared_dotenv_feeds_each_scope_its_own_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One .env for every scope: a key one scope owns (CRYPTO__SECRET, HTTP_BASE_URL) never aborts another (ApiSettings)."""
    (tmp_path / ".env").write_text("CRYPTO__SECRET=dotenv-secret-0123456789\nHTTP_BASE_URL=https://dotenv.test\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CRYPTO__SECRET", raising=False)
    assert ApiSettings().allow_origins
    assert HttpSettings().http_base_url == "https://dotenv.test"
    assert CryptoSettings().secret is not None
