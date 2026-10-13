"""e_tui.interact.ports: the contract an interactive object must answer to.

An object is born from its `Spec` plus whatever the walk already committed there (so a reverse
re-shows the answer), is itself a Textual widget the viewer can drop into a slot, and answers to
`commit`: the user's `Commit`, or `None` while the step is still unanswered. That is the whole deal —
the flow engine never learns what a switch is; the widgets never learn what a graph is. The two meet
only on this protocol."""

from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from e_tui.models.object import Commit

##### PORT #####


@runtime_checkable
class ObjectPort(Protocol):
    """A spec come alive: built from a spec and previous values, it commits answers."""

    def commit(self) -> Commit | None:
        """The user's answer, or None while there is nothing to answer with."""
        ...


Maker = Callable[[Any, Sequence[str]], ObjectPort]
