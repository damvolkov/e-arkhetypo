"""tests/support/kv: the four calls of the byte-keyed store, by name — what a translation test runs one by one."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from e_infra.ports.store import StorePort


async def keys_of(store: StorePort) -> list[str]:
    return [key async for key in store.keys("")]


KV_CALLS: Final[Mapping[str, Callable[[StorePort], Awaitable[object]]]] = MappingProxyType(
    {
        "get": lambda store: store.get("k"),
        "set": lambda store: store.set("k", b"v"),
        "delete": lambda store: store.delete("k"),
        "keys": keys_of,
    }
)
