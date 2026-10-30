"""e_infra.infra.settings: five layered sources, frozen pydantic models, SecretStr, lazy singleton."""

import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from pydantic import BaseModel, ValidationError
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.api import ApiSettings, HttpMethod
from e_infra.infra.config.app import AppSettings, Env
from e_infra.infra.config.crypto import CryptoSettings
from e_infra.infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from e_infra.infra.config.providers.drivers.http.wreq import WreqSettings
from e_infra.infra.config.providers.drivers.store.redis import RedisSettings
from e_infra.infra.config.providers.drivers.store.sqlite import SqliteSettings
from e_infra.infra.settings import BaseSettings, Secret
from e_infra.infra.settings import Settings as Composite
from e_infra.infra.settings import settings as st


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
    assert WreqSettings().timeout == timedelta(seconds=12.5)
    assert SqliteSettings().path == Path("/data/app.db")


##### FROZEN #####
async def test_frozen_blocks_mutation() -> None:
    with pytest.raises(ValidationError):
        Settings().port = 1


##### ENUMS #####
async def test_app_env_decodes_to_typed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    assert AppSettings().env is Env.LOCAL
    assert AppSettings(env="dev").env in set(Env)


async def test_app_env_rejects_a_typo() -> None:
    with pytest.raises(ValidationError, match="validation error"):
        AppSettings(env="deV")


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
    assert isinstance(st.app.env, Env)


async def test_composite_scopes_discovered() -> None:
    """Every settings module of the config tree became a scope on the composite, nested like the tree."""
    assert all(
        hasattr(node, leaf)
        for node, leaf in (
            (st, "api"),
            (st, "app"),
            (st, "cli"),
            (st, "crypto"),
            (st, "oauth"),
            (st, "ping"),
            (st.engines, "dispatch"),
            (st.processors, "doc"),
            (st.processors, "md"),
            (st.providers.drivers.database, "psqlpy"),
            (st.providers.drivers.database, "asyncpg"),
            (st.providers.drivers.store, "redis"),
            (st.providers.drivers.store, "sqlite"),
            (st.providers.drivers.http, "wreq"),
            (st.providers.drivers.queue, "awa"),
            (st.providers.drivers.queue, "pgqueuer"),
            (st.providers.drivers.telemetry, "otel"),
            (st.providers.adapters.cache, "theine"),
        )
    )


async def test_composite_chain_reads_as_the_path() -> None:
    """`st.providers.drivers.database.psqlpy` is the settings of `providers/drivers/database/psqlpy.py`."""
    assert isinstance(st.providers.drivers.database.psqlpy, PsqlpySettings)
    assert isinstance(st.providers.drivers.store.redis, RedisSettings)
    assert st.providers.drivers.database.psqlpy.pool == PsqlpySettings().pool


async def test_composite_load_overrides_by_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A per-scope override nested like the tree beats the scope's own layers, and only that scope's."""
    monkeypatch.setenv("POSTGRES_POOL", "5")
    loaded = Composite.load(providers={"drivers": {"database": {"psqlpy": {"pool": 3}}}}, app={"env": "prod"})
    assert (loaded.providers.drivers.database.psqlpy.pool, loaded.app.env) == (3, Env.PROD)
    assert loaded.providers.drivers.store.redis.pool == RedisSettings().pool
    assert Composite.load().providers.drivers.database.psqlpy.pool == 5


async def test_composite_is_frozen_all_the_way_down() -> None:
    loaded = Composite.load()
    with pytest.raises(ValidationError):
        loaded.providers.drivers.database.psqlpy.pool = 1
    with pytest.raises(ValidationError):
        loaded.providers = None


async def test_composite_is_lazy_at_import() -> None:
    """Importing the composer reads no environment: the proxy builds on its first access, not before."""
    code = "import os; os.environ['POSTGRES_POOL']='x'; import e_infra.infra.settings as s; print(type(s.settings).__name__)"
    ran = await anyio.run_process([sys.executable, "-c", code], check=False)
    assert (ran.returncode, ran.stdout.decode().strip()) == (0, "LazyProxy"), ran.stderr


async def test_shared_dotenv_feeds_each_scope_its_own_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One .env for every scope: a key one scope owns (CRYPTO__SECRET, HTTP_BASE_URL) never aborts another (ApiSettings)."""
    (tmp_path / ".env").write_text("CRYPTO__SECRET=dotenv-secret-0123456789\nHTTP_BASE_URL=https://dotenv.test\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CRYPTO__SECRET", raising=False)
    assert ApiSettings().allow_origins
    assert WreqSettings().base_url == "https://dotenv.test"
    assert CryptoSettings().secret is not None
