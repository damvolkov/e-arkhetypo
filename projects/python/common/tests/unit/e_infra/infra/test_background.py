"""tests/unit/e_infra/infra/background: the supervisor — jobs, retries, cancel, keep, reporter and clock, in process."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from e_infra.infra.background import (
    Background,
    BackgroundJob,
    BackgroundReport,
    BackgroundState,
    BackgroundTask,
)
from e_infra.infra.errors import QueueError
from unit.e_infra.conftest import Warnings, Works, settled, until

if TYPE_CHECKING:
    from collections.abc import Mapping

NOW: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)
QUEUE: Final[str] = "q"


async def supervisor(works: Works, *, keep: int = 1000) -> Background:
    """A supervisor with every scripted work registered on `QUEUE`, not yet entered."""
    background = Background(keep=keep)
    _ = [
        background.register(kind, QUEUE, lambda run, work=work: work(run.job.args, run.report))
        for kind, work in {"ok": works.ok, "boom": works.boom, "flaky": works.flaky, "hang": works.hang}.items()
    ]
    return background


async def test_background_retried(works: Works) -> None:
    """A failed attempt is retried while attempts remain; its error stays on the job."""
    async with await supervisor(works) as background:
        await background.start({QUEUE: 2})
        job = await background.enqueue("flaky", {}, queue=QUEUE, attempts=2)
        done = await settled(background, job.id)
    assert (done.state, done.attempt, done.errors) == (BackgroundState.COMPLETED, 2, ("ValueError: bad",))
    assert done.progress == {"stage": "smoke"}


async def test_background_cancel_queued(works: Works) -> None:
    """Both slots held: the third job waits, and a cancel settles it without its work ever running."""
    async with await supervisor(works) as background:
        await background.start({QUEUE: 2})
        holding = [await background.enqueue("hang", {}, queue=QUEUE, attempts=1) for _ in range(2)]
        await works.started.wait()
        waiting = await background.enqueue("ok", {}, queue=QUEUE, attempts=1)
        assert (await background.job(waiting.id) or waiting).state is BackgroundState.AVAILABLE
        cancelled = await background.cancel(waiting.id)
        _ = [await background.cancel(job.id) for job in holding]
    assert cancelled is not None
    assert (cancelled.state, works.calls) == (BackgroundState.CANCELLED, [])


async def test_background_exit_cancels(works: Works) -> None:
    async with await supervisor(works) as background:
        await background.start({QUEUE: 2})
        job = await background.enqueue("hang", {}, queue=QUEUE, attempts=1)
        await works.started.wait()
    assert (await background.job(job.id) or job).state is BackgroundState.CANCELLED


async def test_background_unentered(works: Works) -> None:
    with pytest.raises(QueueError, match="not entered"):
        await (await supervisor(works)).enqueue("ok", {}, queue=QUEUE, attempts=1)


async def test_background_unknown(works: Works) -> None:
    background = await supervisor(works)
    assert (await background.job("ghost"), await background.cancel("ghost")) == (None, None)


async def test_background_keep(works: Works) -> None:
    """Past `keep` jobs the oldest settled one leaves; a running one is never dropped."""
    async with await supervisor(works, keep=2) as background:
        await background.start({QUEUE: 4})
        first = await settled(background, (await background.enqueue("ok", {}, queue=QUEUE, attempts=1)).id)
        hanging = await background.enqueue("hang", {}, queue=QUEUE, attempts=1)
        await works.started.wait()
        last = await background.enqueue("ok", {}, queue=QUEUE, attempts=1)
        after = await background.enqueue("ok", {}, queue=QUEUE, attempts=1)
        assert await background.job(first.id) is None
        assert {job.id for job in await background.jobs(limit=10)} == {hanging.id, last.id, after.id}


async def test_background_entered_twice(works: Works) -> None:
    """Entering again keeps the task group the first entry made."""
    background = await supervisor(works)
    async with background:
        group = background._group
        await background.__aenter__()
        assert background._group is group


async def test_report_idle() -> None:
    """A reporter with nothing pending writes nothing on flush."""
    run = BackgroundTask(
        BackgroundJob(id="j", kind="ok", queue="q", state=BackgroundState.RUNNING, attempt=1, args={}, created=NOW)
    )
    await BackgroundReport(run, throttle=60).flush()
    assert run.job.progress is None


@pytest.mark.parametrize(
    ("cron", "after", "tick"),
    [
        ("* * * * *", datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC), datetime(2026, 1, 1, 0, 1, tzinfo=UTC)),
        ("*/10 * * * * *", datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC), datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)),
    ],
    ids=["five-fields", "six-fields-seconds-first"],
)
async def test_background_next_tick(cron: str, after: datetime, tick: datetime) -> None:
    assert Background.next_tick(cron, after) == tick


async def test_background_clock(works: Works) -> None:
    """A schedule is a clock task of the group: it fires every second until the supervisor exits."""
    fired: list[int] = []

    async def fire() -> None:
        fired.append(1)

    background = await supervisor(works)
    background.schedule("tick", "* * * * * *", fire)
    async with background:
        await background.start({QUEUE: 1})
        await until(lambda: len(fired) >= 2)


async def test_background_clock_survives_failure(works: Works, warnings: Warnings) -> None:
    """A fire that raises is said and skipped; the clock goes on to the next tick."""
    calls: list[int] = []

    async def fire() -> None:
        calls.append(1)
        msg = "no"
        raise RuntimeError(msg)

    background = await supervisor(works)
    background.schedule("tick", "* * * * * *", fire)
    async with background:
        await background.start({QUEUE: 1})
        await until(lambda: len(calls) >= 2)
    assert warnings.events[:2] == ["schedule fire failed", "schedule fire failed"]


async def test_background_progress_view(works: Works) -> None:
    """A work's progress is the job's, readable while it runs."""
    async with await supervisor(works) as background:
        await background.start({QUEUE: 1})
        job = await background.enqueue("hang", {}, queue=QUEUE, attempts=1)
        await works.started.wait()
        progress: Mapping[str, object] | None = (await background.job(job.id) or job).progress
        await background.cancel(job.id)
    assert progress == {"stage": "discover"}
