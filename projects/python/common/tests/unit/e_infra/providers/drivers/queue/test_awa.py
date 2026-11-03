"""tests/unit/e_infra/providers/drivers/queue/awa: the awa driver against a client that holds no database."""

import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anyio
import pytest
from awa import AwaError, Cancel
from awa import DatabaseError as AwaDatabaseError

from e_infra.infra.background import BackgroundState
from e_infra.infra.config.providers.drivers.queue.awa import AwaSettings
from e_infra.infra.errors import QueueError
from e_infra.ports.queue import QueuePort, SchedulePort
from e_infra.providers.drivers.queue import awa as awa_module
from e_infra.providers.drivers.queue.awa import REPORT, SCHEMA, AwaDriver
from support.awa import FakeAwaJob

if TYPE_CHECKING:
    from e_infra.infra.background import BackgroundHandler
    from support.awa import FakeAwaClient
    from unit.e_infra.conftest import Logs


##### LIFECYCLE #####
async def test_awa_meets_the_queue_port_and_keeps_no_clock(awa_driver: AwaDriver) -> None:
    assert (isinstance(awa_driver, QueuePort), isinstance(awa_driver, SchedulePort)) == (True, False)


async def test_awa_open_migrates_creates_its_tables_and_fills_the_pool(
    awa_driver: AwaDriver, awa_clients: list[FakeAwaClient], awa_settings: AwaSettings, logs: Logs
) -> None:
    async with awa_driver:
        [client] = awa_clients
        assert (client.dsn, client.max_connections) == (awa_settings.dsn.get_secret_value(), 6)
        assert "migrate" in client.calls
        assert client.sql() == list(SCHEMA)
        assert client.opened == len(SCHEMA) + awa_settings.pool
    assert (client.drained, client.closed) == (50, True)
    assert logs.at("info") == ["awa opened", "awa closed"]


async def test_awa_closing_twice_is_nothing(awa_driver: AwaDriver) -> None:
    async with awa_driver:
        pass
    await awa_driver.__aexit__(None, None, None)


async def test_awa_default_settings_come_from_the_composer(awa_clients: list[FakeAwaClient]) -> None:
    async with AwaDriver():
        assert awa_clients[0].max_connections == AwaSettings().pool


async def test_awa_unopened_calls_are_queue_errors(awa_driver: AwaDriver, handler: BackgroundHandler) -> None:
    with pytest.raises(QueueError, match="not open"):
        await awa_driver.job("1")
    with pytest.raises(QueueError, match="not open"):
        awa_driver.register("k", "q", handler)
    assert not await awa_driver.health()


@pytest.mark.parametrize("step", ["migrate", "transaction"])
async def test_awa_open_failing_is_a_queue_error_and_logged(
    awa_driver: AwaDriver, awa_script: dict[str, BaseException], logs: Logs, step: str
) -> None:
    awa_script[step] = AwaDatabaseError("connection refused")
    with pytest.raises(QueueError, match="connection refused"):
        await awa_driver.__aenter__()
    assert logs.at("error") == ["awa database failed"]


async def test_awa_client_that_never_connects_is_a_queue_error(
    awa_settings: AwaSettings, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    """awa's constructor connects synchronously: it runs off the loop and is abandoned at QUEUE_TIMEOUT."""

    def slow(dsn: str, max_connections: int = 10) -> None:
        time.sleep(0.4)

    monkeypatch.setattr(awa_module, "AsyncClient", slow)
    driver = AwaDriver(awa_settings.model_copy(update={"timeout": timedelta(milliseconds=50)}))
    with pytest.raises(QueueError, match="open timed out"):
        await driver.__aenter__()
    assert logs.at("error") == ["awa open failed"]


async def test_awa_close_that_never_returns_is_a_queue_error(
    awa_clients: list[FakeAwaClient], monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    async def never(timeout_ms: int = 0) -> None:
        await anyio.sleep_forever()

    driver = AwaDriver(AwaSettings(pool=6, drain=timedelta(milliseconds=20), timeout=timedelta(milliseconds=20)))
    await driver.__aenter__()
    monkeypatch.setattr(awa_clients[0], "shutdown", never)
    with pytest.raises(QueueError, match="close timed out"):
        await driver.__aexit__(None, None, None)
    assert logs.at("error") == ["awa close timed out"]
    assert not await driver.health()


##### HEALTH #####
async def test_awa_health_true_when_the_database_answers(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    assert await awa_opened.health()
    assert awa_clients[0].sql()[-1] == "SELECT 1"


async def test_awa_health_false_and_warned_when_the_database_is_gone(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient], logs: Logs
) -> None:
    awa_clients[0].failures["transaction"] = AwaDatabaseError("server closed the connection")
    assert not await awa_opened.health()
    assert "awa unhealthy" in logs.at("warning")


##### THE PORT #####
async def test_awa_register_binds_the_kind_and_start_hands_over_slots_and_poll(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    async def handler(_run: object) -> None:
        return None

    awa_opened.register("ingest", "docs", handler)
    await awa_opened.start({"docs": 2, "mail": 1})
    assert "ingest" in awa_clients[0].tasks
    assert awa_clients[0].started == [([("docs", 2), ("mail", 1)], 10)]


async def test_awa_enqueue_plain_json_and_the_job_as_the_port_shows_it(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    job = await awa_opened.enqueue("ingest", {"sources": ("a", "b")}, queue="docs", attempts=3)
    assert (job.id, job.kind, job.queue, job.state, job.args) == (
        "1",
        "ingest",
        "docs",
        BackgroundState.AVAILABLE,
        {"sources": ["a", "b"]},
    )
    assert awa_clients[0].jobs[1].args == {"sources": ["a", "b"]}


async def test_awa_job_carries_the_snapshot_and_errors(awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]) -> None:
    awa_clients[0].jobs[5] = FakeAwaJob(
        id=5,
        kind="ingest",
        queue="docs",
        args={},
        state="failed",
        attempt=2,
        errors=[{"error": "boom\ntrace"}],
        finalized_at="2026-10-30T10:00:00+00:00",
    )
    awa_clients[0].answers["background.progress"] = [{"job": 5, "snapshot": {"seen": 3}}]
    found = await awa_opened.job("5")
    assert found is not None
    assert (found.progress, found.errors, found.state, found.attempt) == (
        {"seen": 3},
        ("boom",),
        BackgroundState.FAILED,
        2,
    )
    assert found.finished is not None


@pytest.mark.parametrize("job", ["nope", "4611686018427387904", ""], ids=["not-decimal", "unknown", "empty"])
async def test_awa_job_of_nothing_is_none(awa_opened: AwaDriver, job: str) -> None:
    assert await awa_opened.job(job) is None


async def test_awa_job_unknown_to_awa_is_none_and_any_other_awa_error_propagates(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    awa_clients[0].failures["get_job"] = AwaError("job not found: 9")
    assert await awa_opened.job("9") is None
    awa_clients[0].failures["get_job"] = AwaError("migration pending")
    with pytest.raises(AwaError, match="migration pending"):
        await awa_opened.job("9")


async def test_awa_jobs_newest_first_filtered_with_their_snapshots(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    _ = [await awa_opened.enqueue(kind, {"n": n}, queue="q", attempts=1) for n, kind in enumerate(["a", "b", "a"])]
    awa_clients[0].answers["background.progress"] = [{"job": 3, "snapshot": {"done": True}}]
    listed = await awa_opened.jobs(kind="a", limit=5)
    assert [(job.id, job.progress) for job in listed] == [("3", {"done": True}), ("1", None)]


async def test_awa_cancel_a_queued_job_and_a_settled_one_unchanged(awa_opened: AwaDriver) -> None:
    queued = await awa_opened.enqueue("a", {}, queue="q", attempts=1)
    cancelled = await awa_opened.cancel(queued.id)
    again = await awa_opened.cancel(queued.id)
    assert cancelled is not None
    assert again is not None
    assert (cancelled.state, again.state) == (BackgroundState.CANCELLED, BackgroundState.CANCELLED)
    assert await awa_opened.cancel("nope") is None


##### ERRORS #####
async def test_awa_database_failure_is_a_queue_error_and_logged(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient], logs: Logs
) -> None:
    awa_clients[0].failures["insert"] = AwaDatabaseError("server closed the connection")
    with pytest.raises(QueueError, match="server closed"):
        await awa_opened.enqueue("a", {}, queue="q", attempts=1)
    assert logs.at("error") == ["awa database failed"]


async def test_awa_call_past_the_bound_is_a_queue_error(
    awa_settings: AwaSettings, awa_clients: list[FakeAwaClient], monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    driver = AwaDriver(awa_settings.model_copy(update={"timeout": timedelta(milliseconds=50)}))
    async with driver:

        async def never(*_args: Any, **_kwargs: Any) -> None:
            await anyio.sleep_forever()

        monkeypatch.setattr(awa_clients[0], "insert", never)
        with pytest.raises(QueueError, match="timed out after"):
            await driver.enqueue("a", {}, queue="q", attempts=1)
    assert logs.at("error") == ["awa call timed out"]


##### THE HANDLER A JOB RUNS #####
async def test_awa_run_reports_progress_into_the_driver_table(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    async def handler(run: Any) -> None:
        await run.report({"seen": 1})

    awa_opened.register("ingest", "docs", handler)
    job = FakeAwaJob(id=7, kind="ingest", queue="docs", args={"n": 1})
    assert await awa_clients[0].tasks["ingest"](job) is None
    assert REPORT in awa_clients[0].sql()
    assert awa_clients[0].statements[-1][1] == (7, json.dumps({"seen": 1}))


async def test_awa_run_that_fails_raises_the_handlers_own_error(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    async def handler(_run: Any) -> None:
        msg = "bad"
        raise ValueError(msg)

    awa_opened.register("harvest", "docs", handler)
    with pytest.raises(ValueError, match="bad"):
        await awa_clients[0].tasks["harvest"](FakeAwaJob(id=1, kind="harvest", queue="docs", args={}))


async def test_awa_run_of_a_job_cancelled_meanwhile_settles_as_cancelled(
    awa_opened: AwaDriver, awa_clients: list[FakeAwaClient]
) -> None:
    job = FakeAwaJob(id=2, kind="hang", queue="docs", args={})

    async def handler(_run: Any) -> None:
        job.cancelled = True
        await anyio.sleep_forever()

    awa_opened.register("hang", "docs", handler)
    with anyio.fail_after(2):
        settled = await awa_clients[0].tasks["hang"](job)
    assert isinstance(settled, Cancel)
