"""adapters/queue: the durable engines behind `BackgroundPort`, by QUEUE_ENGINE.

The composition root that runs the background picks one — `Background(ENGINES[st.queue.engine](st.queue), slots)` —:
PgQueuer by default, awa one setting away. Both keep their tables in the queue's own database, apart from each other's,
so switching engines needs no migration; jobs in flight on the other engine are not carried over."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from e_core.adapters.awa import AwaAdapter
from e_core.adapters.pgqueuer import PgqueuerAdapter
from e_core.core.settings.queue import QueueEngine

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e_core.core.background import BackgroundPort
    from e_core.core.settings.queue import QueueSettings

ENGINES: Final[Mapping[QueueEngine, Callable[[QueueSettings], BackgroundPort]]] = MappingProxyType(
    {QueueEngine.AWA: AwaAdapter, QueueEngine.PGQUEUER: PgqueuerAdapter}
)
