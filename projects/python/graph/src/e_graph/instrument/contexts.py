"""instrument.contexts: the process-wide store of live runs' contexts, `system.instrument.contexts`.

A run opens `contexts[<id>]` and releases it when it closes. Not an infra `State` on purpose: sealing the app's graph
at startup freezes its shape, while this store must keep taking and dropping runs for the app's whole life."""

from collections.abc import Iterator, Mapping

from infra.state import State


class InstrumentContexts(Mapping[str, State]):
    """Every live run's context by run id: opened by a run, released when it closes."""

    __slots__ = ("_runs",)

    def __init__(self) -> None:
        self._runs: dict[str, State] = {}

    def __getitem__(self, run_id: str) -> State:
        return self._runs[run_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._runs)

    def __len__(self) -> int:
        return len(self._runs)

    ############################################################

    def open(self, run_id: str) -> State:
        """A fresh, empty context for a new run; an id already live is a wiring bug, never a silent share."""
        match run_id in self._runs:
            case True:
                msg = f"context {run_id!r} is already open: run ids are unique"
                raise ValueError(msg)
            case _:
                context = self._runs[run_id] = State()
                return context

    def drop(self, run_id: str) -> None:
        """Forget a run's context; dropping one already gone is a no-op."""
        self._runs.pop(run_id, None)
