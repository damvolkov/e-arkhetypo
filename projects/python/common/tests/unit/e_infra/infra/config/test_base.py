"""tests/unit/e_infra/infra/config/base: the layers every cluster shares — the environment's secrets folder above all."""

from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings

if TYPE_CHECKING:
    from pathlib import Path


class ProbeSettings(BaseSettings):
    """A cluster of the test's own: one secret, one plain value."""

    PROBE_SECRET: SecretStr = SecretStr("")
    PROBE_PLAIN: str = "default"


@pytest.fixture
def cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory of the test's own, no APP_ENV and no PROBE_* in the environment."""
    monkeypatch.chdir(tmp_path)
    _ = [monkeypatch.delenv(name, raising=False) for name in ("APP_ENV", "PROBE_SECRET", "PROBE_PLAIN")]
    return tmp_path


def _secret(folder: Path, env: str, value: str) -> None:
    (folder / "secrets" / env).mkdir(parents=True, exist_ok=True)
    (folder / "secrets" / env / "probe_secret").write_text(value)


@pytest.mark.parametrize(("env", "value"), [(None, "dev-key"), ("prod", "prod-key")], ids=["dev-default", "prod"])
def test_base_reads_the_secrets_of_its_own_environment(
    cwd: Path, monkeypatch: pytest.MonkeyPatch, env: str | None, value: str
) -> None:
    _secret(cwd, "dev", "dev-key")
    _secret(cwd, "prod", "prod-key")
    _ = env and monkeypatch.setenv("APP_ENV", env)
    assert ProbeSettings().PROBE_SECRET.get_secret_value() == value


def test_base_without_a_secrets_folder_reads_none(cwd: Path) -> None:
    assert (ProbeSettings().PROBE_SECRET.get_secret_value(), cwd.joinpath("secrets").exists()) == ("", False)


def test_base_environment_beats_a_secret_file(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _secret(cwd, "dev", "from-file")
    monkeypatch.setenv("PROBE_SECRET", "from-env")
    assert ProbeSettings().PROBE_SECRET.get_secret_value() == "from-env"


def test_base_a_cluster_naming_its_own_secrets_dir_reads_that(cwd: Path) -> None:
    _secret(cwd, "dev", "from-env-folder")
    (cwd / "run").mkdir()
    (cwd / "run" / "probe_secret").write_text("from-own-dir")

    class OwnSettings(ProbeSettings):
        model_config = SettingsConfigDict(secrets_dir=str(cwd / "run"))

    assert OwnSettings().PROBE_SECRET.get_secret_value() == "from-own-dir"
