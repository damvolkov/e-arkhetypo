"""ports/provider: the contract of everything the lifespan opens — lifecycle, health and an orienting spec."""

from dataclasses import dataclass
from enum import StrEnum, auto
from typing import ClassVar, Protocol, Self, runtime_checkable


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
    """A singleton the lifespan opens with `async with` and closes in reverse order; `health` never raises."""

    spec: ClassVar[ProviderSpec]

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc: object) -> None: ...

    async def health(self) -> bool: ...
