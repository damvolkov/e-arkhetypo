"""providers/adapters/anytomd: anytomd bound to Python — one engine for every format, PDF and image descriptions folded in.

`convert_bytes` renders office, markup, tables, notebooks, code and text; a PDF goes through the bundled
liteparse `PdfConverter`; an image is annotated by the configured OpenAI-compatible vision model. Format
detection, zip-bomb limits and size caps are the engine's own; `detect` names a file's format from its bytes
and name, an archive as the office format it is. Its failures are `ParseError` from here up, which `MDProcessor`
records per file rather than letting one bad member abort a batch."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Self

from anytomd import (
    AsyncOpenAIDescriber,
    ConvertError,
    PdfConverter,
    convert_bytes_async,
    detect_format,
    detect_zip_format,
)

from e_infra.infra.errors import ParseError, ProviderError
from e_infra.infra.settings import settings as st
from e_infra.ports.markdown import MdConversion
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Generator

    from e_infra.infra.config.md import MDSettings


##### ADAPTER #####
class AnytomdAdapter:
    """One anytomd converter per process: `convert` renders bytes of a named format, PDF and image descriptions included."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("anytomd", Locality.EMBEDDED, Workload.MIXED, Isolation.LOOP)

    __slots__ = ("_conf", "_describer", "_pdf")

    def __init__(self, settings: MDSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.md if settings is None else settings
        self._pdf: PdfConverter | None = None
        self._describer: AsyncOpenAIDescriber | None = None

    ##### PRIVATE #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """anytomd's own error, as the tree's `ParseError`."""
        try:
            yield
        except ConvertError as error:
            raise ParseError(str(error)) from error

    def _common_pdf(self) -> PdfConverter:
        match self._pdf:
            case None:
                msg = "AnytomdAdapter is not open: the lifespan opens it, callers never do"
                raise ParseError(msg)
            case pdf:
                return pdf

    def _common_vision(self) -> AsyncOpenAIDescriber:
        conf = self._conf
        key = conf.md_vision_api_key
        return AsyncOpenAIDescriber(
            model=conf.md_vision_model,
            api_base=conf.md_vision_base_url,
            api_key=key.get_secret_value() if key is not None else None,
            prompt=conf.md_vision_prompt,
        )

    async def _convert_pdf(self, data: bytes) -> MdConversion:
        document = await self._common_pdf().convert_bytes_async(data)
        return MdConversion(markdown=document.markdown, warnings=document.warnings)

    async def _convert_text(self, data: bytes, extension: str) -> MdConversion:
        result = await convert_bytes_async(
            data,
            extension,
            async_image_describer=self._describer,
            extract_comments=self._conf.md_extract_comments,
            strict=self._conf.md_strict,
            max_input_bytes=self._conf.md_max_input_bytes,
        )
        return MdConversion(markdown=result.markdown, warnings=tuple(w.message for w in result.warnings))

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        conf = self._conf
        self._pdf = PdfConverter(
            ocr=conf.md_pdf_ocr, language=conf.md_pdf_language, workers=conf.md_pdf_workers or None
        )
        ### vision is best-effort: without a key there is nothing to describe with, so images keep their
        ### bare `![]` reference rather than bricking startup.
        self._describer = (
            self._common_vision() if conf.md_image_describe and conf.md_vision_api_key is not None else None
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        match getattr(self._describer, "aclose", None):
            case None:
                pass
            case aclose:
                ### releases the vision client's sockets.
                await aclose()
        self._pdf = None
        self._describer = None

    async def health(self) -> bool:
        """The engine renders a line of text, and the PDF converter is open."""
        try:
            self._common_pdf()
            await self.convert(b"ping", extension="txt")
        except ProviderError:
            return False
        return True

    def detect(self, name: str, data: bytes) -> str | None:
        """The engine names the format from bytes and name; a ZIP becomes its office format, or stays a bundle."""
        match detect_format(name, data):
            case None:
                return None
            case "zip":
                return detect_zip_format(data) or "zip"
            case fmt:
                return fmt

    async def convert(self, data: bytes, *, extension: str) -> MdConversion:
        """Render bytes of a named format: a PDF through the bundled liteparse, everything else through anytomd."""
        with self._common_guard():
            conversion = await (self._convert_pdf(data) if extension == "pdf" else self._convert_text(data, extension))
        ### returned after the block: a context manager may swallow an exit, so the type checker wants it bound.
        return conversion  # noqa: RET504
