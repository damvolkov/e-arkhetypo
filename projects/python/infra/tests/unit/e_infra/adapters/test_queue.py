"""The durable engines by QUEUE_ENGINE: every engine has its adapter, PgQueuer by default."""

import pytest

from e_infra.adapters.queue import ENGINES
from e_infra.infra.background import BackgroundPort
from e_infra.infra.settings.queue import QueueEngine, QueueSettings


@pytest.mark.parametrize("engine", list(QueueEngine))
async def test_queue_engines(engine: QueueEngine) -> None:
    built = ENGINES[engine](QueueSettings(engine=engine))
    assert (isinstance(built, BackgroundPort), built.name) == (True, engine.value)


async def test_queue_default() -> None:
    assert QueueSettings().engine is QueueEngine.PGQUEUER
