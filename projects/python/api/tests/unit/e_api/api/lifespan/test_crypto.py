"""tests/unit/e_api/api/lifespan/crypto: crypto written to the graph, no resource to close."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from e_api.api.lifespan import crypto
from e_api.api.state import AppState
from e_api.infra.state import State
from e_api.ops.crypto import Crypto

if TYPE_CHECKING:
    from litestar import Litestar


async def test_lifespan_writes_crypto_to_the_graph() -> None:
    """Crypto is the one object this concern writes; it owns no resource to close."""
    app = SimpleNamespace(state=AppState({"system": State()}))
    async with crypto.lifespan(cast("Litestar", app)):
        assert isinstance(app.state.system.crypto, Crypto)


async def test_lifespan_hashes_what_it_verifies() -> None:
    app = SimpleNamespace(state=AppState({"system": State()}))
    async with crypto.lifespan(cast("Litestar", app)):
        hashed = await app.state.system.crypto.hash_password("correct-horse-1")
        assert await app.state.system.crypto.verify_password("correct-horse-1", hashed)
