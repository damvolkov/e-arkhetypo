"""tests/unit/e_infra/infra/events: in-process events — each type to its subscribers, in order, a failing listener
never the publisher's nor the next one's, and what waits delivered on the way out."""

import anyio
import pytest
import structlog

from e_infra.infra import events as module
from e_infra.infra.events import EventsPort, MemoryEvents
from unit.e_infra.infra.conftest import Other, Saved


async def test_events_satisfy_their_port() -> None:
    async with MemoryEvents() as events:
        assert isinstance(events, EventsPort)


async def test_events_reach_their_subscribers_in_order() -> None:
    """Every event of a type goes to its handlers in subscription order; another type's do not see it."""
    seen: list[tuple[str, str]] = []

    async def first(event: Saved) -> None:
        seen.append(("first", event.name))

    async def second(event: Saved) -> None:
        seen.append(("second", event.name))

    async def other(event: Other) -> None:
        seen.append(("other", event.name))

    events = MemoryEvents()
    _ = [events.subscribe(Saved, handler) for handler in (first, second)]
    events.subscribe(Other, other)
    async with events:
        _ = [await events.publish(Saved(name)) for name in ("a", "b")]
        await events.publish(Other("c"))
        await events.publish(object())
    assert seen == [("first", "a"), ("second", "a"), ("first", "b"), ("second", "b"), ("other", "c")]


async def test_events_failing_listener_is_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """A handler that raises is logged once per event; the others, and the next events, still go."""
    kept: list[str] = []

    async def broken(event: Saved) -> None:
        raise RuntimeError(event.name)

    async def keep(event: Saved) -> None:
        kept.append(event.name)

    events = MemoryEvents()
    events.subscribe(Saved, broken)
    events.subscribe(Saved, keep)
    with structlog.testing.capture_logs() as logs:
        ### the module's logger may be cached from an earlier test (cache_logger_on_first_use): a fresh one is captured.
        monkeypatch.setattr(module, "logger", structlog.get_logger())
        async with events:
            _ = [await events.publish(Saved(name)) for name in ("a", "b")]
    failed = [log for log in logs if log["event"] == "event handler failed"]
    assert (kept, [log["error"] for log in failed]) == (["a", "b"], ["RuntimeError: a", "RuntimeError: b"])


async def test_events_published_before_entering_are_delivered() -> None:
    """The stream holds what was published before delivery started; leaving twice is harmless."""
    kept: list[str] = []

    async def keep(event: Saved) -> None:
        kept.append(event.name)

    events = MemoryEvents()
    events.subscribe(Saved, keep)
    await events.publish(Saved("early"))
    async with events:
        pass
    await events.__aexit__(None, None, None)
    assert kept == ["early"]


async def test_events_full_stream_holds_the_publisher() -> None:
    """Past CAPACITY, publishing waits: backpressure, never an unbounded queue."""
    gate = anyio.Event()

    async def hold(_event: Saved) -> None:
        await gate.wait()

    events = MemoryEvents(capacity=1)
    events.subscribe(Saved, hold)
    async with events:
        ### `a` is in the handler, `b` fills the stream: `c` has nowhere to go.
        _ = [await events.publish(Saved(name)) for name in ("a", "b")]
        with pytest.raises(TimeoutError), anyio.fail_after(0.05):
            await events.publish(Saved("c"))
        gate.set()
