from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anyio
import pytest
from awa import AwaError

from e_core.adapters.awa import AwaAdapter
from e_core.adapters.base import PingError
from e_core.conftest import settled
from e_core.core.background import BackgroundError, BackgroundPort, BackgroundState
from e_core.core.settings.base import Secret

if TYPE_CHECKING:
    from e_core.core.background import BackgroundRun
    from e_core.core.settings.queue import QueueSettings

pytestmark = pytest.mark.db


async def test_awa_port(awa: AwaAdapter) -> None:
    assert isinstance(awa, BackgroundPort)


async def test_awa_enqueue(awa: AwaAdapter, queue: str) -> None:
    job = await awa.enqueue("annotate", {"document": "d1", "names": ["lang"]}, queue=queue, attempts=1)
    assert job.id.isdecimal()
    assert (job.kind, job.queue, job.state, job.attempt) == ("annotate", queue, BackgroundState.AVAILABLE, 0)
    assert (job.args, job.progress, job.errors, job.finished) == ({"document": "d1", "names": ["lang"]}, None, (), None)
    assert await awa.job(job.id) == job


async def test_awa_enqueue_tuples(awa: AwaAdapter, queue: str) -> None:
    """A struct's builtins keep their tuples; awa takes JSON types only, so they travel as lists."""
    job = await awa.enqueue("annotate", {"enrichers": ("deterministic",), "scope": None}, queue=queue, attempts=1)
    assert job.args == {"enrichers": ["deterministic"], "scope": None}


async def test_awa_jobs(awa: AwaAdapter, queue: str) -> None:
    first = await awa.enqueue(f"{queue}-a", {}, queue=queue, attempts=1)
    second = await awa.enqueue(f"{queue}-b", {}, queue=queue, attempts=1)
    assert [job.id for job in await awa.jobs(kind=f"{queue}-a")] == [first.id]
    assert [job.id for job in await awa.jobs(kind=f"{queue}-b", state=BackgroundState.AVAILABLE)] == [second.id]
    assert await awa.jobs(kind=f"{queue}-b", state=BackgroundState.COMPLETED) == []


async def test_awa_cancel_queued(awa: AwaAdapter, queue: str) -> None:
    job = await awa.enqueue("annotate", {}, queue=queue, attempts=1)
    cancelled = await awa.cancel(job.id)
    assert cancelled is not None
    assert (cancelled.state, cancelled.finished is not None) == (BackgroundState.CANCELLED, True)


@pytest.mark.parametrize("job", ["4611686018427387904", "0190a1b2c3d4e5f6a7b8c9d0e1f2a3b4"])
async def test_awa_unknown(awa: AwaAdapter, job: str) -> None:
    """An id awa never issued, or one of another engine: None either way."""
    assert (await awa.job(job), await awa.cancel(job)) == (None, None)


async def test_awa_run_progress(awa: AwaAdapter, queue: str) -> None:
    """The latest snapshot outlives the completion that awa's own progress does not."""
    seen: list[str] = []

    async def handler(run: BackgroundRun) -> None:
        seen.append(run.job.id)
        await run.report({"stage": "fetch", "seen": 1})
        await run.report({"stage": "smoke", "seen": 2})

    awa.register("ingest", queue, handler)
    await awa.start({queue: 2})
    job = await awa.enqueue("ingest", {"source": "s"}, queue=queue, attempts=1)
    done = await settled(awa, job.id)
    assert (done.state, done.progress, seen) == (BackgroundState.COMPLETED, {"stage": "smoke", "seen": 2}, [job.id])
    assert [each.progress for each in await awa.jobs(kind="ingest", state=BackgroundState.COMPLETED, limit=1)] == [
        {"stage": "smoke", "seen": 2}
    ]


async def test_awa_run_failed(awa: AwaAdapter, queue: str) -> None:
    """The handler's own error, its first line: never the task group that watches it."""

    async def handler(_run: BackgroundRun) -> None:
        msg = "bad"
        raise ValueError(msg)

    awa.register("harvest", queue, handler)
    await awa.start({queue: 1})
    job = await awa.enqueue("harvest", {}, queue=queue, attempts=1)
    done = await settled(awa, job.id)
    assert (done.state, done.attempt, done.errors) == (BackgroundState.FAILED, 1, ("ValueError: bad",))


async def test_awa_cancel_running(awa: AwaAdapter, queue: str) -> None:
    started, interrupted = anyio.Event(), anyio.Event()

    async def handler(run: BackgroundRun) -> None:
        await run.report({"stage": "discover"})
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            interrupted.set()

    awa.register("ingest", queue, handler)
    await awa.start({queue: 1})
    job = await awa.enqueue("ingest", {}, queue=queue, attempts=1)
    await started.wait()
    await awa.cancel(job.id)
    with anyio.fail_after(5):
        await interrupted.wait()
    done = await settled(awa, job.id)
    assert (done.state, done.progress) == (BackgroundState.CANCELLED, {"stage": "discover"})


async def test_awa_connect_missing(queue_settings: QueueSettings) -> None:
    missing = queue_settings.model_copy(update={"dsn": Secret(f"{queue_settings.dsn.get_secret_value()}_missing")})
    with pytest.raises(BackgroundError, match="does not exist"):
        await AwaAdapter(missing).connect()


async def test_awa_connect_timeout(queue_settings: QueueSettings) -> None:
    """A host that never answers: the connect gives up at QUEUE_TIMEOUT, not at the driver's own thirty seconds."""
    down = queue_settings.model_copy(
        update={"dsn": Secret("postgresql://postgres:postgres@127.0.0.1:1/x"), "timeout": timedelta(milliseconds=300)}
    )
    with anyio.fail_after(5), pytest.raises(BackgroundError, match="timed out"):
        await AwaAdapter(down).connect()


async def test_awa_unconnected(queue_settings: QueueSettings) -> None:
    with pytest.raises(BackgroundError, match="not connected"):
        await AwaAdapter(queue_settings).job("1")


async def test_awa_close_twice(queue_settings: QueueSettings, queue: str) -> None:
    adapter = AwaAdapter(queue_settings)
    await adapter.connect()
    await adapter.connect()
    assert (await adapter.enqueue("annotate", {}, queue=queue, attempts=1)).state == BackgroundState.AVAILABLE
    await adapter.close()
    await adapter.close()
    with pytest.raises(BackgroundError, match="not connected"):
        await adapter.jobs()


async def test_awa_outage(queue_settings: QueueSettings, queue: str) -> None:
    """The pool gone under the adapter: every call is an outage the facade can fall back from."""
    adapter = AwaAdapter(queue_settings)
    await adapter.connect()
    job = await adapter.enqueue("annotate", {}, queue=queue, attempts=1)
    await adapter._common_client().close()
    with pytest.raises(BackgroundError):
        await adapter.enqueue("annotate", {}, queue=queue, attempts=1)
    with pytest.raises(BackgroundError):
        await adapter.job(job.id)
    with pytest.raises(BackgroundError):
        await adapter.cancel(job.id)
    with pytest.raises(BackgroundError):
        await adapter.jobs()


async def test_awa_found_propagates(awa: AwaAdapter) -> None:
    """An awa error that is neither an outage nor an unknown id is the caller's: it propagates."""

    async def call(_client: Any) -> None:
        msg = "unique conflict"
        raise AwaError(msg)

    with pytest.raises(AwaError, match="unique conflict"):
        await awa._common_found(call)


async def test_awa_call_timeout(queue_settings: QueueSettings) -> None:
    """A call that outlasts QUEUE_TIMEOUT is an outage, not a hang."""
    adapter = AwaAdapter(queue_settings.model_copy(update={"timeout": timedelta(milliseconds=100)}))
    await adapter.connect()
    try:
        with pytest.raises(BackgroundError, match="timed out"):
            await adapter._common_call(lambda _client: anyio.sleep(5))
    finally:
        await adapter.close()


async def test_awa_found_none(awa: AwaAdapter) -> None:
    """A call that answers no job is no job."""

    async def call(_client: Any) -> None:
        return None

    assert await awa._common_found(call) is None


async def test_awa_ping(queue_settings: QueueSettings) -> None:
    """One query on the queue's own database; closed, nothing answers."""
    async with AwaAdapter(queue_settings) as adapter:
        await adapter.ping()
    with pytest.raises(PingError, match=r"^awa: BackgroundError: awa adapter is not connected"):
        await adapter.ping()
