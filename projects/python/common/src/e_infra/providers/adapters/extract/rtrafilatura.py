"""providers/adapters/extract/rtrafilatura: a web page's main content as Markdown — the article without its menus and footers.

Through rtrafilatura (the EDamLabs binding of trafilatura-rs; WCXB 2026: F1 0.903 on held-out pages). The page's own
facts ride first as YAML front matter (title, author, date, url, site): the layout reads it as the document's metadata.
Links, images, tables and inline formatting are kept, so the harvest still finds what the text points at. Extraction is
CPU work: the Rust engine releases the GIL, so the lanes extract in parallel, off the loop. A page with no main content
to find answers None: the caller reads it whole instead."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Final, Self

import anyio
import rtrafilatura
from rtrafilatura.errors import ExtractionError

from e_infra.infra.errors import ParseError, ProviderError
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Generator

### pages extracted at once: the engine frees the GIL, the lxml parse and tree conversion still hold it — x2.5 at 4.
LANES: Final[int] = 4


##### ADAPTER #####
class RtrafilaturaAdapter:
    """Extracts a page's main content; holds nothing but its lanes."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "rtrafilatura", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.THREAD, fork_safe=True
    )

    __slots__ = ("_limiter",)

    def __init__(self) -> None:
        self._limiter = anyio.CapacityLimiter(LANES)

    ##### PRIVATE #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """rtrafilatura's own error, as the tree's `ParseError`."""
        try:
            yield
        except ExtractionError as error:
            raise ParseError(str(error)) from error

    @staticmethod
    def _extract_sync(html: bytes, url: str) -> str | None:
        return rtrafilatura.extract(
            html,
            url=url or None,
            output_format="markdown",
            with_metadata=True,
            include_links=True,
            include_images=True,
            include_tables=True,
            include_formatting=True,
        )

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        """Nothing to open: the extractor is a library."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        """The extractor reads a one-paragraph page in its lanes."""
        try:
            await self.extract(b"<html><body><p>ping</p></body></html>")
        except ProviderError:
            return False
        return True

    async def extract(self, html: bytes, *, url: str = "") -> str | None:
        """The page's main content as Markdown, its facts as front matter; None when it holds none."""
        with self._common_guard():
            return await anyio.to_thread.run_sync(self._extract_sync, html, url, limiter=self._limiter)
