"""api.router.user: CRUD over the User DTO family — the key's access per route, three injection chains, msgspec at both edges.

Handlers are plain async functions with no knowledge of HTTP; the ROUTES tuple at the bottom is the
single place where routes, access and dependencies meet them — declarative registration, not decorators. Reading is an
account's (`Access.USER`), writing the admin's (`Access.ADMIN`): the caller is the token middleware's and the refusal the
guard's (`infra/auth`), the same at the MCP door, whose tools call these very handlers (`mcp/tools/user`).
"""

from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

import msgspec
from litestar import delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.handlers import HTTPRouteHandler
from litestar.params import FromPath, JSONBody

from e_api.api.deps import (
    USER_KEY,
    DepKey,
    caller,
    correlation_id,
    graph,
    load_record,
    store,
    to_user,
)
from e_api.api.security import SECURITY
from e_api.infra.auth.guard import OPT
from e_api.infra.auth.models import Access, Caller
from e_api.infra.logger import logger
from e_api.infra.state import State
from e_api.models.user import User, UserCreate, UserRecord, UserUpdate
from e_api.ports.store import StorePort


##### HANDLERS #####
async def create_user(
    data: JSONBody[UserCreate], graph: NamedDependency[State], store: NamedDependency[StorePort]
) -> User:
    """Hash through crypto, persist through the store — the credential never returns."""
    record = UserRecord(
        id=uuid4(),
        username=data.username,
        email=data.email,
        password_hash=await graph.crypto.hash_password(data.password),
        birth=data.birth,
        quota=data.quota,
        created=datetime.now(UTC),
    )
    await store.set(USER_KEY + str(record.id), msgspec.json.encode(record))
    return to_user(record)


async def list_users(store: NamedDependency[StorePort]) -> list[User]:
    """Collection read through the store's key prefix — streamed by the port, never materialized."""
    return [
        to_user(record)
        async for key in store.keys(USER_KEY)
        if (record := await load_record(store, key.removeprefix(USER_KEY))) is not None
    ]


async def read_user(
    user_id: FromPath[UUID],
    store: NamedDependency[StorePort],
    caller: NamedDependency[Caller],
    correlation_id: NamedDependency[str],
) -> User:
    """One record, read for the caller and the request's correlation id."""
    match await load_record(store, str(user_id)):
        case None:
            raise NotFoundException(detail="No such user")
        case record:
            logger.info("user read", user_id=str(user_id), by=caller.name, correlation=correlation_id)
            return to_user(record)


async def update_user(user_id: FromPath[UUID], data: JSONBody[UserUpdate], store: NamedDependency[StorePort]) -> User:
    """PATCH with the UNSET sentinel: absent fields stay, nulls apply."""
    match await load_record(store, str(user_id)):
        case None:
            raise NotFoundException(detail="No such user")
        case record:
            changes = {
                field.name: value
                for field in msgspec.structs.fields(data)
                if (value := getattr(data, field.name)) is not msgspec.UNSET
            }
            updated = msgspec.structs.replace(record, **changes)
            await store.set(USER_KEY + str(user_id), msgspec.json.encode(updated))
            return to_user(updated)


async def delete_user(user_id: FromPath[UUID], store: NamedDependency[StorePort]) -> None:
    """Idempotent removal — 204 whether or not it existed."""
    await store.delete(USER_KEY + str(user_id))


##### CHAINS — endpoint-local wiring: the enum owns the vocabulary #####
### litestar builds its signature model through msgspec with `str_keys=True`: only exact `str` keys survive,
### so `DepKey…value` is the single typed edge into litestar — never a raw string literal in the source.
GRAPH_DEPS: Final[dict[str, Provide]] = {DepKey.GRAPH.value: Provide(graph, sync_to_thread=False)}
STORE_DEPS: Final[dict[str, Provide]] = {
    **GRAPH_DEPS,
    DepKey.STORE.value: Provide(store, sync_to_thread=False),
}
READ_DEPS: Final[dict[str, Provide]] = {
    **STORE_DEPS,
    DepKey.CORRELATION_ID.value: Provide(correlation_id, sync_to_thread=False),
    DepKey.CALLER.value: Provide(caller, sync_to_thread=False),
}

##### ROUTES #####
ROUTES: Final[tuple[HTTPRouteHandler, ...]] = (
    post(
        "/users",
        name="user.create",
        status_code=201,
        tags=["users"],
        opt=OPT[Access.ADMIN],
        security=SECURITY,
        dependencies=STORE_DEPS,
    )(create_user),
    get("/users", name="user.list", tags=["users"], opt=OPT[Access.USER], security=SECURITY, dependencies=STORE_DEPS)(
        list_users
    ),
    get(
        "/users/{user_id:uuid}",
        name="user.read",
        tags=["users"],
        opt=OPT[Access.USER],
        security=SECURITY,
        dependencies=READ_DEPS,
    )(read_user),
    patch(
        "/users/{user_id:uuid}",
        name="user.update",
        tags=["users"],
        opt=OPT[Access.ADMIN],
        security=SECURITY,
        dependencies=STORE_DEPS,
    )(update_user),
    delete(
        "/users/{user_id:uuid}",
        name="user.delete",
        status_code=204,
        tags=["users"],
        opt=OPT[Access.ADMIN],
        security=SECURITY,
        dependencies=STORE_DEPS,
    )(delete_user),
)
