"""tests/unit/e_infra/providers/drivers/queue/pgqueuer: the PgQueuer driver over an asyncpg driver that holds no
database and PgQueuer's own in-memory backend — the managers, retries and cron are the real ones."""

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import anyio
import asyncpg
import pytest
from pgqueuer.domain.types import JobId

from e_infra.infra.background import BackgroundState
from e_infra.infra.config.providers.drivers.queue.pgqueuer import PgqueuerSettings
from e_infra.infra.errors import QueueError
from e_infra.ports.queue import QueuePort, SchedulePort
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver
from e_infra.providers.drivers.queue.pgqueuer import MANY, ONE, RECORD, REPORT, SCHEMA, PgqueuerDriver
from support.pgqueuer import book_row
from unit.e_infra.conftest import until

if TYPE_CHECKING:
    from e_infra.infra.background import BackgroundRun
    from support.asyncpg import FakeAsyncpgServer
    from support.pgqueuer import FakePgqueuer
    from unit.e_infra.conftest import Logs

ROW_ONE = "WHERE id = $1"
ROW_MANY = "ORDER BY created DESC"


##### LIFECYCLE #####
async def test_pgqueuer_meets_both_ports(pgqueuer_driver: PgqueuerDriver) -> None:
    assert (isinstance(pgqueuer_driver, QueuePort), isinstance(pgqueuer_driver, SchedulePort)) == (True, True)


async def test_pgqueuer_open_installs_its_schema_and_the_books_on_the_drivers_pool(
    pgqueuer_driver: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs
) -> None:
    async with pgqueuer_driver:
        assert asyncpg_server.sql() == list(SCHEMA)
        assert asyncpg_server.dedicated == 0
    assert logs.at("info") == ["pgqueuer opened", "pgqueuer closed"]


async def test_pgqueuer_opens_no_pool_of_its_own(
    pgqueuer_driver: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    async with pgqueuer_driver:
        assert len(asyncpg_server.pools) == 1


async def test_pgqueuer_on_a_driver_that_never_opened_is_a_queue_error(
    pgqueuer_memory: FakePgqueuer, pgqueuer_settings: PgqueuerSettings, asyncpg_server: FakeAsyncpgServer
) -> None:
    driver = PgqueuerDriver(AsyncpgDriver(), pgqueuer_settings)
    with pytest.raises(QueueError, match="not open"):
        await driver.__aenter__()
    with pytest.raises(QueueError, match="not open"):
        await driver.start({"q": 1})
    assert not await driver.health()


async def test_pgqueuer_default_settings_come_from_the_composer(fake_db: AsyncpgDriver) -> None:
    assert PgqueuerDriver(fake_db)._conf == PgqueuerSettings()


async def test_pgqueuer_close_that_cannot_drain_is_a_queue_error(
    opened: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    async def never(_: PgqueuerDriver) -> None:
        await anyio.sleep_forever()

    monkeypatch.setattr(PgqueuerDriver, "_close_drain", never)
    opened._conf = opened._conf.model_copy(
        update={"drain": timedelta(milliseconds=20), "timeout": timedelta(milliseconds=20)}
    )
    with anyio.fail_after(5), pytest.raises(QueueError, match="close timed out"):
        await opened.__aexit__(None, None, None)
    assert logs.at("error") == ["pgqueuer close timed out"]
    assert not await opened.health()


##### HEALTH #####
async def test_pgqueuer_health_true_when_the_pool_answers(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    assert await opened.health()
    assert asyncpg_server.sql()[-1] == "SELECT 1"


async def test_pgqueuer_health_false_and_warned_before_it_opens(pgqueuer_driver: PgqueuerDriver, logs: Logs) -> None:
    assert not await pgqueuer_driver.health()
    assert logs.at("warning") == ["pgqueuer unhealthy"]


async def test_pgqueuer_health_false_and_warned_when_the_database_fails(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs
) -> None:
    asyncpg_server.failures["SELECT 1"] = asyncpg.InterfaceError("pool is closing")
    assert not await opened.health()
    assert "pgqueuer unhealthy" in logs.at("warning")


##### OUTAGES — the database failing under the queue is the queue's #####
async def test_pgqueuer_a_database_failure_is_a_queue_error_and_logged(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs
) -> None:
    asyncpg_server.failures[ONE] = asyncpg.PostgresConnectionError("server closed the connection")
    with pytest.raises(QueueError, match="server closed"):
        await opened.job("1")
    assert logs.at("error") == ["asyncpg failed", "pgqueuer database failed"]


async def test_pgqueuer_a_call_past_the_bound_is_a_queue_error(
    pgqueuer_driver: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs
) -> None:
    async with pgqueuer_driver:
        asyncpg_server.hang = ROW_ONE
        pgqueuer_driver._conf = pgqueuer_driver._conf.model_copy(update={"timeout": timedelta(milliseconds=50)})
        with pytest.raises(QueueError, match="timed out after"):
            await pgqueuer_driver.job("1")
    assert logs.at("error") == ["pgqueuer call timed out"]
    assert asyncpg_server.held == 0


##### THE PORT #####
async def test_pgqueuer_enqueue_books_the_job_in_the_same_transaction_and_answers_it(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, pgqueuer_memory: FakePgqueuer
) -> None:
    asyncpg_server.answers[ROW_ONE] = [book_row(1, args='{"sources": ["a"]}')]
    job = await opened.enqueue("reported", {"sources": ("a",)}, queue="q", attempts=3)
    assert (job.id, job.kind, job.queue, job.state, job.args) == (
        "1",
        "reported",
        "q",
        BackgroundState.AVAILABLE,
        {"sources": ["a"]},
    )
    assert (RECORD, (1, "reported", "q", json.dumps({"sources": ["a"]}), 3)) in asyncpg_server.statements
    assert asyncpg_server.transactions == ["begin", "commit"]
    assert list(pgqueuer_memory.queries._jobs) == [1]


async def test_pgqueuer_enqueue_of_a_job_the_book_lost_is_a_queue_error(opened: PgqueuerDriver) -> None:
    with pytest.raises(QueueError, match="lost a job"):
        await opened.enqueue("reported", {}, queue="q", attempts=1)


@pytest.mark.parametrize("job", ["nope", "", "1.5"], ids=["word", "empty", "float"])
async def test_pgqueuer_job_that_is_no_id_is_none_without_asking(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, job: str
) -> None:
    before = len(asyncpg_server.statements)
    assert await opened.job(job) is None
    assert len(asyncpg_server.statements) == before


BOOKED = {
    "running": ({"state": "running", "live": "picked", "picks": 0}, (BackgroundState.RUNNING, 1, False)),
    "retryable": (
        {"state": "retryable", "picks": 2, "errors": ["ValueError: bad"]},
        (BackgroundState.RETRYABLE, 2, False),
    ),
    "completed": (
        {"state": "completed", "picks": 1, "finished": datetime(2026, 10, 30, tzinfo=UTC)},
        (BackgroundState.COMPLETED, 1, True),
    ),
    "failed": (
        {"state": "failed", "picks": 3, "errors": ["a", "b"], "finished": datetime(2026, 10, 30, tzinfo=UTC)},
        (BackgroundState.FAILED, 3, True),
    ),
    "progress": ({"state": "available", "progress": '{"seen": 4}'}, (BackgroundState.AVAILABLE, 0, False)),
}


@pytest.mark.parametrize(("fields", "expected"), BOOKED.values(), ids=BOOKED.keys())
async def test_pgqueuer_job_as_the_port_shows_it(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, fields: dict[str, Any], expected: tuple[Any, ...]
) -> None:
    asyncpg_server.answers[ROW_ONE] = [book_row(9, **fields)]
    found = await opened.job("9")
    assert found is not None
    assert (found.state, found.attempt, found.finished is not None) == expected
    assert found.progress == (json.loads(fields["progress"]) if "progress" in fields else None)


async def test_pgqueuer_jobs_are_asked_by_kind_state_and_limit(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    asyncpg_server.answers[ROW_MANY] = [book_row(3), book_row(2)]
    listed = await opened.jobs(kind="reported", state=BackgroundState.AVAILABLE, limit=2)
    assert [job.id for job in listed] == ["3", "2"]
    assert asyncpg_server.statements[-1] == (MANY, ("reported", "available", 2))


async def test_pgqueuer_cancel_marks_a_queued_job_and_answers_it_as_the_book_has_it(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, pgqueuer_memory: FakePgqueuer
) -> None:
    asyncpg_server.answers[ROW_ONE] = [book_row(1)]
    await opened.enqueue("reported", {}, queue="q", attempts=1)
    asyncpg_server.answers[ROW_ONE] = [book_row(1, state="cancelled", last="canceled")]
    cancelled = await opened.cancel("1")
    assert cancelled is not None
    assert cancelled.state is BackgroundState.CANCELLED
    assert 1 not in pgqueuer_memory.queries._jobs
    assert await opened.cancel("nope") is None


##### RUNNING — the real managers, in memory #####
async def test_pgqueuer_a_started_queue_runs_the_handler_of_the_kind_and_books_progress(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    seen: list[dict[str, Any]] = []

    async def handler(run: BackgroundRun) -> None:
        seen.append({"job": run.job.id, "kind": run.job.kind, "args": run.job.args, "state": run.job.state})
        await run.report({"stage": "done"})

    asyncpg_server.answers[ROW_ONE] = [book_row(1)]
    opened.register("reported", "q", handler)
    await opened.start({"q": 1})
    await opened.enqueue("reported", {"n": 7}, queue="q", attempts=1)
    await until(lambda: bool(seen) and REPORT in asyncpg_server.sql(), seconds=5)
    assert seen == [{"job": "1", "kind": "reported", "args": {"n": 7}, "state": BackgroundState.RUNNING}]
    assert (REPORT, (1, json.dumps({"stage": "done"}))) in asyncpg_server.statements
    assert asyncpg_server.dedicated == 1
    await opened.__aexit__(None, None, None)
    assert asyncpg_server.dedicated == 0


async def test_pgqueuer_a_failing_attempt_with_attempts_left_runs_again(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    calls: list[int] = []

    async def flaky(run: BackgroundRun) -> None:
        calls.append(run.job.attempt)
        _ = len(calls) == 1 and flaky_fail()

    def flaky_fail() -> None:
        msg = "first attempt"
        raise RuntimeError(msg)

    asyncpg_server.answers[ROW_ONE] = [book_row(1)]
    opened.register("reported", "q", flaky)
    await opened.start({"q": 1})
    await opened.enqueue("reported", {}, queue="q", attempts=2)
    await until(lambda: len(calls) >= 2, seconds=5)
    assert calls == [1, 2]
    await opened.__aexit__(None, None, None)


async def test_pgqueuer_a_failing_last_attempt_is_not_run_again(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    calls: list[int] = []

    async def boom(run: BackgroundRun) -> None:
        calls.append(run.job.attempt)
        msg = "bad"
        raise RuntimeError(msg)

    asyncpg_server.answers[ROW_ONE] = [book_row(1)]
    opened.register("reported", "q", boom)
    await opened.start({"q": 1})
    await opened.enqueue("reported", {}, queue="q", attempts=1)
    await until(lambda: bool(calls), seconds=5)
    await anyio.sleep(0.3)
    assert calls == [1]
    await opened.__aexit__(None, None, None)


async def test_pgqueuer_a_cancelled_running_job_is_interrupted_where_it_awaits(
    opened: PgqueuerDriver, asyncpg_server: FakeAsyncpgServer, pgqueuer_memory: FakePgqueuer
) -> None:
    started, interrupted = anyio.Event(), anyio.Event()

    async def hang(_run: BackgroundRun) -> None:
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            interrupted.set()

    asyncpg_server.answers[ROW_ONE] = [book_row(1)]
    opened.register("reported", "q", hang)
    await opened.start({"q": 1})
    await opened.enqueue("reported", {}, queue="q", attempts=1)
    with anyio.fail_after(5):
        await started.wait()
    await pgqueuer_memory.queries.mark_job_as_cancelled([JobId(1)])
    await pgqueuer_memory.queries.notify_job_cancellation([JobId(1)])
    with anyio.fail_after(5):
        await interrupted.wait()
    await opened.__aexit__(None, None, None)


##### SUPERVISION — a manager that dies is started again on a fresh connection #####
async def test_pgqueuer_a_manager_that_dies_is_restarted_and_warned(
    opened: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
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

    monkeypatch.setattr(PgqueuerDriver, "_start_manage", dies)
    await opened.start({"q": 1})
    with anyio.fail_after(5):
        await again.wait()
    await opened.__aexit__(None, None, None)
    assert calls == ["q", "q"]
    assert logs.at("warning") == ["pgqueuer manager died, restarting"]


async def test_pgqueuer_a_scheduler_that_dies_is_restarted_and_warned(
    opened: PgqueuerDriver, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
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

    monkeypatch.setattr(PgqueuerDriver, "_start_schedule", dies)
    opened.schedule("clock", "0 0 1 1 *", fire)
    await opened.start({})
    with anyio.fail_after(5):
        await again.wait()
    await opened.__aexit__(None, None, None)
    assert len(calls) == 2
    assert logs.at("warning") == ["pgqueuer scheduler died, restarting"]


async def test_pgqueuer_a_schedule_is_claimed_in_the_backend_and_fires_here(opened: PgqueuerDriver) -> None:
    fired: list[int] = []

    async def fire() -> None:
        fired.append(1)

    opened.schedule("clock", "* * * * * *", fire)
    await opened.start({})
    await until(lambda: bool(fired), seconds=10)
    await opened.__aexit__(None, None, None)


@pytest.mark.parametrize(
    ("cron", "dialect"),
    [("*/5 * * * *", "*/5 * * * *"), ("*/5 * * * * *", "* * * * * */5")],
    ids=["five-fields", "six-fields-seconds-first"],
)
async def test_pgqueuer_dialect(cron: str, dialect: str) -> None:
    """Five fields go as they are; with seconds first, the seconds move to the end, where croniter reads them."""
    assert PgqueuerDriver.dialect(cron) == dialect
