"""ports/provider: the contract of everything the lifespan opens — lifecycle, health, spec, the open guard."""

from dataclasses import dataclass
from enum import StrEnum, auto
from typing import ClassVar, Protocol, Self, overload, runtime_checkable


##### SPEC #####
class Locality(StrEnum):
    """Where the work happens. `EMBEDDED` is an adapter; every other value is a driver."""

    REMOTE = auto()
    SIDECAR = auto()
    EMBEDDED = auto()
    FILESYSTEM = auto()


class Workload(StrEnum):
    """What resource the work consumes."""

    IO_BOUND = auto()
    CPU_BOUND = auto()
    GPU_BOUND = auto()
    MIXED = auto()


class Isolation(StrEnum):
    """How it can run without breaking — the axis an executor reads: the loop, a thread, a process, or one at a time."""

    LOOP = auto()
    THREAD = auto()
    PROCESS = auto()
    SERIAL = auto()


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Orienting metadata, readable without an instance: no layer must consult it, every provider must declare it."""

    name: str
    locality: Locality
    workload: Workload
    isolation: Isolation
    fork_safe: bool = False
    pooled: bool = False
    warmup: bool = False
    memory_hint_mb: int | None = None


##### PORT #####
@runtime_checkable
class Provider(Protocol):
    """A singleton the lifespan opens with `async with` and closes in reverse order. `health` answers True when the
    provider serves, and raises its own error — the reason it is down, what the readiness route shows — when not."""

    spec: ClassVar[ProviderSpec]

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc: object) -> None: ...

    async def health(self) -> bool: ...


##### OPENED #####
class Opened[T]:
    """A provider's resource read through the provider: what its private slot `_<name>` holds once `__aenter__` set it,
    and before that — or after `__aexit__` cleared it — the provider's own error, never a hand-written `case None:
    raise`. Only the lifecycle writes the slot; every other reader goes through the descriptor."""

    __slots__ = ("_error", "_slot")

    def __init__(self, error: type[Exception]) -> None:
        self._error = error

    ##### PRIVATE #####

    def _get_held[O](self, instance: O, owner: type[O]) -> T:
        held: T | None = getattr(instance, self._slot, None)
        match held:
            case None:
                msg = f"{owner.__name__} is not open: the lifespan opens it, callers never do"
                raise self._error(msg)
            case value:
                return value

    ############################################################

    ##### PUBLIC #####

    def __set_name__(self, owner: type, name: str) -> None:
        self._slot = f"_{name}"

    @overload
    def __get__(self, instance: None, owner: type) -> Self: ...

    @overload
    def __get__[O](self, instance: O, owner: type[O]) -> T: ...

    def __get__[O](self, instance: O | None, owner: type[O]) -> Self | T:
        match instance:
            case None:
                return self
            case _:
                return self._get_held(instance, owner)
