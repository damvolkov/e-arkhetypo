"""ports/database: a SQL database — `$n` statements, rows as dicts, scopes — and LISTEN beside it.

Two capabilities, two ports: `DatabasePort` (the provider) and `ListenPort`, which a driver may meet as well; a consumer
needing both — the durable queue — is handed the same provider typed as each."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractAsyncContextManager

type Row = dict[str, Any]
### a NOTIFY's payload, handed to whoever listens on its channel.
type Notify = Callable[[str], None]


class Vector(tuple[float, ...]):
    """An embedding as a SQL parameter: a tuple of floats the driver binds as its database's vector type
    (a plain list would bind as a float array)."""

    __slots__ = ()


@runtime_checkable
class QueryPort(Protocol):
    """Statements: `execute` runs without returning rows; `fetch` returns every row, `row` the first (None when
    none), `many` runs one statement for each parameter set, `script` several statements without parameters in one
    round trip. Inside `transaction()` every call shares one connection and commits on a clean exit, rolls back on a
    raise; inside `connection()` every call shares one connection, each statement its own commit — what a
    session-level lock needs. A scope opened inside a scope is that scope. Every refusal is a `DatabaseError`; a
    vector column reads back as a list of floats through `::real[]`, on every driver."""

    async def execute(self, query: str, params: Sequence[object] = ()) -> None: ...

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]: ...

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None: ...

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None: ...

    async def script(self, statements: str) -> None: ...

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]: ...

    def connection(self) -> AbstractAsyncContextManager[QueryPort]: ...


@runtime_checkable
class DatabasePort(Provider, QueryPort, Protocol):
    """A SQL database: the statements and scopes of `QueryPort`, on a pool the provider owns."""


@runtime_checkable
class ListenPort(Protocol):
    """LISTEN on a database: each NOTIFY's payload on `channel` handed to every callback listening there, on one
    connection the driver holds; `unlisten` removes one callback, the channel released with its last."""

    async def listen(self, channel: str, callback: Notify) -> None: ...

    async def unlisten(self, channel: str, callback: Notify) -> None: ...
