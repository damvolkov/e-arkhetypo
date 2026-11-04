"""infra/config/engines: the engines' knobs — a block per engine."""

from datetime import timedelta
from enum import StrEnum, auto

from pydantic import SecretStr

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class QueueEngine(StrEnum):
    """The durable queue behind the background, for a composition root that offers the choice."""

    AWA = auto()
    PGQUEUER = auto()


##### SETTINGS #####
class EngineSettings(BaseSettings):
    """The engines: who may sign in, which queue backs the background, how long a health check may take."""

    ### AUTH
    ### the key account ids are minted under (HMAC of a name): never rotated, or every account becomes someone new.
    AUTH_SECRET: SecretStr | None = None
    ### how long a key holds once issued (`P30D` in env); unset, until revoked.
    AUTH_TTL: timedelta | None = None
    AUTH_ADMIN: str = "admin"

    ### DISPATCH
    QUEUE_ENGINE: QueueEngine = QueueEngine.PGQUEUER
    ### how often at most a job's progress is written; the last snapshot is always written when it ends.
    QUEUE_THROTTLE: timedelta = timedelta(seconds=0.5)

    ### HEALTH
    ### how long one provider's health check may take before it counts as down, at startup and on `GET /ready`.
    PING_TIMEOUT: timedelta = timedelta(seconds=2)
