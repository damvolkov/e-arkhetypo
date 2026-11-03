"""e_api.mcp.tools.user: the user records as tools — the twin of `api/router/user`, whose handlers they call.

Reading is an account's (`Access.USER`), writing the admin's (`Access.ADMIN`), as the routes declare; the refusal of a
missing key or a key short of the access is the guard's, the same words as the API's. A record that is not there is the
route's own 404, answered as the tool's error."""

from typing import Final

import msgspec
from litestar.di import NamedDependency
from litestar.handlers import HTTPRouteHandler
from litestar.params import JSONBody

from e_api.api.router import user as router
from e_api.mcp.models import NoArgs, UserArgs, UserUpdateArgs
from e_api.mcp.refusals import REFUSALS
from e_api.models.user import User, UserCreate, UserUpdate
from infra.auth.models import Access, Caller
from infra.mcp.models import MCPTool
from infra.state import State
from ports.store import StorePort

##### TOOLS — what a client is told #####
LIST: Final = MCPTool(
    name="api_user_list",
    title="List users",
    description="Every user record: id, username, email, birth, quota, created. Needs an account's key.",
)
READ: Final = MCPTool(
    name="api_user_read",
    title="Read a user",
    description="One user record by `user_id`. Needs an account's key.",
)
CREATE: Final = MCPTool(
    name="api_user_create",
    title="Create a user",
    description="Create a user record; the password is hashed and never returned. Returns the record. Needs the admin's key.",
    read_only=False,
)
UPDATE: Final = MCPTool(
    name="api_user_update",
    title="Update a user",
    description=(
        "Change a user record by `user_id`: a field left out stays, `null` sets it to null. Returns the record. "
        "Needs the admin's key."
    ),
    read_only=False,
)
DELETE: Final = MCPTool(
    name="api_user_delete",
    title="Delete a user",
    description="Delete a user record by `user_id`; one already gone is no error. Needs the admin's key.",
    read_only=False,
    destructive=True,
)


##### HANDLERS #####
async def listed(data: JSONBody[NoArgs], store: NamedDependency[StorePort]) -> list[User]:  # noqa: ARG001 — the registry reads a tool's arguments off `data`
    return await router.list_users(store)


async def read(
    data: JSONBody[UserArgs],
    store: NamedDependency[StorePort],
    caller: NamedDependency[Caller],
    correlation_id: NamedDependency[str],
) -> User:
    return await router.read_user(data.user_id, store, caller, correlation_id)


async def create(data: JSONBody[UserCreate], graph: NamedDependency[State], store: NamedDependency[StorePort]) -> User:
    return await router.create_user(data, graph, store)


async def update(data: JSONBody[UserUpdateArgs], store: NamedDependency[StorePort]) -> User:
    changes = {
        field.name: value
        for field in msgspec.structs.fields(data)
        if field.name != "user_id" and (value := getattr(data, field.name)) is not msgspec.UNSET
    }
    return await router.update_user(data.user_id, UserUpdate(**changes), store)


async def remove(data: JSONBody[UserArgs], store: NamedDependency[StorePort]) -> None:
    await router.delete_user(data.user_id, store)


##### ROUTES #####
ROUTES: tuple[HTTPRouteHandler, ...] = tuple(
    tool.route(access, dependencies=router.READ_DEPS, exception_handlers=REFUSALS)(handler)
    for tool, access, handler in (
        (LIST, Access.USER, listed),
        (READ, Access.USER, read),
        (CREATE, Access.ADMIN, create),
        (UPDATE, Access.ADMIN, update),
        (DELETE, Access.ADMIN, remove),
    )
)
