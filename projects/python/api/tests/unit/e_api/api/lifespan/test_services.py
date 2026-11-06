"""tests/unit/e_api/api/lifespan/services: crypto written to the graph, no resource to close."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from e_api.api.lifespan import services
from e_api.api.state import AppState
from e_api.infra.state import State
from e_api.ops.crypto import Crypto

if TYPE_CHECKING:
    from litestar import Litestar


async def test_services_write_crypto_to_the_graph() -> None:
    """Crypto is the one engine the services concern writes; it owns no resource to close."""
    app = SimpleNamespace(state=AppState({"system": State()}))
    async with services.lifespan(cast("Litestar", app)):
        assert isinstance(app.state.system.crypto, Crypto)


async def test_services_crypto_hashes_what_it_verifies() -> None:
    app = SimpleNamespace(state=AppState({"system": State()}))
    async with services.lifespan(cast("Litestar", app)):
        crypto = app.state.system.crypto
        hashed = await crypto.hash_password("correct-horse-1")
        assert await crypto.verify_password("correct-horse-1", hashed)
