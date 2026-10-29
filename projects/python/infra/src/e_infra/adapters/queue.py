"""adapters/queue: the durable engines behind `BackgroundPort`, by QUEUE_ENGINE.

The composition root that runs the background picks one — `Background(ENGINES[st.queue.engine](st.queue), slots)` —:
PgQueuer by default, awa one setting away. Both keep their tables in the queue's own database, apart from each other's,
so switching engines needs no migration; jobs in flight on the other engine are not carried over."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from e_infra.adapters.awa import AwaAdapter
from e_infra.adapters.pgqueuer import PgqueuerAdapter
from e_infra.infra.config.queue import QueueEngine

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e_infra.infra.background import BackgroundPort
    from e_infra.infra.config.queue import QueueSettings

ENGINES: Final[Mapping[QueueEngine, Callable[[QueueSettings], BackgroundPort]]] = MappingProxyType(
    {QueueEngine.AWA: AwaAdapter, QueueEngine.PGQUEUER: PgqueuerAdapter}
)
