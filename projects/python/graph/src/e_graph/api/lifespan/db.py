"""api.lifespan.db: create every database the settings name, when missing, before any provider connects to one.

Each database is a row: its concern, and the settings whose DSN names it — the background queue (QUEUE_DSN, default
`app_background` on the local ParadeDB); a service that keeps its data in Postgres adds
`"app": st.providers.drivers.database.psqlpy`, and any
new database is one more row. Each is created on its server's maintenance database by the postgres driver, the rows
in order. One that cannot be reached or created is a warning, never a crash here: the background falls back to
memory, a provider on a missing database fails loudly where it connects. Nothing is written to the graph."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from litestar import Litestar

from infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from infra.errors import DatabaseError
from infra.logger import logger
from infra.settings import settings as st
from providers.drivers.database.psqlpy import PsqlpyDriver


##### ROWS #####
def databases() -> Mapping[str, PsqlpySettings]:
    """Every database the service needs, by concern; read on call, so the settings stay lazy."""
    queue = st.providers.drivers.queue.awa
    return {"background": PsqlpySettings(dsn=queue.dsn, timeout=queue.timeout)}


async def provision(concern: str, settings: PsqlpySettings) -> bool:
    """Whether the concern's database was created now; a failure is warned of and reads as not created."""
    try:
        return await PsqlpyDriver(settings).provision()
    except DatabaseError as error:
        logger.warning("database not provisioned", concern=concern, error=str(error), step="START")
        return False


@asynccontextmanager
async def lifespan(_app: Litestar) -> AsyncIterator[None]:
    """Provision each database, then hand over: the providers open on databases that exist."""
    created = [concern for concern, settings in databases().items() if await provision(concern, settings)]
    logger.info("databases ready", created=created, step="START")
    yield
