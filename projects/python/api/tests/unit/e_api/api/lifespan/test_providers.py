"""tests/unit/e_api/api/lifespan/providers: every provider opened on one stack, in field order, by its role."""

from dataclasses import fields
from typing import TYPE_CHECKING, Final

from e_api.api.lifespan.providers import ProvidersState
from ports.provider import Provider

if TYPE_CHECKING:
    from litestar.testing import TestClient

### the roles are the section's fields: a provider the export drops leaves this list with it.
ROLES: Final[tuple[str, ...]] = tuple(each.name for each in fields(ProvidersState))


async def test_providers_named_in_field_order(client: TestClient) -> None:
    """Each role maps to the provider it holds, every one satisfying the lifecycle contract."""
    roles = client.app.state.system.providers.named
    assert tuple(roles) == ROLES
    assert all(isinstance(provider, Provider) for provider in roles.values())


async def test_providers_open_inside_the_cycle(client: TestClient) -> None:
    """The open sqlite file answers its health while the app runs."""
    assert await client.app.state.system.providers.named["store"].health()
