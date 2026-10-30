"""infra/config/providers/drivers/queue/pgqueuer: PgQueuer's pace — poll, drain, call bound, heartbeat and restart."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class PgqueuerSettings(BaseSettings):
    """The database is the `AsyncpgDriver` PgQueuer rides: its DSN and pool are `AsyncpgSettings`'. QUEUE_TIMEOUT — a
    call on the pool before work falls back to memory; QUEUE_POLL — how often an idle worker looks for work; QUEUE_DRAIN
    — how long shutdown waits for in-flight jobs; QUEUE_HEARTBEAT — PgQueuer re-picks a job whose heartbeat (sent every
    half of this) is older than it: a crashed worker's job is rescued after it, and a loop blocked for longer runs the
    job twice; QUEUE_RESTART — the pause before a dead manager is started again on a fresh connection."""

    model_config = SettingsConfigDict(env_prefix="QUEUE_")

    timeout: timedelta = timedelta(seconds=5)
    poll: timedelta = timedelta(milliseconds=200)
    drain: timedelta = timedelta(seconds=5)
    heartbeat: timedelta = Field(default=timedelta(seconds=30), gt=timedelta(0))
    restart: timedelta = timedelta(seconds=1)
