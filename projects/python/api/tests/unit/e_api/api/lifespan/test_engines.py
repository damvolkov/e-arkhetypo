"""tests/unit/e_api/api/lifespan/engines: every provider surveyed at startup — one event each, never a failed start; the
admin's account made there, never a key."""

from dataclasses import fields
from typing import TYPE_CHECKING, Final

from litestar.testing import TestClient

from e_api.api.lifespan import engines
from e_api.api.lifespan.engines import EnginesState
from e_api.api.lifespan.providers import ProvidersState
from e_api.main import create_app
from engines.auth import AuthEngine
from infra.auth.models import Role
from infra.settings import Settings
from infra.settings import settings as st
from ops.crypto import Crypto
from providers.drivers.store.sqlite import SqliteDriver

if TYPE_CHECKING:
    import pytest

    from support.auth import FakeAuth

### the roles are the section's fields: a provider the export drops leaves this list with it.
ROLES: Final[tuple[str, ...]] = tuple(each.name for each in fields(ProvidersState))


async def test_engines_section_is_typed(client: TestClient) -> None:
    section = client.app.state.system.engines
    assert isinstance(section, EnginesState)
    assert isinstance(section.auth, AuthEngine)


async def test_engines_health_surveys_every_provider(client: TestClient) -> None:
    """In field order, `store` and `auth` the required ones; the open sqlite file and the open client always answer."""
    verdicts = {verdict.name: verdict for verdict in await client.app.state.system.engines.health.survey()}
    assert tuple(verdicts) == ROLES
    assert [verdicts[name].required for name in ROLES] == [name in {"store", "auth"} for name in ROLES]
    assert verdicts["store"].ok


async def test_engines_startup_logs_each_verdict(
    monkeypatch: pytest.MonkeyPatch, logs: list[tuple[str, str, dict[str, object]]]
) -> None:
    """One event per provider as the app starts: info when it answers, a warning when it does not — the app starts."""

    async def down(_self: SqliteDriver) -> bool:
        return False

    monkeypatch.setattr(SqliteDriver, "health", down)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
    verdicts = {
        fields["provider"]: {"log_level": level, **fields}
        for level, event, fields in logs
        if event == "provider health"
    }
    assert tuple(verdicts) == ROLES
    assert (verdicts["store"]["log_level"], verdicts["store"]["ok"], verdicts["store"]["reason"]) == (
        "warning",
        False,
        "unhealthy",
    )
    assert not any(verdicts[name]["required"] for name in ROLES if name not in {"store", "auth"})


def test_engines_startup_makes_the_admin_account_and_no_key(keys: FakeAuth) -> None:
    held = len(keys.grants)
    with TestClient(create_app()):
        secret = st.AUTH_SECRET
        assert secret is not None
        made = keys.owners[Crypto.identify(secret.get_secret_value(), "admin")]
    assert (made.name, made.role, len(keys.grants)) == ("admin", Role.ADMIN, held)


def test_engines_startup_without_a_secret_makes_no_account(monkeypatch: pytest.MonkeyPatch, keys: FakeAuth) -> None:
    monkeypatch.setattr(engines, "st", Settings(AUTH_SECRET=None))
    before = dict(keys.owners)
    with TestClient(create_app()):
        assert keys.owners == before
