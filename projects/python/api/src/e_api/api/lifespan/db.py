"""api.lifespan.db: create every database the settings name, when missing, before any edge connects to one.

Each database is a row: its concern, and the settings whose DSN names it — the service's own (POSTGRES_DSN, default
`app` on the local ParadeDB); any new database is one more row. Each is created on its server's maintenance database
by the psqlpy driver, the rows in order. One that cannot be reached or created is a warning, never a crash here: an
edge on a missing database fails loudly where it connects. Nothing is written to the graph."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager

from litestar import Litestar
from pydantic import PostgresDsn, Secret

from e_api.infra.errors import DatabaseError
from e_api.infra.logger import logger
from e_api.infra.settings import settings as st
from e_api.providers.drivers.database.psqlpy import PsqlpyDriver


##### ROWS #####
def databases() -> Mapping[str, Secret[PostgresDsn]]:
    """Every database the service needs, by concern: its DSN."""
    return {"app": st.POSTGRES_DSN}


async def provision(concern: str, dsn: Secret[PostgresDsn]) -> bool:
    """Whether the concern's database was created now; a failure is warned of and reads as not created."""
    try:
        return await PsqlpyDriver(dsn=dsn, pool=st.POSTGRES_POOL, timeout=st.POSTGRES_TIMEOUT).provision()
    except DatabaseError as error:
        logger.warning("database not provisioned", concern=concern, error=str(error), step="START")
        return False


@asynccontextmanager
async def lifespan(_app: Litestar) -> AsyncGenerator[None]:
    """Provision each database, then hand over: the edges open on databases that exist."""
    created = [concern for concern, dsn in databases().items() if await provision(concern, dsn)]
    logger.info("databases ready", created=created, step="START")
    yield
