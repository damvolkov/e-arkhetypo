from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import anyio
import pytest

from e_core.adapters.awa import AwaAdapter
from e_core.adapters.base import PingError
from e_core.adapters.pgqueuer import PgqueuerAdapter
from e_core.conftest import outage, settled
from e_core.core.background import (
    Background,
    BackgroundError,
    BackgroundJob,
    BackgroundPort,
    BackgroundReport,
    BackgroundState,
    MemoryBackground,
    MemoryRun,
)
from e_core.core.conftest import Works, build
from e_core.core.settings.base import Secret
from e_core.core.settings.queue import QueueSettings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_core.core.background import BackgroundReporter
    from e_core.core.conftest import Warnings


NOW: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)


##### CONTRACT — the same on every engine #####


async def test_background_completed(background: Background, works: Works) -> None:
    async with background:
        queued = await background.submit("ok", source="s1", force=True)
        done = await settled(background, queued.id)
        assert (queued.state, queued.args) == (BackgroundState.AVAILABLE, {"source": "s1", "force": True})
        assert (done.state, done.attempt, done.progress) == (
            BackgroundState.COMPLETED,
            1,
            {"stage": "smoke", "seen": 2},
        )
        assert (done.errors, done.finished is not None, works.calls) == ((), True, [{"source": "s1", "force": True}])


async def test_background_failed(background: Background) -> None:
    async with background:
        done = await settled(background, (await background.submit("boom", attempts=1)).id)
        assert (done.state, done.attempt, done.errors) == (BackgroundState.FAILED, 1, ("ValueError: bad",))


async def test_background_cancel_running(background: Background, works: Works) -> None:
    async with background:
        job = await background.submit("hang")
        await works.started.wait()
        await background.cancel(job.id)
        with anyio.fail_after(5):
            await works.interrupted.wait()
        done = await settled(background, job.id)
        assert (done.state, done.progress) == (BackgroundState.CANCELLED, {"stage": "discover"})


async def test_background_cancel_settled(background: Background) -> None:
    async with background:
        done = await settled(background, (await background.submit("ok")).id)
        again = await background.cancel(done.id)
        assert again is not None
        assert (again.state, again.progress) == (done.state, done.progress)
        assert (await background.cancel("4611686018427387904"), await background.job("unknown")) == (None, None)


async def test_background_jobs(background: Background) -> None:
    async with background:
        first = await settled(background, (await background.submit("ok")).id)
        second = await settled(background, (await background.submit("boom")).id)
        assert [job.id for job in await background.jobs(limit=2)] == [second.id, first.id]
        assert [job.id for job in await background.jobs(kind="ok", limit=1)] == [first.id]
        assert [job.id for job in await background.jobs(state=BackgroundState.FAILED, limit=1)] == [second.id]


async def test_background_unregistered(background: Background) -> None:
    async with background:
        with pytest.raises(KeyError):
            await background.submit("nobody")


##### MEMORY #####


async def test_background_retried(queue: str, works: Works) -> None:
    """A failed attempt is retried while attempts remain; its error stays on the job."""
    async with build(None, queue, works) as background:
        done = await settled(background, (await background.submit("flaky", attempts=2)).id)
    assert (done.state, done.attempt, done.errors) == (BackgroundState.COMPLETED, 2, ("ValueError: bad",))
    assert done.progress == {"stage": "smoke"}


async def test_background_cancel_queued(queue: str, works: Works) -> None:
    """Both slots held: the third job waits, and a cancel settles it without its work ever running."""
    async with build(None, queue, works) as background:
        holding = [await background.submit("hang"), await background.submit("hang")]
        await works.started.wait()
        waiting = await background.submit("ok")
        assert (await background.job(waiting.id) or waiting).state is BackgroundState.AVAILABLE
        cancelled = await background.cancel(waiting.id)
        _ = [await background.cancel(job.id) for job in holding]
    assert cancelled is not None
    assert (cancelled.state, works.calls) == (BackgroundState.CANCELLED, [])


async def test_background_exit_cancels(queue: str, works: Works) -> None:
    async with build(None, queue, works) as background:
        job = await background.submit("hang")
        await works.started.wait()
    assert (await background.job(job.id) or job).state is BackgroundState.CANCELLED


async def test_background_memory_alone(queue: str, works: Works, warnings: Warnings) -> None:
    async with build(None, queue, works) as background:
        assert background.engine == "memory"
        assert (await settled(background, (await background.submit("ok")).id)).state is BackgroundState.COMPLETED
    assert warnings.events == ["background in memory: jobs will not survive a restart"]


async def test_background_throttled(queue: str) -> None:
    """Within the throttle only the first snapshot is written; the last one always is, once the work ends."""
    seen: list[Mapping[str, Any] | None] = []

    async def chatty(_args: Mapping[str, Any], report: BackgroundReporter) -> None:
        _ = [await report({"n": n}) for n in range(5)]
        seen.append((await background.job(job.id) or job).progress)

    background = Background(None, {queue: 1}, throttle=60)
    background.register("chatty", chatty, queue=queue)
    async with background:
        job = await background.submit("chatty")
        done = await settled(background, job.id)
    assert (seen, done.progress) == ([{"n": 0}], {"n": 4})


async def test_memory_port() -> None:
    assert isinstance(MemoryBackground(), BackgroundPort)


async def test_memory_unconnected() -> None:
    with pytest.raises(BackgroundError, match="not connected"):
        await MemoryBackground().enqueue("ok", {}, queue="q", attempts=1)


async def test_memory_unknown() -> None:
    memory = MemoryBackground()
    assert (await memory.job("ghost"), await memory.cancel("ghost")) == (None, None)


async def test_memory_keep(works: Works) -> None:
    """Past `keep` jobs the oldest settled one leaves; a running one is never dropped."""
    memory = MemoryBackground(keep=2)
    memory.register("ok", "q", lambda run: works.ok({}, run.report))
    memory.register("hang", "q", lambda run: works.hang({}, run.report))
    await memory.connect()
    await memory.connect()
    await memory.start({"q": 4})
    first = await settled(memory, (await memory.enqueue("ok", {}, queue="q", attempts=1)).id)
    hanging = await memory.enqueue("hang", {}, queue="q", attempts=1)
    await works.started.wait()
    last = await memory.enqueue("ok", {}, queue="q", attempts=1)
    after = await memory.enqueue("ok", {}, queue="q", attempts=1)
    assert await memory.job(first.id) is None
    assert {job.id for job in await memory.jobs(limit=10)} == {hanging.id, last.id, after.id}
    await memory.close()


async def test_report_idle() -> None:
    """A reporter with nothing pending writes nothing on flush."""
    run = MemoryRun(
        BackgroundJob(id="j", kind="ok", queue="q", state=BackgroundState.RUNNING, attempt=1, args={}, created=NOW)
    )
    await BackgroundReport(run, throttle=60).flush()
    assert run.job.progress is None


##### FALLBACK — the durable engine absent, unreachable or failing #####


@pytest.mark.db
async def test_background_durable(queue_settings: QueueSettings, queue: str, works: Works) -> None:
    async with build(AwaAdapter(queue_settings), queue, works) as background:
        job = await background.submit("ok")
        assert (background.engine, job.id.isdecimal()) == ("awa", True)
        assert (await settled(background, job.id)).state is BackgroundState.COMPLETED


@pytest.mark.db
async def test_background_unreachable(
    queue_settings: QueueSettings, queue: str, works: Works, warnings: Warnings
) -> None:
    missing = queue_settings.model_copy(update={"dsn": Secret(f"{queue_settings.dsn.get_secret_value()}_missing")})
    async with build(AwaAdapter(missing), queue, works) as background:
        job = await background.submit("ok")
        assert (background.engine, job.id.isdecimal()) == ("memory", False)
        assert (await settled(background, job.id)).state is BackgroundState.COMPLETED
    assert warnings.events == ["background engine unreachable, in memory: jobs will not survive a restart"]


@pytest.mark.db
async def test_background_outage(queue_settings: QueueSettings, queue: str, works: Works, warnings: Warnings) -> None:
    """The durable database down after entry: new work runs in memory, its jobs stay readable, the durable ones read
    as unknown — every fall a warning; once it is back, work goes durable again."""
    async with build(AwaAdapter(queue_settings), queue, works) as background:
        durable = await settled(background, (await background.submit("ok")).id)
        async with outage(queue_settings.dsn.get_secret_value()):
            fallen = await background.submit("ok")
            done = await settled(background, fallen.id)
            listed = [job.id for job in await background.jobs()]
            lost = (await background.job(durable.id), await background.cancel(durable.id))
        back = await background.submit("ok")
    assert (fallen.id.isdecimal(), done.state, listed, lost) == (
        False,
        BackgroundState.COMPLETED,
        [fallen.id],
        (None, None),
    )
    assert back.id.isdecimal()
    assert warnings.events == [
        "background enqueue fell back to memory",
        "background engine unreadable",
        "background engine unreadable",
        "background engine unreadable",
    ]


##### PING — the durable engine answering, memory standing in for it #####


async def test_background_ping_durable(durable: AwaAdapter | PgqueuerAdapter, queue: str, works: Works) -> None:
    """The durable engine entered answers; closed, its own ping says why not."""
    async with build(durable, queue, works) as background:
        await background.ping()
    with pytest.raises(PingError, match=rf"^{durable.name}: "):
        await background.ping()


@pytest.mark.parametrize("unreachable", [False, True], ids=["absent", "unreachable"])
async def test_background_ping_memory(queue: str, works: Works, unreachable: bool) -> None:
    """No durable engine, or one unreachable on entry: memory runs the work, and the ping says jobs are not durable."""
    dead = QueueSettings(dsn=Secret("postgresql://u:p@127.0.0.1:1/x"), timeout=timedelta(seconds=1))
    async with build(PgqueuerAdapter(dead) if unreachable else None, queue, works) as background:
        with pytest.raises(BackgroundError, match=r"^in memory: "):
            await background.ping()
