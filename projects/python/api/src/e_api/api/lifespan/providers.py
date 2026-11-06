"""api.lifespan.providers: open every provider on one exit stack.

The concern owns its subtree as a typed section: `ProvidersState` names each provider by the port the
consumers (api.deps, routers, engines) may ask of it, so the graph carries contracts, not classes. Each
provider is a singleton built here, enters the shared `AsyncExitStack` in field order, and they close
in reverse when the stack unwinds. Every provider is one line per block — its import, its field, its
construction — so an exported project that drops a driver loses exactly those lines. Their health is the
engines' concern (`api/lifespan/engines`)."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, fields

from litestar import Litestar

from e_api.api.state import AppState
from e_api.infra.logger import logger
from e_api.infra.settings import settings as st
from e_api.ports.auth import AuthPort
from e_api.ports.database import DatabasePort
from e_api.ports.http import HTTPPort
from e_api.ports.provider import Provider
from e_api.ports.store import StorePort
from e_api.providers.drivers.auth.postgres import PostgresAuthDriver
from e_api.providers.drivers.database.psqlpy import PsqlpyDriver
from e_api.providers.drivers.http.wreq import WreqDriver
from e_api.providers.drivers.store.redis import RedisDriver
from e_api.providers.drivers.store.sqlite import SqliteDriver


##### SECTION #####
@dataclass(frozen=True, slots=True)
class ProvidersState:
    """The typed providers section: fields named by role, typed by the port the role speaks.

    `store` is the KV edge the app's records live on; `auth` is where accounts and keys live, over `database`, the
    service's one SQL pool; any further field is an optional provider the export may drop. The providers are
    singletons — factory machinery comes later."""

    store: StorePort
    redis: StorePort
    http: HTTPPort
    database: DatabasePort
    auth: AuthPort

    @property
    def named(self) -> Mapping[str, Provider]:
        """Every provider by its role, in field order — what the health engine surveys."""
        return {each.name: getattr(self, each.name) for each in fields(self)}


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open every provider on the exit stack, then mount the typed section under `system.providers`."""
    system = AppState.of(app).system
    async with AsyncExitStack() as stack:
        enter = stack.enter_async_context
        store = await enter(SqliteDriver(path=st.DB_PATH, timeout=st.DB_TIMEOUT))
        redis = await enter(RedisDriver(url=st.REDIS_URL, pool=st.REDIS_POOL, timeout=st.REDIS_TIMEOUT))
        http = await enter(
            WreqDriver(base_url=st.HTTP_BASE_URL, timeout=st.HTTP_TIMEOUT, agent=st.HTTP_AGENT, headers=st.HTTP_HEADERS)
        )
        database = await enter(PsqlpyDriver(dsn=st.POSTGRES_DSN, pool=st.POSTGRES_POOL, timeout=st.POSTGRES_TIMEOUT))
        auth = await enter(PostgresAuthDriver(database))
        providers = ProvidersState(store=store, redis=redis, http=http, database=database, auth=auth)
        system.providers = providers
        logger.info("providers ready", providers=sorted(providers.named), step="START")
        yield
    logger.info("providers closed", step="STOP")
