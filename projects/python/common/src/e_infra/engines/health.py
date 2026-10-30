"""engines/health: every provider asked how it is, at once — the startup survey and the readiness route's verdicts.

`survey` calls `health` on many providers together (`asyncio.gather`, each under the same limit, so the whole takes the
slowest one and one that hangs holds none of the rest) and answers one `ProviderHealth` per provider, never a raise: the
lifespan logs it at startup, `GET /ready` serves it. A provider that answers False is down; one that outlasts the limit
is down and says so; one that breaks its contract and raises is down too — a health check's failure is its verdict."""

import asyncio
import time
from typing import TYPE_CHECKING, Final

import msgspec

from e_infra.infra.settings import settings as st

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from e_infra.ports.provider import Provider

MS: Final[int] = 1_000


##### VALUES #####
class ProviderHealth(msgspec.Struct, frozen=True, kw_only=True):
    """One provider's verdict: its name in the state, whether a ready service needs it, whether it is up, how long it
    took (ms), and why not."""

    name: str
    required: bool
    ok: bool
    latency: float
    reason: str = ""


##### ENGINE #####
class HealthEngine:
    """The providers of a process, surveyed together within `limit` each; `required` names the ones a ready service
    cannot do without."""

    __slots__ = ("_limit", "_providers", "_required")

    def __init__(
        self, providers: Mapping[str, Provider], required: frozenset[str] = frozenset(), limit: timedelta | None = None
    ) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._providers = providers
        self._required = required
        self._limit = st.ping.timeout if limit is None else limit

    ##### PRIVATE #####

    async def _survey_one(self, name: str, provider: Provider) -> ProviderHealth:
        """One provider's health, timed, bounded: down when it says so, raises, or outlasts the limit."""
        start = time.perf_counter()
        try:
            async with asyncio.timeout(self._limit.total_seconds()):
                up = await provider.health()
        except TimeoutError:
            reason = f"no answer within {self._limit.total_seconds():g}s"
        except Exception as error:  # noqa: BLE001 — a health check's failure is its verdict, never the caller's
            reason = f"{type(error).__name__}: {error}"
        else:
            reason = "" if up else "unhealthy"
        latency = round((time.perf_counter() - start) * MS, 2)
        return ProviderHealth(name=name, required=name in self._required, ok=not reason, latency=latency, reason=reason)

    def _survey_failed(self, name: str, error: BaseException) -> ProviderHealth:
        """The verdict of a check that escaped `_survey_one` — a cancellation — never timed."""
        reason = f"{type(error).__name__}: {error}".rstrip(": ")
        return ProviderHealth(name=name, required=name in self._required, ok=False, latency=0.0, reason=reason)

    ############################################################

    ##### PUBLIC #####

    async def survey(self) -> tuple[ProviderHealth, ...]:
        """Every provider checked at once, in mapping order: the whole takes the slowest, never the sum."""
        answers = await asyncio.gather(
            *(self._survey_one(name, provider) for name, provider in self._providers.items()),
            return_exceptions=True,
        )
        ### `_survey_one` answers for every failure of a check; what still escapes it (a cancellation) is that provider's.
        return tuple(
            answer if isinstance(answer, ProviderHealth) else self._survey_failed(name, answer)
            for name, answer in zip(self._providers, answers, strict=True)
        )
