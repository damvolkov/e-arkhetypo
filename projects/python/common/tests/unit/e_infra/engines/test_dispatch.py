from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anyio
import pytest

from e_infra.engines.dispatch import DispatchEngine
from e_infra.infra.background import Background, BackgroundState
from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.queue.awa import AwaSettings
from e_infra.providers.drivers.queue.awa import AwaDriver
from unit.e_infra.conftest import Warnings, Works, outage, settled, until
from unit.e_infra.engines.conftest import build

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.background import BackgroundReporter
    from e_infra.providers.drivers.queue.pgqueuer import PgqueuerDriver


##### CONTRACT — the same on every queue #####


async def test_dispatch_completed(background: DispatchEngine, works: Works) -> None:
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


async def test_dispatch_failed(background: DispatchEngine) -> None:
    async with background:
        done = await settled(background, (await background.submit("boom", attempts=1)).id)
        assert (done.state, done.attempt, done.errors) == (BackgroundState.FAILED, 1, ("ValueError: bad",))


async def test_dispatch_cancel_running(background: DispatchEngine, works: Works) -> None:
    async with background:
        job = await background.submit("hang")
        await works.started.wait()
        await background.cancel(job.id)
        with anyio.fail_after(5):
            await works.interrupted.wait()
        done = await settled(background, job.id)
        assert (done.state, done.progress) == (BackgroundState.CANCELLED, {"stage": "discover"})


async def test_dispatch_cancel_settled(background: DispatchEngine) -> None:
    async with background:
        done = await settled(background, (await background.submit("ok")).id)
        again = await background.cancel(done.id)
        assert again is not None
        assert (again.state, again.progress) == (done.state, done.progress)
        assert (await background.cancel("4611686018427387904"), await background.job("unknown")) == (None, None)


async def test_dispatch_jobs(background: DispatchEngine) -> None:
    async with background:
        first = await settled(background, (await background.submit("ok")).id)
        second = await settled(background, (await background.submit("boom")).id)
        assert [job.id for job in await background.jobs(limit=2)] == [second.id, first.id]
        assert [job.id for job in await background.jobs(kind="ok", limit=1)] == [first.id]
        assert [job.id for job in await background.jobs(state=BackgroundState.FAILED, limit=1)] == [second.id]


async def test_dispatch_unregistered(background: DispatchEngine) -> None:
    async with background:
        with pytest.raises(KeyError):
            await background.submit("nobody")


##### MEMORY #####


async def test_dispatch_memory_alone(queue: str, works: Works, warnings: Warnings) -> None:
    async with build(None, queue, works) as dispatch:
        assert dispatch.engine == "memory"
        assert (await settled(dispatch, (await dispatch.submit("ok")).id)).state is BackgroundState.COMPLETED
    assert warnings.events == ["background in memory: jobs will not survive a restart"]


async def test_dispatch_throttled(queue: str) -> None:
    """Within the throttle only the first snapshot is written; the last one always is, once the work ends."""
    seen: list[Mapping[str, Any] | None] = []

    async def chatty(_args: Mapping[str, Any], report: BackgroundReporter) -> None:
        _ = [await report({"n": n}) for n in range(5)]
        seen.append((await dispatch.job(job.id) or job).progress)

    dispatch = DispatchEngine(None, Background(), {queue: 1}, throttle=60)
    dispatch.register("chatty", chatty, queue=queue)
    async with dispatch:
        job = await dispatch.submit("chatty")
        done = await settled(dispatch, job.id)
    assert (seen, done.progress) == ([{"n": 0}], {"n": 4})


##### COALESCE AND SCHEDULE #####


async def test_dispatch_coalesce(queue: str, works: Works) -> None:
    """Two slots held: a coalesced twin of a waiting job is that job, a different argument set is a job of its own."""
    async with build(None, queue, works) as dispatch:
        _ = [await dispatch.submit("hang"), await dispatch.submit("hang")]
        await works.started.wait()
        waiting = await dispatch.submit("ok", source="a")
        twin = await dispatch.submit("ok", coalesce=True, source="a")
        other = await dispatch.submit("ok", coalesce=True, source="b")
        _ = [await dispatch.cancel(job.id) for job in await dispatch.jobs(limit=10)]
    assert (twin.id == waiting.id, other.id == waiting.id) == (True, False)


@pytest.mark.parametrize(
    ("cron", "kind", "error"),
    [("not a cron", "ok", ValueError), ("* * * * *", "nobody", LookupError)],
    ids=["bad-cron", "no-work"],
)
async def test_dispatch_schedule_refused(
    queue: str, works: Works, cron: str, kind: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        build(None, queue, works).schedule("tick", cron, kind)


async def test_dispatch_schedule_fires(queue: str, works: Works) -> None:
    """A schedule with seconds puts its kind on the supervisor's clock: the job runs on its own, with its args."""
    dispatch = build(None, queue, works)
    dispatch.schedule("tick", "* * * * * *", "ok", source="clock")
    async with dispatch:
        await until(lambda: bool(works.calls))
    assert works.calls[0] == {"source": "clock"}


async def test_dispatch_schedule_failed(queue: str, works: Works, warnings: Warnings) -> None:
    """A tick that cannot submit is said and skipped, never the end of the clock."""
    dispatch = build(None, queue, works)
    dispatch.schedule("tick", "* * * * * *", "ok")
    dispatch._works.pop("ok")
    async with dispatch:
        await until(lambda: "schedule fired in vain" in warnings.events)


##### FALLBACK — the durable queue absent, unreachable or failing #####


@pytest.mark.integration
async def test_dispatch_durable(queue_settings: AwaSettings, queue: str, works: Works) -> None:
    async with build(AwaDriver(queue_settings), queue, works) as dispatch:
        job = await dispatch.submit("ok")
        assert (dispatch.engine, job.id.isdecimal()) == ("awa", True)
        assert (await settled(dispatch, job.id)).state is BackgroundState.COMPLETED


@pytest.mark.integration
async def test_dispatch_unreachable(queue_settings: AwaSettings, queue: str, works: Works, warnings: Warnings) -> None:
    missing = queue_settings.model_copy(update={"dsn": Secret(f"{queue_settings.dsn.get_secret_value()}_missing")})
    async with build(AwaDriver(missing), queue, works) as dispatch:
        job = await dispatch.submit("ok")
        assert (dispatch.engine, job.id.isdecimal()) == ("memory", False)
        assert (await settled(dispatch, job.id)).state is BackgroundState.COMPLETED
    assert warnings.events == ["background queue unreachable, in memory: jobs will not survive a restart"]


@pytest.mark.integration
async def test_dispatch_outage(queue_settings: AwaSettings, queue: str, works: Works, warnings: Warnings) -> None:
    """The durable database down after entry: new work runs in memory, its jobs stay readable, the durable ones read
    as unknown — every fall a warning; once it is back, work goes durable again."""
    async with build(AwaDriver(queue_settings), queue, works) as dispatch:
        durable = await settled(dispatch, (await dispatch.submit("ok")).id)
        async with outage(queue_settings.dsn.get_secret_value()):
            fallen = await dispatch.submit("ok")
            done = await settled(dispatch, fallen.id)
            listed = [job.id for job in await dispatch.jobs()]
            lost = (await dispatch.job(durable.id), await dispatch.cancel(durable.id))
        back = await dispatch.submit("ok")
    assert (fallen.id.isdecimal(), done.state, listed, lost) == (
        False,
        BackgroundState.COMPLETED,
        [fallen.id],
        (None, None),
    )
    assert back.id.isdecimal()
    assert warnings.events == [
        "background enqueue fell back to memory",
        "background queue unreadable",
        "background queue unreadable",
        "background queue unreadable",
    ]


##### HEALTH — the durable queue answering, memory standing in for it #####


async def test_dispatch_health_durable(durable: AwaDriver | PgqueuerDriver, queue: str, works: Works) -> None:
    """The durable queue entered answers; closed, it does not."""
    async with build(durable, queue, works) as dispatch:
        assert await dispatch.health()
    assert not await dispatch.health()


@pytest.mark.parametrize("unreachable", [False, True], ids=["absent", "unreachable"])
async def test_dispatch_health_memory(queue: str, works: Works, unreachable: bool) -> None:
    """No durable queue, or one unreachable on entry: memory runs the work, and health says jobs are not durable."""
    dead = AwaSettings(dsn=Secret("postgresql://u:p@127.0.0.1:1/x"), timeout=timedelta(seconds=1))
    async with build(AwaDriver(dead) if unreachable else None, queue, works) as dispatch:
        assert not await dispatch.health()
