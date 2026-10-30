"""ports/rerank: a cross-encoder — each text scored against the question, read together, in the texts' order."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Sequence


@runtime_checkable
class RerankPort(Provider, Protocol):
    """What one embedding per text, made before the question exists, cannot do."""

    async def rerank(self, question: str, texts: Sequence[str]) -> list[float]: ...
