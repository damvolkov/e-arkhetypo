"""tests/unit/e_infra/providers/drivers/queue/awa_real: awa against a real Postgres — the contract both queues hold, and awa's outages."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anyio
import pytest
from awa import AwaError

from e_infra.infra.background import BackgroundState
from e_infra.infra.errors import ProviderError, QueueError
from e_infra.ports.queue import QueuePort, SchedulePort
from e_infra.providers.drivers.queue.awa import AwaDriver
from unit.e_infra.conftest import dsn, over, settled

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from e_infra.infra.background import BackgroundHandler, BackgroundRun

pytestmark = pytest.mark.integration


async def test_awa_port(awa: AwaDriver) -> None:
    assert isinstance(awa, QueuePort)


async def test_awa_enqueue(awa: AwaDriver, queue: str) -> None:
    job = await awa.enqueue("annotate", {"document": "d1", "names": ["lang"]}, queue=queue, attempts=1)
    assert job.id.isdecimal()
    assert (job.kind, job.queue, job.state, job.attempt) == ("annotate", queue, BackgroundState.AVAILABLE, 0)
    assert (job.args, job.progress, job.errors, job.finished) == ({"document": "d1", "names": ["lang"]}, None, (), None)
    assert await awa.job(job.id) == job


async def test_awa_enqueue_tuples(awa: AwaDriver, queue: str) -> None:
    """A struct's builtins keep their tuples; awa takes JSON types only, so they travel as lists."""
    job = await awa.enqueue("annotate", {"enrichers": ("deterministic",), "scope": None}, queue=queue, attempts=1)
    assert job.args == {"enrichers": ["deterministic"], "scope": None}


async def test_awa_jobs(awa: AwaDriver, queue: str) -> None:
    first = await awa.enqueue(f"{queue}-a", {}, queue=queue, attempts=1)
    second = await awa.enqueue(f"{queue}-b", {}, queue=queue, attempts=1)
    assert [job.id for job in await awa.jobs(kind=f"{queue}-a")] == [first.id]
    assert [job.id for job in await awa.jobs(kind=f"{queue}-b", state=BackgroundState.AVAILABLE)] == [second.id]
    assert await awa.jobs(kind=f"{queue}-b", state=BackgroundState.COMPLETED) == []


async def test_awa_cancel_queued(awa: AwaDriver, queue: str) -> None:
    job = await awa.enqueue("annotate", {}, queue=queue, attempts=1)
    cancelled = await awa.cancel(job.id)
    assert cancelled is not None
    assert (cancelled.state, cancelled.finished is not None) == (BackgroundState.CANCELLED, True)


@pytest.mark.parametrize("job", ["4611686018427387904", "0190a1b2c3d4e5f6a7b8c9d0e1f2a3b4"])
async def test_awa_unknown(awa: AwaDriver, job: str) -> None:
    """An id awa never issued, or one of another engine: None either way."""
    assert (await awa.job(job), await awa.cancel(job)) == (None, None)


async def test_awa_run_progress(awa: AwaDriver, queue: str) -> None:
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


async def test_awa_run_failed(awa: AwaDriver, queue: str) -> None:
    """The handler's own error, its first line: never the task group that watches it."""

    async def handler(_run: BackgroundRun) -> None:
        msg = "bad"
        raise ValueError(msg)

    awa.register("harvest", queue, handler)
    await awa.start({queue: 1})
    job = await awa.enqueue("harvest", {}, queue=queue, attempts=1)
    done = await settled(awa, job.id)
    assert (done.state, done.attempt, done.errors) == (BackgroundState.FAILED, 1, ("ValueError: bad",))


async def test_awa_cancel_running(awa: AwaDriver, queue: str) -> None:
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


async def test_awa_connect_missing(awa_conf: dict[str, Any]) -> None:
    missing = over(awa_conf, dsn=dsn(f"{awa_conf['dsn'].get_secret_value()}_missing"))
    with pytest.raises(QueueError, match="does not exist"):
        await AwaDriver(**missing).__aenter__()


async def test_awa_connect_timeout(awa_conf: dict[str, Any]) -> None:
    """A host that never answers: the connect gives up at QUEUE_TIMEOUT, not at the driver's own thirty seconds."""
    down = over(awa_conf, dsn=dsn("postgresql://postgres:postgres@127.0.0.1:1/x"), timeout=timedelta(milliseconds=300))
    with anyio.fail_after(5), pytest.raises(QueueError, match="timed out"):
        await AwaDriver(**down).__aenter__()


async def test_awa_unconnected(awa_conf: dict[str, Any]) -> None:
    with pytest.raises(QueueError, match="not open"):
        await AwaDriver(**awa_conf).job("1")


async def test_awa_close_twice(awa_conf: dict[str, Any], queue: str) -> None:
    adapter = AwaDriver(**awa_conf)
    await adapter.__aenter__()
    await adapter.__aenter__()
    assert (await adapter.enqueue("annotate", {}, queue=queue, attempts=1)).state == BackgroundState.AVAILABLE
    await adapter.__aexit__(None, None, None)
    await adapter.__aexit__(None, None, None)
    with pytest.raises(QueueError, match="not open"):
        await adapter.jobs()


async def test_awa_outage(awa_conf: dict[str, Any], queue: str) -> None:
    """The pool gone under the adapter: every call is an outage the facade can fall back from."""
    adapter = AwaDriver(**awa_conf)
    await adapter.__aenter__()
    job = await adapter.enqueue("annotate", {}, queue=queue, attempts=1)
    await adapter.client.close()
    with pytest.raises(QueueError):
        await adapter.enqueue("annotate", {}, queue=queue, attempts=1)
    with pytest.raises(QueueError):
        await adapter.job(job.id)
    with pytest.raises(QueueError):
        await adapter.cancel(job.id)
    with pytest.raises(QueueError):
        await adapter.jobs()


async def test_awa_found_propagates(awa: AwaDriver) -> None:
    """An awa error that is neither an outage nor an unknown id is the caller's: it propagates."""

    async def call(_client: Any) -> None:
        msg = "unique conflict"
        raise AwaError(msg)

    with pytest.raises(AwaError, match="unique conflict"):
        await awa._common_found(call)


async def test_awa_call_timeout(awa_conf: dict[str, Any]) -> None:
    """A call that outlasts QUEUE_TIMEOUT is an outage, not a hang."""
    adapter = AwaDriver(**over(awa_conf, timeout=timedelta(milliseconds=100)))
    await adapter.__aenter__()
    try:
        with pytest.raises(QueueError, match="timed out"):
            await adapter._common_call(lambda _client: anyio.sleep(5))
    finally:
        await adapter.__aexit__(None, None, None)


async def test_awa_found_none(awa: AwaDriver) -> None:
    """A call that answers no job is no job."""

    async def call(_client: Any) -> None:
        return None

    assert await awa._common_found(call) is None


async def test_awa_health(awa_conf: dict[str, Any]) -> None:
    """One query on the queue's own database; closed, nothing answers."""
    adapter = AwaDriver(**awa_conf)
    async with adapter:
        assert await adapter.health()
    with pytest.raises(ProviderError):
        await adapter.health()


async def test_awa_health_unreachable(awa_conf: dict[str, Any]) -> None:
    adapter = AwaDriver(**over(awa_conf, timeout=timedelta(seconds=1)))
    with pytest.raises(ProviderError):
        await adapter.health()


async def test_awa_keeps_no_clock(awa: AwaDriver) -> None:
    """awa binds no cron callback: the dispatch gives the clock to memory."""
    assert not isinstance(awa, SchedulePort)


async def test_awa_pool_held(
    awa_conf: dict[str, Any], queue: str, handler: BackgroundHandler, refuse: Callable[[], Awaitable[None]]
) -> None:
    """Connected, the pool is whole: a database that then refuses every new connection — a server out of slots — still
    runs a job to its end and lets the engine close."""
    with anyio.fail_after(20):
        async with AwaDriver(**awa_conf) as awa:
            await refuse()
            awa.register("reported", queue, handler)
            await awa.start({queue: 1})
            job = await awa.enqueue("reported", {}, queue=queue, attempts=1)
            done = await settled(awa, job.id)
    assert (done.state, done.progress) == (BackgroundState.COMPLETED, {"done": True})


@pytest.mark.usefixtures("stuck")
async def test_awa_close_bounded(awa_conf: dict[str, Any], queue: str, handler: BackgroundHandler) -> None:
    """A runtime that never stops does not hold the close: past QUEUE_DRAIN and QUEUE_TIMEOUT it is an outage, and
    the client is let go."""
    awa = AwaDriver(**over(awa_conf, timeout=timedelta(seconds=1)))
    await awa.__aenter__()
    awa.register("reported", queue, handler)
    await awa.start({queue: 1})
    with anyio.fail_after(10), pytest.raises(QueueError, match=r"^awa close timed out after "):
        await awa.__aexit__(None, None, None)
    with pytest.raises(ProviderError):
        await awa.health()
