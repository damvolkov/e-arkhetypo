"""ports/extract: a web page's main content as Markdown — what an article says, without what the site wraps it in."""

from typing import Protocol, runtime_checkable

from e_infra.ports.provider import Provider


@runtime_checkable
class ExtractPort(Provider, Protocol):
    """The page's facts (title, author, date, url) ride first as front matter; None when it holds no main content."""

    async def extract(self, html: bytes, *, url: str = "") -> str | None: ...
