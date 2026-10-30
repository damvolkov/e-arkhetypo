"""ports/database: a SQL database — statements with positional `$n` parameters, rows as dicts, a transaction scope."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

type Row = dict[str, Any]


class Vector(tuple[float, ...]):
    """An embedding as a SQL parameter: a tuple of floats the driver binds as its database's vector type
    (a plain list would bind as a float array)."""

    __slots__ = ()


@runtime_checkable
class QueryPort(Protocol):
    """Statements: `execute` runs without returning rows; `fetch` returns every row, `row` the first (None when
    none), `many` runs one statement for each parameter set."""

    async def execute(self, query: str, params: Sequence[object] = ()) -> None: ...

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]: ...

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None: ...

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None: ...


@runtime_checkable
class DatabasePort(Provider, QueryPort, Protocol):
    """A SQL database. Inside `transaction()` every statement shares one connection and commits on a clean exit,
    rolls back on a raise."""

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]: ...
