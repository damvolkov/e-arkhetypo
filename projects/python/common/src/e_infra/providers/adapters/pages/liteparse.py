"""providers/adapters/pages/liteparse: a document's fast pass on liteparse (Rust, in-process) — the `PagesPort`.

Every page read at once (`aparse`, off the loop), each page's blocks in order — its kind, its text or its lines, a
heading's level, a table's header and rows — and its signals: what liteparse's complexity pass saw that a deep reader
reads better (a table block or a table-like layout, figures or dense graphics, no usable text layer over an image,
embedded images, more than one column). OCR, its tessdata and language, and the workers come from DOC_*."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Final, Self

from liteparse import LiteParse
from liteparse import ParseError as LiteparseError

from e_infra.infra.config.doc import DocSignal
from e_infra.infra.errors import ParseError
from e_infra.infra.settings import settings as st
from e_infra.ports.pages import FastPage, PageBlock
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Generator

    from liteparse import ParsedPage

    from e_infra.infra.config.doc import DocSettings

TABLE: Final[str] = "table"
SCANNED: Final[frozenset[str]] = frozenset({"scanned", "vector-text", "garbled"})


##### ADAPTER #####
class LiteparseAdapter:
    """The fast pass over liteparse, one parser per process."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "liteparse", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.THREAD, fork_safe=True
    )

    __slots__ = ("_conf", "_parser")

    def __init__(self, settings: DocSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.doc if settings is None else settings
        self._parser: LiteParse | None = None

    ##### PRIVATE #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """liteparse's own error, as the tree's `ParseError`."""
        try:
            yield
        except LiteparseError as error:
            raise ParseError(str(error)) from error

    def _common_parser(self) -> LiteParse:
        match self._parser:
            case None:
                msg = "LiteparseAdapter is not open: the lifespan opens it, callers never do"
                raise ParseError(msg)
            case parser:
                return parser

    def _enter_parser(self) -> LiteParse:
        conf = self._conf
        return LiteParse(
            ocr_enabled=conf.doc_ocr,
            tessdata_path=str(conf.doc_tessdata) if conf.doc_tessdata is not None else None,
            ocr_language=conf.doc_ocr_language,
            num_workers=conf.doc_workers or None,
            extract_blocks=True,
            include_complexity=True,
            output_format="markdown",
            quiet=True,
        )

    @staticmethod
    def _parse_signals(page: ParsedPage) -> tuple[DocSignal, ...]:
        """What liteparse's fast pass saw on the page that a deep reader reads better, in DocSignal order."""
        stats = page.complexity
        layout = stats.layout if stats is not None else None
        reasons = set(stats.reasons) if stats is not None else set()
        shapes = set(layout.reasons) if layout is not None else set()
        seen = {
            DocSignal.TABLE: any(block.kind == TABLE for block in page.blocks or ())
            or "table-likely" in shapes
            or bool(layout is not None and layout.text_table_run_count),
            DocSignal.GRAPHICS: "dense-graphics" in shapes or bool(layout is not None and layout.figure_count),
            ### `no-text` alone is a blank page; only with an image under it is it a scan.
            DocSignal.SCANNED: bool(reasons & SCANNED)
            or ("no-text" in reasons and bool(stats.full_page_image or stats.has_substantial_images)),
            DocSignal.IMAGES: "embedded-images" in reasons,
            DocSignal.COLUMNS: "multi-column" in shapes,
        }
        return tuple(signal for signal in DocSignal if seen[signal])

    @staticmethod
    def _parse_blocks(page: ParsedPage) -> tuple[PageBlock, ...]:
        """The page's blocks in order, each as the engine reads it: a table's cells, a heading's level."""
        return tuple(
            PageBlock(
                kind=block.kind,
                text=block.text or "\n".join(block.lines or ()),
                level=block.level if block.kind == "heading" else None,
                header=tuple(cell.text or "" for cell in block.header) if block.header else (),
                rows=tuple(tuple(cell.text or "" for cell in row) for row in block.rows or ()),
            )
            for block in page.blocks or ()
        )

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._parser = self._enter_parser()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._parser = None

    async def health(self) -> bool:
        return self._parser is not None

    async def parse(self, data: bytes) -> tuple[FastPage, ...]:
        with self._common_guard():
            read = await self._common_parser().aparse(data)
        pages = (read.get_page(number) for number in range(1, read.num_pages + 1))
        return tuple(
            FastPage(
                number=number,
                markdown=page.markdown or "",
                blocks=self._parse_blocks(page),
                signals=self._parse_signals(page),
            )
            for number, page in enumerate(pages, start=1)
        )
