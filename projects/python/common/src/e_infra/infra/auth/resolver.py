"""infra/auth/resolver: what the token middleware asks of whoever knows the keys — an `Authorization` header, a caller."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from e_infra.infra.auth.models import Caller


@runtime_checkable
class CallerResolver(Protocol):
    """Turns an `Authorization` header into its caller: nobody without a bearer, a refusal for a key nobody holds."""

    async def resolve(self, header: str) -> Caller: ...
