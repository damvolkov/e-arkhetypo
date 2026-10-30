"""The `QueuePort` contract, held by PgQueuer (the default) and awa alike; then PgQueuer's own recovery."""

from typing import TYPE_CHECKING, Any

import anyio
import asyncpg
import pytest

from e_infra.infra.background import BackgroundState
from e_infra.infra.config.base import Secret
from e_infra.infra.errors import QueueError
from e_infra.ports.queue import QueuePort, SchedulePort
from e_infra.providers.drivers.queue import pgqueuer
from e_infra.providers.drivers.queue.pgqueuer import PgqueuerDriver
from unit.e_infra.conftest import running, settled, until

if TYPE_CHECKING:
    from collections.abc import Callable

    from e_infra.infra.background import BackgroundHandler
    from e_infra.providers.drivers.queue.awa import AwaDriver
    from unit.e_infra.providers.drivers.conftest import Flaky, Hang

pytestmark = pytest.mark.db


##### CONTRACT — the same on every durable engine #####
async def test_pgqueuer_complete(port: AwaDriver | PgqueuerDriver, queue: str, handler: BackgroundHandler) -> None:
    """A job runs once and completes; its args and its last snapshot outlive it."""
    async with port:
        port.register("reported", queue, handler)
        await port.start({queue: 1})
        job = await port.enqueue("reported", {"ids": (1, 2)}, queue=queue, attempts=1)
        done = await settled(port, job.id)
    assert isinstance(port, QueuePort)
    assert (done.state, done.attempt, done.args, done.progress, done.errors) == (
        BackgroundState.COMPLETED,
        1,
        {"ids": [1, 2]},
        {"done": True},
        (),
    )


@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        ((2, 3), (BackgroundState.COMPLETED, 3, 2, 3)),
        ((5, 2), (BackgroundState.FAILED, 2, 2, 2)),
        ((1, 1), (BackgroundState.FAILED, 1, 1, 1)),
    ],
    ids=["recovers", "exhausted", "single"],
)
async def test_pgqueuer_retry(
    port: AwaDriver | PgqueuerDriver,
    queue: str,
    flaky: Callable[[int], Flaky],
    plan: tuple[int, int],
    expected: tuple[BackgroundState, int, int, int],
) -> None:
    """A failed attempt is retried until `attempts` are spent, each failure leaving its message: `plan` is (failures,
    attempts), `expected` (state, attempt, errors, runs)."""
    fails, attempts = plan
    handler = flaky(fails)
    async with port:
        port.register("flaky", queue, handler)
        await port.start({queue: 1})
        job = await port.enqueue("flaky", {}, queue=queue, attempts=attempts)
        done = await settled(port, job.id)
    assert (done.state, done.attempt, len(done.errors), handler.seen) == expected
    assert done.errors[0].startswith("RuntimeError: attempt 1 failed")


async def test_pgqueuer_cancel_running(port: AwaDriver | PgqueuerDriver, queue: str, hang: Hang) -> None:
    """A running job is cancelled where it awaits, and stays cancelled."""
    async with port:
        port.register("hang", queue, hang)
        await port.start({queue: 1})
        job = await port.enqueue("hang", {}, queue=queue, attempts=3)
        await running(port, job.id)
        await port.cancel(job.id)
        done = await settled(port, job.id)
        await anyio.sleep(1)
        again = await port.job(job.id)
    assert (done.state, hang.cancelled, again and again.state, done.progress) == (
        BackgroundState.CANCELLED,
        True,
        BackgroundState.CANCELLED,
        {"hanging": True},
    )


async def test_pgqueuer_cancel_queued(
    port: AwaDriver | PgqueuerDriver, queue: str, handler: BackgroundHandler, hang: Hang
) -> None:
    """A job waiting behind a busy slot is cancelled in storage and never runs; a settled job comes back unchanged;
    unknown ids are None."""
    async with port:
        port.register("hang", queue, hang)
        port.register("reported", queue, handler)
        await port.start({queue: 1})
        busy = await port.enqueue("hang", {}, queue=queue, attempts=1)
        await running(port, busy.id)
        job = await port.enqueue("reported", {}, queue=queue, attempts=1)
        cancelled = await port.cancel(job.id)
        again = await port.cancel(job.id)
        await port.cancel(busy.id)
        await settled(port, busy.id)
        await anyio.sleep(0.5)
        after = await port.job(job.id)
        unknown = (await port.job("987654321"), await port.cancel("987654321"), await port.job("nope"))
    assert (cancelled and cancelled.state, again and again.state, after and after.progress, unknown) == (
        BackgroundState.CANCELLED,
        BackgroundState.CANCELLED,
        None,
        (None, None, None),
    )


async def test_pgqueuer_jobs(port: AwaDriver | PgqueuerDriver, queue: str, handler: BackgroundHandler) -> None:
    """Jobs are listed newest first, filtered by kind and state."""
    async with port:
        port.register(f"{queue}a", queue, handler)
        port.register(f"{queue}b", queue, handler)
        await port.start({queue: 2})
        made = [await port.enqueue(f"{queue}a", {"n": n}, queue=queue, attempts=1) for n in range(3)]
        other = await port.enqueue(f"{queue}b", {}, queue=queue, attempts=1)
        _ = [await settled(port, job.id) for job in (*made, other)]
        listed = await port.jobs(kind=f"{queue}a", state=BackgroundState.COMPLETED, limit=10)
        none = await port.jobs(kind=f"{queue}a", state=BackgroundState.FAILED)
    assert ([job.args["n"] for job in listed], none) == ([2, 1, 0], [])


##### PGQUEUER — its own recovery, without the facade #####
async def test_pgqueuer_health(engine: PgqueuerDriver) -> None:
    """One query on its pool; not open, it does not answer."""
    assert not await engine.health()
    async with engine:
        assert await engine.health()


async def test_pgqueuer_satisfies_ports(engine: PgqueuerDriver) -> None:
    assert (isinstance(engine, QueuePort), isinstance(engine, SchedulePort)) == (True, True)


async def test_pgqueuer_open_unreachable(engine: PgqueuerDriver) -> None:
    down = PgqueuerDriver(engine._conf.model_copy(update={"dsn": Secret("postgresql://postgres:x@127.0.0.1:9/none")}))
    with pytest.raises(QueueError):
        await down.__aenter__()


@pytest.mark.parametrize(
    ("failure", "message"),
    [(asyncpg.InterfaceError("pool is closing"), "pool is closing"), (None, "timed out after")],
    ids=["refused", "slow"],
)
async def test_pgqueuer_call_outage(
    engine: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, failure: Exception | None, message: str
) -> None:
    """A call the database refuses, or does not answer within QUEUE_TIMEOUT, is the port's outage."""

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        match failure:
            case None:
                await anyio.sleep_forever()
            case error:
                raise error

    async with engine:
        monkeypatch.setattr(asyncpg.Pool, "fetchval", broken)
        with pytest.raises(QueueError, match=message):
            await engine._common_call(lambda pool: pool.fetchval("SELECT 1"))
        assert not await engine.health()


async def test_pgqueuer_lost_job(
    engine: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, queue: str, handler: BackgroundHandler
) -> None:
    async def nothing(_: PgqueuerDriver, __: str) -> None:
        return None

    async with engine:
        engine.register("reported", queue, handler)
        monkeypatch.setattr(PgqueuerDriver, "job", nothing)
        with pytest.raises(QueueError, match="lost a job"):
            await engine.enqueue("reported", {}, queue=queue, attempts=1)


async def test_pgqueuer_close_bounded(engine: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    """A drain that never ends does not hold the close: past its bound it is an outage, and the pool is let go."""

    async def never(_: PgqueuerDriver) -> None:
        await anyio.sleep_forever()

    await engine.__aenter__()
    monkeypatch.setattr(PgqueuerDriver, "_close_drain", never)
    with anyio.fail_after(10), pytest.raises(QueueError, match="close timed out"):
        await engine.__aexit__(None, None, None)
    assert not await engine.health()


async def test_pgqueuer_manager_restarted(
    engine: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, queue: str, handler: BackgroundHandler
) -> None:
    """A manager that dies — its connection gone — is started again after RESTART, until close."""
    calls: list[str] = []
    again = anyio.Event()

    async def dies(self: PgqueuerDriver, name: str, _slots: int) -> None:
        calls.append(name)
        match len(calls):
            case 1:
                msg = "gone"
                raise ConnectionResetError(msg)
            case _:
                again.set()
                await self._closing.wait()

    monkeypatch.setattr(pgqueuer, "RESTART", 0.05)
    monkeypatch.setattr(PgqueuerDriver, "_start_manage", dies)
    with anyio.fail_after(10):
        async with engine:
            engine.register("reported", queue, handler)
            await engine.start({queue: 1})
            await again.wait()
    assert calls == [queue, queue]


##### SCHEDULE — the clock is the database's #####
@pytest.mark.parametrize(
    ("cron", "dialect"),
    [("*/5 * * * *", "*/5 * * * *"), ("*/5 * * * * *", "* * * * * */5")],
    ids=["five-fields", "six-fields-seconds-first"],
)
async def test_pgqueuer_dialect(cron: str, dialect: str) -> None:
    """Five fields go as they are; with seconds first, the seconds move to the end, where croniter reads them."""
    assert PgqueuerDriver.dialect(cron) == dialect


async def test_pgqueuer_schedule_fires(engine: PgqueuerDriver, queue: str) -> None:
    """A schedule is claimed in the database and its fire runs in this process, tick after tick."""
    fired: list[int] = []

    async def fire() -> None:
        fired.append(1)

    engine.schedule(queue, "* * * * * *", fire)
    async with engine:
        await engine.start({queue: 1})
        await until(lambda: len(fired) >= 1, seconds=20)


async def test_pgqueuer_scheduler_restarted(
    engine: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, queue: str
) -> None:
    """A scheduler that dies — its connection gone — is started again after RESTART, until close."""
    calls: list[int] = []
    again = anyio.Event()

    async def dies(self: PgqueuerDriver) -> None:
        calls.append(1)
        match len(calls):
            case 1:
                msg = "gone"
                raise ConnectionResetError(msg)
            case _:
                again.set()
                await self._closing.wait()

    async def fire() -> None:
        """Never due in this test."""

    monkeypatch.setattr(pgqueuer, "RESTART", 0.05)
    monkeypatch.setattr(PgqueuerDriver, "_start_schedule", dies)
    engine.schedule(queue, "0 0 1 1 *", fire)
    with anyio.fail_after(10):
        async with engine:
            await engine.start({queue: 1})
            await again.wait()
    assert len(calls) == 2
