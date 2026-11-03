"""tests/unit/e_api/api/lifespan/infra: the infra singletons loaded once and mirrored as the `shared` section."""

from typing import TYPE_CHECKING

from e_api.api.lifespan.infra import SharedState
from infra.logger import logger
from infra.settings import settings as st

if TYPE_CHECKING:
    from litestar.testing import TestClient


def test_infra_shared_section_holds_the_loaded_singletons(client: TestClient) -> None:
    shared = client.app.state.system.shared
    assert isinstance(shared, SharedState)
    assert shared.settings is st
    assert shared.logger is logger


def test_infra_singleton_load_is_idempotent(client: TestClient) -> None:
    """Two touches, one instance: the LazyProxy cache pins the build for the whole process."""
    assert client.app.state.system.shared.settings.app is st.app
    assert st.app is st.app
