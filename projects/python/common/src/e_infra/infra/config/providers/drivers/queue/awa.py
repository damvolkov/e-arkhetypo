"""infra/config/providers/drivers/queue/awa: the awa queue — a Postgres database of its own, pool, poll and drain."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings, Secret


class AwaSettings(BaseSettings):
    """QUEUE_DSN — the queue's dedicated database on the local ParadeDB, `<service>_background` (`app_background` by
    default; created at startup when missing) — one per service, two sharing one would share queue names, password
    included; QUEUE_POOL — connections held, all opened at connect (awa's workers, claimers and maintenance leader share
    them: below 6 a started runtime deadlocks on shutdown); QUEUE_TIMEOUT — how long connecting may take before work
    falls back to memory; QUEUE_POLL — how often an idle worker looks for work, and a running one for its cancel;
    QUEUE_DRAIN — how long shutdown waits for in-flight jobs."""

    model_config = SettingsConfigDict(env_prefix="QUEUE_")

    dsn: Secret = Secret("postgresql://postgres:postgres@127.0.0.1:45011/app_background")
    pool: int = Field(default=10, ge=6)
    timeout: timedelta = timedelta(seconds=5)
    poll: timedelta = timedelta(milliseconds=200)
    drain: timedelta = timedelta(seconds=5)
