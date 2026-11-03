"""infra/config/engines/dispatch: the dispatch engine — which durable queue backs the background, and its write pace."""

from datetime import timedelta
from enum import StrEnum, auto

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class QueueEngine(StrEnum):
    """The durable queue behind the background, for a composition root that offers the choice."""

    AWA = auto()
    PGQUEUER = auto()


class DispatchSettings(BaseSettings):
    """QUEUE_ENGINE — the durable queue the composition root builds, `pgqueuer` by default (`awa` one setting away);
    QUEUE_THROTTLE — how often at most a job's progress is written (the last snapshot is always written when it ends)."""

    model_config = SettingsConfigDict(env_prefix="QUEUE_")

    engine: QueueEngine = QueueEngine.PGQUEUER
    throttle: timedelta = timedelta(seconds=0.5)
