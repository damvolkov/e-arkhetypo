"""The durable engines by QUEUE_ENGINE: every engine has its adapter, PgQueuer by default."""

import pytest

from e_core.adapters.queue import ENGINES
from e_core.core.background import BackgroundPort
from e_core.core.settings.queue import QueueEngine, QueueSettings


@pytest.mark.parametrize("engine", list(QueueEngine))
async def test_queue_engines(engine: QueueEngine) -> None:
    built = ENGINES[engine](QueueSettings(engine=engine))
    assert (isinstance(built, BackgroundPort), built.name) == (True, engine.value)


async def test_queue_default() -> None:
    assert QueueSettings().engine is QueueEngine.PGQUEUER
