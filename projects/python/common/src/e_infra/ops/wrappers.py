"""ops/wrappers: agnostic measuring wrappers — scope a block, read what it cost.

Every wrapper is a context manager, sync and async alike (`with` works inside coroutines: the
measure is the block, not the event loop). `LatencyWrapper` reads the monotonic nanosecond clock
once on entry and once on exit; inside the block `ms` is the live elapsed time, after the block it
is frozen — so a failure path can report how long it ran before raising."""

import time
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from types import TracebackType

NS_PER_MS: float = 1_000_000.0


##### TYPES #####
class LatencyWrapper:
    """Wall latency of a block in milliseconds: live while open, frozen once closed."""

    __slots__ = ("_started", "_stopped")

    def __init__(self) -> None:
        self._started: int = 0
        self._stopped: int | None = None

    def __enter__(self) -> Self:
        self._started = time.perf_counter_ns()
        self._stopped = None
        return self

    def __exit__(
        self, _exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: TracebackType | None
    ) -> None:
        self._stopped = time.perf_counter_ns()

    ############################################################

    @property
    def ms(self) -> float:
        """Elapsed milliseconds: up to now while the block runs, up to the exit once it closed."""
        ### the ternary picks the clock end: the live reading inside the block, the frozen one after it.
        end = time.perf_counter_ns() if self._stopped is None else self._stopped
        return (end - self._started) / NS_PER_MS
