"""ports/ner: zero-shot named entities — per text, the spans of the labels asked for, scored and never overlapping."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Sequence


class NerEntity(msgspec.Struct, frozen=True):
    """A span the model typed: `start..end` a half-open range of characters (code points) in its text, `label` one of
    the labels asked for, `score` the model's in (0, 1)."""

    start: int
    end: int
    text: str
    label: str
    score: float


@runtime_checkable
class NerPort(Provider, Protocol):
    """Spans scored from `threshold`. `annotator` names the model that answered last time it was asked (empty before);
    `refresh` asks the model again and answers it, raising when it cannot say."""

    @property
    def annotator(self) -> str: ...

    async def refresh(self) -> str: ...

    async def entities(
        self, texts: Sequence[str], *, labels: Sequence[str], threshold: float
    ) -> list[tuple[NerEntity, ...]]: ...
