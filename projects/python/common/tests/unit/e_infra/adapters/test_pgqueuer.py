"""The `BackgroundPort` contract, held by PgQueuer (the default) and awa alike; then PgQueuer's own recovery."""

from typing import TYPE_CHECKING, Any

import anyio
import asyncpg
import pytest

from e_infra.adapters import pgqueuer
from e_infra.adapters.base import PingError
from e_infra.adapters.pgqueuer import PgqueuerAdapter
from e_infra.infra.background import BackgroundError, BackgroundPort, BackgroundState
from e_infra.infra.config.base import Secret
from unit.e_infra.conftest import running, settled

if TYPE_CHECKING:
    from collections.abc import Callable

    from e_infra.adapters.awa import AwaAdapter
    from e_infra.infra.background import BackgroundHandler
    from unit.e_infra.adapters.conftest import Flaky, Hang

pytestmark = pytest.mark.db


##### CONTRACT — the same on every durable engine #####
async def test_pgqueuer_complete(port: AwaAdapter | PgqueuerAdapter, queue: str, handler: BackgroundHandler) -> None:
    """A job runs once and completes; its args and its last snapshot outlive it."""
    async with port:
        port.register("reported", queue, handler)
        await port.start({queue: 1})
        job = await port.enqueue("reported", {"ids": (1, 2)}, queue=queue, attempts=1)
        done = await settled(port, job.id)
    assert isinstance(port, BackgroundPort)
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
    port: AwaAdapter | PgqueuerAdapter,
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


async def test_pgqueuer_cancel_running(port: AwaAdapter | PgqueuerAdapter, queue: str, hang: Hang) -> None:
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
    port: AwaAdapter | PgqueuerAdapter, queue: str, handler: BackgroundHandler, hang: Hang
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


async def test_pgqueuer_jobs(port: AwaAdapter | PgqueuerAdapter, queue: str, handler: BackgroundHandler) -> None:
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
async def test_pgqueuer_ping(engine: PgqueuerAdapter) -> None:
    """One query on its pool; not connected, the ping says so."""
    with pytest.raises(PingError, match="not connected"):
        await engine.ping()
    async with engine:
        await engine.ping()


async def test_pgqueuer_connect_unreachable(engine: PgqueuerAdapter) -> None:
    down = PgqueuerAdapter(engine._conf.model_copy(update={"dsn": Secret("postgresql://postgres:x@127.0.0.1:9/none")}))
    with pytest.raises(BackgroundError):
        await down.connect()


@pytest.mark.parametrize(
    ("failure", "message"),
    [(asyncpg.InterfaceError("pool is closing"), "pool is closing"), (None, "timed out after")],
    ids=["refused", "slow"],
)
async def test_pgqueuer_call_outage(
    engine: PgqueuerAdapter, monkeypatch: pytest.MonkeyPatch, failure: Exception | None, message: str
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
        with pytest.raises(PingError, match=message):
            await engine.ping()


async def test_pgqueuer_lost_job(
    engine: PgqueuerAdapter, monkeypatch: pytest.MonkeyPatch, queue: str, handler: BackgroundHandler
) -> None:
    async def nothing(_: PgqueuerAdapter, __: str) -> None:
        return None

    async with engine:
        engine.register("reported", queue, handler)
        monkeypatch.setattr(PgqueuerAdapter, "job", nothing)
        with pytest.raises(BackgroundError, match="lost a job"):
            await engine.enqueue("reported", {}, queue=queue, attempts=1)


async def test_pgqueuer_close_bounded(engine: PgqueuerAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
    """A drain that never ends does not hold the close: past its bound it is an outage, and the pool is let go."""

    async def never(_: PgqueuerAdapter) -> None:
        await anyio.sleep_forever()

    await engine.connect()
    monkeypatch.setattr(PgqueuerAdapter, "_close_drain", never)
    with anyio.fail_after(10), pytest.raises(BackgroundError, match="close timed out"):
        await engine.close()
    with pytest.raises(PingError, match="not connected"):
        await engine.ping()


async def test_pgqueuer_manager_restarted(
    engine: PgqueuerAdapter, monkeypatch: pytest.MonkeyPatch, queue: str, handler: BackgroundHandler
) -> None:
    """A manager that dies — its connection gone — is started again after RESTART, until close."""
    calls: list[str] = []
    again = anyio.Event()

    async def dies(self: PgqueuerAdapter, name: str, _slots: int) -> None:
        calls.append(name)
        match len(calls):
            case 1:
                msg = "gone"
                raise ConnectionResetError(msg)
            case _:
                again.set()
                await self._closing.wait()

    monkeypatch.setattr(pgqueuer, "RESTART", 0.05)
    monkeypatch.setattr(PgqueuerAdapter, "_start_manage", dies)
    with anyio.fail_after(10):
        async with engine:
            engine.register("reported", queue, handler)
            await engine.start({queue: 1})
            await again.wait()
    assert calls == [queue, queue]
