"""tests/unit/e_infra/infra/settings: one `Settings` of category clusters — its sources, its types, and the law's gates.

The sources are proven on a cluster of the test's own; the gates read the real `Settings` and the source tree: every
field UPPERCASE, no field in two clusters, the environment names held against the snapshot, `infra.settings` read only
by the composition root, and nothing but enums and value types taken from `infra.config` below it."""

import ast
import json
import re
from datetime import timedelta
from pathlib import Path
from types import UnionType
from typing import Any, Final, Union, get_args, get_origin

import pytest
from pydantic import BaseModel, SecretStr, ValidationError
from pydantic_settings import SettingsConfigDict

from e_infra.infra import settings as composer
from e_infra.infra.config.api import ApiSettings, HTTPMethod
from e_infra.infra.config.base import BaseSettings
from e_infra.infra.config.infra import Env, InfraSettings
from e_infra.infra.settings import Settings, settings

RESOURCES: Final[Path] = Path(__file__).resolve().parents[3] / "resources"
SNAPSHOT: Final[Path] = RESOURCES / "settings" / "env.json"
### the package the spine sits in: `e_infra` here, the project's package or `src` once materialized.
SOURCE: Final[Path] = Path(composer.__file__).resolve().parents[1]
CONFIG: Final[Path] = SOURCE / "infra" / "config"
### the composition root: entrypoints, lifespans, request deps, the cli's runtime.
ROOT: Final[re.Pattern[str]] = re.compile(r"(^|/)(main|__main__|deps|cli)\.py$|(^|/)lifespan/|(^|/)cli/runtime/")


class DB(BaseModel):
    host: str = "localhost"
    port: int = 5432


class ProbeSettings(BaseSettings):
    """A cluster of the test's own, no `.env`: a flag, a port, a credential, a structured value."""

    model_config = SettingsConfigDict(env_file=None)

    PROBE_DEBUG: bool = False
    PROBE_PORT: int = 8000
    PROBE_TOKEN: SecretStr = SecretStr("")
    PROBE_DB: DB = DB()


def _config(**kw: Any) -> SettingsConfigDict:
    """The probe's config with one layer repointed."""
    return SettingsConfigDict(**{"env_file": None, **kw})


##### SOURCES #####
def test_load_env_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROBE_PORT", "9000")
    monkeypatch.setenv("PROBE_DEBUG", "true")
    monkeypatch.setenv("PROBE_DB__PORT", "6543")
    probe = ProbeSettings()
    assert (probe.PROBE_PORT, probe.PROBE_DEBUG, probe.PROBE_DB.port, probe.PROBE_DB.host) == (
        9000,
        True,
        6543,
        "localhost",
    )


def test_load_kwargs_beat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROBE_PORT", "9000")
    assert ProbeSettings(PROBE_PORT=7000).PROBE_PORT == 7000


@pytest.mark.parametrize(
    ("name", "body", "attr"),
    [
        ("c.toml", 'PROBE_PORT = 5555\nPROBE_TOKEN = "filetok"\n', "toml_file"),
        ("c.json", '{"PROBE_PORT": 4321, "PROBE_TOKEN": "filetok"}', "json_file"),
        ("c.yaml", "PROBE_PORT: 7777\nPROBE_TOKEN: filetok\n", "yaml_file"),
    ],
    ids=["toml", "json", "yaml"],
)
def test_load_config_file_under_env(
    name: str, body: str, attr: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / name
    path.write_text(body)
    monkeypatch.setattr(ProbeSettings, "model_config", _config(**{attr: path}))
    monkeypatch.setenv("PROBE_PORT", "6666")
    probe = ProbeSettings()
    assert (probe.PROBE_PORT, probe.PROBE_TOKEN.get_secret_value()) == (6666, "filetok")


def test_load_absent_file_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProbeSettings, "model_config", _config(toml_file=tmp_path / "absent.toml"))
    assert ProbeSettings().PROBE_PORT == 8000


def test_load_corrupt_config_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c.toml"
    path.write_text("PROBE_PORT = = =\n")
    monkeypatch.setattr(ProbeSettings, "model_config", _config(toml_file=path))
    with pytest.raises(Exception, match="Invalid value"):
        ProbeSettings()


def test_load_dotenv_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("export PROBE_PORT='8123'\nPROBE_DEBUG = true\n# junk\n")
    monkeypatch.setattr(ProbeSettings, "model_config", _config(env_file=tmp_path / ".env"))
    probe = ProbeSettings()
    assert (probe.PROBE_PORT, probe.PROBE_DEBUG) == (8123, True)


def test_env_json_decodes_a_structured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROBE_DB", '{"host": "fromjson", "port": 1}')
    assert ProbeSettings().PROBE_DB.host == "fromjson"


##### TYPES #####
def test_a_credential_never_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROBE_TOKEN", "hunter2")
    probe = ProbeSettings()
    assert ("hunter2" not in repr(probe), probe.PROBE_TOKEN.get_secret_value()) == (True, "hunter2")


def test_frozen_blocks_mutation() -> None:
    with pytest.raises(ValidationError):
        ProbeSettings().PROBE_PORT = 1


def test_app_env_decodes_to_typed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    assert InfraSettings().APP_ENV is Env.LOCAL


def test_app_env_rejects_a_typo() -> None:
    with pytest.raises(ValidationError, match="validation error"):
        InfraSettings(APP_ENV="deV")


def test_allow_methods_decode_to_typed_verbs() -> None:
    assert ApiSettings(ALLOW_METHODS=["GET", "DELETE"]).ALLOW_METHODS == [HTTPMethod.GET, HTTPMethod.DELETE]


def test_allow_methods_rejects_a_foreign_verb() -> None:
    with pytest.raises(ValidationError, match="BREW"):
        ApiSettings(ALLOW_METHODS=["BREW"])


def test_timedelta_coerced_from_iso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_TIMEOUT", "PT12.5S")
    assert timedelta(seconds=12.5) == Settings().HTTP_TIMEOUT


##### THE ONE SETTINGS #####
def test_settings_is_one_instance_of_every_cluster() -> None:
    clusters = [base for base in Settings.__bases__ if issubclass(base, BaseSettings)]
    assert (isinstance(settings, Settings), len(clusters) == len(Settings.__bases__)) == (True, True)


##### GATES — the law, read from the tree #####
def structured(annotation: object) -> tuple[type[BaseModel], ...]:
    """The structured types `__` reaches into: the annotation itself, or a member of its union — never a container's."""
    kinds = get_args(annotation) if get_origin(annotation) in {Union, UnionType} else (annotation,)
    return tuple(kind for kind in kinds if isinstance(kind, type) and issubclass(kind, BaseModel))


def names(model: type[BaseModel]) -> set[str]:
    """The environment names a settings class reads: each field, and `FIELD__KEY` into a structured one."""
    nested = (
        f"{name}__{key.upper()}"
        for name, field in model.model_fields.items()
        for kind in structured(field.annotation)
        for key in kind.model_fields
    )
    return {*model.model_fields, *nested}


def test_every_field_is_uppercase() -> None:
    assert [name for name in Settings.model_fields if name != name.upper()] == []


def test_no_field_lives_in_two_clusters() -> None:
    owners = [name for base in Settings.__bases__ for name in base.__annotations__]
    assert sorted({name for name in owners if owners.count(name) > 1}) == []


def test_environment_names_are_held() -> None:
    assert sorted(names(Settings)) == json.loads(SNAPSHOT.read_text())


def imports(path: Path) -> list[tuple[str, str]]:
    """Every `from <module> import <name>` of a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]


def below() -> list[Path]:
    """The modules below the composition root: every source module but the settings, the config and the root."""
    return [
        path
        for path in SOURCE.rglob("*.py")
        if CONFIG not in path.parents and path.name != "settings.py" and not ROOT.search(str(path.relative_to(SOURCE)))
    ]


def test_settings_is_read_by_the_composition_root_alone() -> None:
    readers = {
        str(path.relative_to(SOURCE))
        for path in below()
        for module, _ in imports(path)
        if module.endswith("infra.settings")
    }
    assert sorted(readers) == []


def test_below_the_root_config_gives_only_types() -> None:
    clusters = {
        f"{path.relative_to(SOURCE)!s}:{name}"
        for path in below()
        for module, name in imports(path)
        if ".infra.config" in f".{module}" and name.endswith("Settings")
    }
    assert sorted(clusters) == []
