"""ports/markdown: a file of any format rendered to Markdown, and the format named from its bytes."""

from typing import Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider


class MdConversion(msgspec.Struct, frozen=True, kw_only=True):
    """One file rendered to Markdown: the body, and what the converter lost along the way.

    `markdown` is the text; `warnings` are the engine's own notes about a conversion it did not fail on
    (an image it skipped, a block it could not read) — empty when the run was clean."""

    markdown: str
    warnings: tuple[str, ...] = ()


@runtime_checkable
class MarkdownPort(Provider, Protocol):
    """Render the bytes of one file, whose `extension` the caller names, to Markdown.

    `detect` names the format of a file from its name and bytes — an archive as the office format it is, else
    `zip` —, None when it is outside the spectrum. `extension` only says what the bytes are, not who reads them."""

    def detect(self, name: str, data: bytes) -> str | None: ...

    async def convert(self, data: bytes, *, extension: str) -> MdConversion: ...
