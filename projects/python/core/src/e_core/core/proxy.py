"""core/proxy: import-safe lazy singletons — the object exists at module level, its load runs on first use."""

import functools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


##### TYPES #####
class LazyProxy[T]:
    """Attribute access delegated to a `T` built exactly once per process, on first access.

    The module body only constructs the proxy — no env, no secrets, no `.env`, no structlog at
    import. `functools.cache` pins the build so the second touch reuses the first instance."""

    __slots__ = ("_get",)

    def __init__(self, build: Callable[[], T]) -> None:
        self._get = functools.cache(build)

    def __getattr__(self, name: str) -> Any:
        ### only reached for names absent on the proxy itself: `_get` is a slot, so no recursion here.
        return getattr(self._get(), name)
