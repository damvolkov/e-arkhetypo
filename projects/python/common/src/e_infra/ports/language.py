"""ports/language: the language a text is written in, over a closed set of ISO 639-1 codes."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Sequence


@runtime_checkable
class LanguagePort(Provider, Protocol):
    """ISO 639-1 codes: `detect` a text's language and the confidence in it (None when nothing can be told), `each`
    every text's (empty when too short or too mixed), `document` the language most characters of the told texts are
    in and its share. `annotator` names the detector at its version — what an annotation's version reads."""

    annotator: str

    def detect(self, text: str) -> tuple[str, float] | None: ...

    def each(self, texts: Sequence[str]) -> list[str]: ...

    def document(self, texts: Sequence[str], langs: Sequence[str]) -> tuple[str, float] | None: ...
