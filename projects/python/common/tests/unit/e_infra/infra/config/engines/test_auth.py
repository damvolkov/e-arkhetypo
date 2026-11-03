"""tests/unit/e_infra/infra/config/engines/auth: AuthSettings — the secret, how long a key holds, the admin's name."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.engines.auth import AuthSettings

if TYPE_CHECKING:
    import pytest


def test_auth_defaults_close_the_engine() -> None:
    assert (AuthSettings().secret, AuthSettings().ttl, AuthSettings().admin) == (None, None, "admin")


def test_auth_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "s3cret")
    monkeypatch.setenv("AUTH_TTL", "P30D")
    monkeypatch.setenv("AUTH_ADMIN", "root")
    conf = AuthSettings()
    assert (conf.secret.get_secret_value() if conf.secret else "", conf.ttl, conf.admin) == (
        "s3cret",
        timedelta(days=30),
        "root",
    )


def test_auth_secret_stays_masked() -> None:
    assert "s3cret" not in repr(AuthSettings(secret="s3cret"))
