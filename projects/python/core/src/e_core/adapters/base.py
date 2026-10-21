"""adapters/base: the implementation base for external services — connect, close, ping, async-context bridge.

The contracts the core consumes are the Protocols in `adapters.ports`; this class is the shared
implementation skeleton: the lifespan only ever talks to `connect`/`close` (through the async-context
bridge), so any backend drops into the `AsyncExitStack` unchanged. `ping` is the cheapest real check that the
provider answers — a query, a readiness route, a protocol ping, a trivial job — and raises `PingError` when it does
not; every adapter must say how, there is no default. `survey` pings many at once (`asyncio.gather`, each under the
same limit, so the whole takes the slowest one and one that hangs holds none of the rest) and answers one
`AdapterPing` per adapter, never a raise: the lifespans log it at startup, `GET /ready` serves it."""

import asyncio
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Final, Self

import msgspec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator, Mapping
    from datetime import timedelta
    from types import TracebackType

MS: Final[int] = 1_000


##### ERRORS #####
class PingError(ConnectionError):
    """An adapter's provider did not answer its ping: which adapter, and why."""

    def __init__(self, adapter: str, reason: str) -> None:
        super().__init__(f"{adapter}: {reason}")
        self.adapter, self.reason = adapter, reason


##### VALUES #####
class AdapterPing(msgspec.Struct, frozen=True, kw_only=True):
    """One adapter's ping: its name in the state, whether a ready service needs it, whether it answered, how long it
    took (ms), and why not."""

    name: str
    required: bool
    ok: bool
    latency: float
    reason: str = ""


##### TYPES #####
class BaseAdapter(ABC):
    """Lifecycle edge: connect before use, close after, ping to know it answers; usable as an async context manager."""

    name: ClassVar[str]

    ##### PRIVATE #####

    @contextmanager
    def _ping_guard(self) -> Generator[None]:
        """Whatever the check raises, as the adapter's `PingError`."""
        try:
            yield
        except PingError:
            raise
        except Exception as error:
            raise PingError(self.name, f"{type(error).__name__}: {error}") from error

    @staticmethod
    async def _survey_one(name: str, adapter: BaseAdapter, limit: timedelta, *, required: bool) -> AdapterPing:
        """One adapter's ping, timed, bounded: down when it raises or outlasts the limit."""
        start = time.perf_counter()
        try:
            async with asyncio.timeout(limit.total_seconds()):
                await adapter.ping()
        except TimeoutError:
            reason = f"no answer within {limit.total_seconds():g}s"
        except Exception as error:  # noqa: BLE001 — a ping's failure is its verdict, never the caller's
            reason = str(error)
        else:
            reason = ""
        latency = round((time.perf_counter() - start) * MS, 2)
        return AdapterPing(name=name, required=required, ok=not reason, latency=latency, reason=reason)

    @staticmethod
    def _survey_failed(name: str, error: BaseException, *, required: bool) -> AdapterPing:
        """The verdict of a ping that escaped `_survey_one` — a cancellation — never timed."""
        return AdapterPing(
            name=name, required=required, ok=False, latency=0.0, reason=f"{type(error).__name__}: {error}".rstrip(": ")
        )

    ############################################################

    ##### PUBLIC #####

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection/pool. Idempotency is the implementation's problem."""

    @abstractmethod
    async def close(self) -> None:
        """Release everything connect() took."""

    @abstractmethod
    async def ping(self) -> None:
        """The cheapest real check that the provider answers; `PingError` when it does not."""

    @classmethod
    async def survey(
        cls, adapters: Mapping[str, BaseAdapter], limit: timedelta, required: frozenset[str]
    ) -> tuple[AdapterPing, ...]:
        """Every adapter pinged at once, each within `limit`, in mapping order: the whole takes the slowest, never
        the sum. `required` names the ones a ready service cannot do without."""
        answers = await asyncio.gather(
            *(cls._survey_one(name, adapter, limit, required=name in required) for name, adapter in adapters.items()),
            return_exceptions=True,
        )
        ### `_survey_one` answers for every failure of a ping; what still escapes it (a cancellation) is that adapter's.
        return tuple(
            answer if isinstance(answer, AdapterPing) else cls._survey_failed(name, answer, required=name in required)
            for name, answer in zip(adapters, answers, strict=True)
        )

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self, _exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: TracebackType | None
    ) -> None:
        await self.close()


class StoreAdapter(BaseAdapter):
    """Byte-keyed store implementation base: the same minimum CRUD across backends,
    so redis and sqlite are interchangeable and satisfy `StorePort` structurally."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Missing key reads as None, never an exception."""

    @abstractmethod
    async def set(self, key: str, value: bytes) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Missing key is a no-op."""

    @abstractmethod
    def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed lazily: an async generator, never a materialized list."""
