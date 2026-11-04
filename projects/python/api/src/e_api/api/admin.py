"""api.admin: a fresh admin key, minted on the service's database without the API — the one door of the first key.

`POST /auth/accounts/{name}/token` needs the admin's key to hand out keys; the first one comes from here, on the service's
own host (`python -m e_api admin`): the database provisioned, the auth tables made, the admin's account rotated through
the same engine and driver the service runs — every earlier admin key revoked, the new one shown this once."""

from contextlib import AsyncExitStack

from engines.auth import AuthEngine
from infra.auth.models import Issued
from infra.logger import logger
from infra.settings import settings as st
from providers.drivers.auth.postgres import PostgresAuthDriver
from providers.drivers.database.psqlpy import PsqlpyDriver


async def mint() -> Issued:
    """The admin's account with one fresh key; the engine refuses (`AuthClosedError`) when no AUTH_SECRET is set."""
    async with AsyncExitStack() as stack:
        database = PsqlpyDriver(dsn=st.POSTGRES_DSN, pool=st.POSTGRES_POOL, timeout=st.POSTGRES_TIMEOUT)
        await database.provision()
        await stack.enter_async_context(database)
        store = await stack.enter_async_context(PostgresAuthDriver(database))
        engine = AuthEngine(store, secret=st.AUTH_SECRET, ttl=st.AUTH_TTL, admin=st.AUTH_ADMIN)
        issued = await engine.rotate(st.AUTH_ADMIN)
    logger.info("admin key minted", owner=issued.owner)
    return issued
