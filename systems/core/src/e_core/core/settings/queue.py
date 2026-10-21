"""core/settings/queue: the durable job queue — a Postgres database of its own, apart from the service's data (QUEUE_*)."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_core.core.settings.base import BaseSettings, Secret


class QueueSettings(BaseSettings):
    """QUEUE_DSN — the queue's dedicated database on the local ParadeDB, `<service>_background` (`app_background` by
    default; created at startup when missing) — one per service, two sharing one would share queue names;
    QUEUE_POOL — connections held (awa's workers, claimers and maintenance leader share them: below 6 a started
    runtime deadlocks on shutdown); QUEUE_POLL — how often an idle worker looks for work, and a running one for its
    cancel; QUEUE_DRAIN — how long shutdown waits for in-flight jobs; QUEUE_TIMEOUT — how long connecting may take
    before work falls back to memory."""

    model_config = SettingsConfigDict(env_prefix="QUEUE_")

    dsn: Secret = Secret("postgresql://postgres:postgres@127.0.0.1:45011/app_background")
    pool: int = Field(default=10, ge=6)
    poll: timedelta = timedelta(milliseconds=200)
    drain: timedelta = timedelta(seconds=5)
    timeout: timedelta = timedelta(seconds=5)
