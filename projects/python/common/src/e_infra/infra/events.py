"""infra/events: events delivered in this process — subscribers by event type, none known to the publisher.

`subscribe(kind, handler)` binds a handler to an event type; `publish(event)` hands the event to a bounded stream and
returns: a slow listener delays the next delivery, never the publisher — until CAPACITY events wait, then publishing
waits too (backpressure, never an unbounded queue). One task delivers, in order, each event to every handler of its
type in subscription order; a handler that raises is logged and skipped, the others and the next events still go.

A producer depends on `EventsPort` alone — `MemoryEvents` is its in-process engine, a queue-backed one is another
adapter of the same port. The engine is entered by its lifespan: entering starts the delivery, leaving delivers what
is still waiting and stops."""

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Final, Protocol, Self, runtime_checkable

import anyio

from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from anyio.abc import TaskGroup

### events that may wait for delivery before publishing waits too.
CAPACITY: Final[int] = 1000

type EventsHandler = Callable[[Any], Awaitable[None]]


##### PORTS #####
@runtime_checkable
class EventsPort(Protocol):
    """What a producer may ask: announce one event, never waiting on a listener's work."""

    async def publish(self, event: object) -> None: ...


##### MEMORY #####
class MemoryEvents:
    """In-process events: subscribers by type, one ordered delivery task, a failing handler never the publisher's."""

    __slots__ = ("_group", "_handlers", "_receive", "_send")

    def __init__(self, capacity: int = CAPACITY) -> None:
        self._send, self._receive = anyio.create_memory_object_stream[Any](capacity)
        self._handlers: defaultdict[type, list[EventsHandler]] = defaultdict(list)
        self._group: TaskGroup | None = None

    ##### PRIVATE #####

    @staticmethod
    async def _start_one(handler: EventsHandler, event: object) -> None:
        try:
            await handler(event)
        except Exception as error:  # noqa: BLE001 — a listener's failure is its own, never the publisher's
            logger.warning("event handler failed", kind=type(event).__name__, error=f"{type(error).__name__}: {error}")

    async def _start_each(self, event: object) -> None:
        """One event to every handler of its type, in subscription order."""
        _ = [await self._start_one(handler, event) for handler in tuple(self._handlers.get(type(event), ()))]

    async def _start_deliver(self) -> None:
        ### a delivery is a loop by nature, as long as the process lives: a comprehension would keep one item per event.
        async with self._receive:
            async for event in self._receive:
                await self._start_each(event)

    ############################################################

    ##### PUBLIC #####

    def subscribe[T](self, kind: type[T], handler: Callable[[T], Awaitable[None]]) -> None:
        """Every event of `kind` delivered to `handler`, after the handlers subscribed before it."""
        self._handlers[kind].append(handler)

    async def publish(self, event: object) -> None:
        """Hand the event over for delivery; waits only when CAPACITY events already wait."""
        await self._send.send(event)

    async def __aenter__(self) -> Self:
        self._group = anyio.create_task_group()
        await self._group.__aenter__()
        self._group.start_soon(self._start_deliver)
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        ### closing the stream lets the delivery drain what waits, then end: the group exits once it has.
        await self._send.aclose()
        match self._group:
            case None:
                return
            case group:
                self._group = None
                await group.__aexit__(kind, error, trace)
