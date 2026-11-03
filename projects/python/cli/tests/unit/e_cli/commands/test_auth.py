"""tests/unit/e_cli/commands/auth: the stored login and the per-run order: flag, then env, then store, never in clear."""

from types import SimpleNamespace
from typing import TYPE_CHECKING

from e_cli.runtime import launcher
from infra.settings import Secret

if TYPE_CHECKING:
    import pytest


def test_auth_status_without_any_credential_is_refused(ecli) -> None:
    code, _, err = ecli("auth", "status")
    assert code == 3
    assert "ecli auth login" in err


def test_auth_login_then_status_reads_the_store_masked(ecli) -> None:
    code, out, _ = ecli("auth", "login", "tok-12345678")
    assert code == 0
    assert "5678" in out
    _, out, _ = ecli("auth", "status")
    assert "store" in out
    assert "tok-1234" not in out


def test_auth_flag_beats_the_stored_login(ecli) -> None:
    ecli("auth", "login", "tok-12345678")
    _, out, _ = ecli("--token", "flag-9999", "auth", "status")
    assert "flag" in out
    assert "9999" in out


def test_auth_env_token_is_used_when_no_flag(ecli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "st", SimpleNamespace(cli=SimpleNamespace(token=Secret("env-7777"))))
    _, out, _ = ecli("auth", "status")
    assert "env" in out
    assert "7777" in out


def test_auth_logout_drops_the_stored_login(ecli) -> None:
    ecli("auth", "login", "tok-12345678")
    assert ecli("auth", "logout")[0] == 0
    assert ecli("auth", "status")[0] == 3
