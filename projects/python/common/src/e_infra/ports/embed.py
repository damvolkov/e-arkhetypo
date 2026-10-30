"""ports/embed: text to vectors, one per text, in order — and the token count of the model that embeds them."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Sequence


@runtime_checkable
class EmbedPort(Provider, Protocol):
    """`query` marks texts that are questions (some models embed them with an instruction). `tokens` counts what the
    embedder's own tokenizer sees."""

    async def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]: ...

    def tokens(self, text: str) -> int: ...
