"""tests/support/models: the model ports a test stands in for — a chat model from a script, an embedder that counts.

`ScriptedModel` is an `LLMPort` that answers one scripted reply per call and keeps what each call was asked (system,
prompt, schema): the engine's retries, its schema and its prompts are read back from `calls`. `ScriptedEmbed` is an
`EmbedPort` whose vectors are the text's position repeated `width` times, and which keeps whether each call embedded
queries; it counts tokens by words. One of each for every test that needs a model — never redefined in a test module."""

from typing import TYPE_CHECKING, Any, ClassVar, Self

from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class ScriptedModel:
    """An `LLMPort` that answers from a script, one reply per call, and keeps what it was asked."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("llm-scripted", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self, *replies: Any, name: str = "scripted") -> None:
        self.replies, self.name = list(replies), name
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def model(self) -> str:
        return self.name

    @property
    def prompts(self) -> list[str]:
        """The prompt of each call, in order."""
        return [prompt for _, prompt, _ in self.calls]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    async def structured(self, system: str, prompt: str, schema: Mapping[str, Any]) -> Any:
        self.calls.append((system, prompt, dict(schema)))
        return self.replies.pop(0)


class ScriptedEmbed:
    """An `EmbedPort` with vectors by position and a word count for tokens; it keeps each call's `query` flag."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("embed-scripted", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self, width: int = 3) -> None:
        self.width = width
        self.queries: list[bool] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    async def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        self.queries.append(query)
        return [[float(n)] * self.width for n, _ in enumerate(texts)]

    def tokens(self, text: str) -> int:
        return len(text.split())
