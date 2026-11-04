"""providers/adapters/markdown/anytomd: anytomd bound to Python — one engine for every format, PDF and images folded in.

`convert_bytes` renders office, markup, tables, notebooks, code and text; a PDF goes through the bundled
liteparse `PdfConverter`; an image is annotated by the OpenAI-compatible vision model it is given. Format
detection, zip-bomb limits and size caps are the engine's own; `detect` names a file's format from its bytes
and name, an archive as the office format it is. Its failures are `ParseError` from here up, which `DocProcessor`
lets rise to its caller."""

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
from e_infra.infra.logger import logger
from e_infra.ports.markdown import MDConversion
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Generator

    from pydantic import HttpUrl, SecretStr


##### ADAPTER #####
class AnytomdAdapter:
    """One anytomd converter per process: `convert` renders bytes of a named format, PDF and image descriptions included."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("anytomd", Locality.EMBEDDED, Workload.MIXED, Isolation.LOOP)

    __slots__ = (
        "_describer",
        "_extract_comments",
        "_image_describe",
        "_max_input_bytes",
        "_pdf",
        "_pdf_language",
        "_pdf_ocr",
        "_pdf_workers",
        "_strict",
        "_vision",
    )

    def __init__(
        self,
        *,
        vision_base_url: HttpUrl,
        vision_api_key: SecretStr | None,
        vision_model: str,
        vision_prompt: str,
        image_describe: bool,
        max_input_bytes: int,
        pdf_workers: int,
        pdf_ocr: bool,
        pdf_language: str,
        strict: bool,
        extract_comments: bool,
    ) -> None:
        self._vision = (vision_base_url, vision_api_key, vision_model, vision_prompt)
        self._image_describe, self._max_input_bytes = image_describe, max_input_bytes
        self._pdf_workers, self._pdf_ocr, self._pdf_language = pdf_workers, pdf_ocr, pdf_language
        self._strict, self._extract_comments = strict, extract_comments
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
            logger.error("anytomd failed", error=str(error))
            raise ParseError(str(error)) from error

    def _common_pdf(self) -> PdfConverter:
        match self._pdf:
            case None:
                msg = "AnytomdAdapter is not open: the lifespan opens it, callers never do"
                raise ParseError(msg)
            case pdf:
                return pdf

    def _common_vision(self) -> AsyncOpenAIDescriber:
        base, key, model, prompt = self._vision
        return AsyncOpenAIDescriber(
            model=model,
            api_base=str(base),
            api_key=key.get_secret_value() if key is not None else None,
            prompt=prompt,
        )

    async def _convert_pdf(self, data: bytes) -> MDConversion:
        document = await self._common_pdf().convert_bytes_async(data)
        return MDConversion(markdown=document.markdown, warnings=document.warnings)

    async def _convert_text(self, data: bytes, extension: str) -> MDConversion:
        result = await convert_bytes_async(
            data,
            extension,
            async_image_describer=self._describer,
            extract_comments=self._extract_comments,
            strict=self._strict,
            max_input_bytes=self._max_input_bytes,
        )
        return MDConversion(markdown=result.markdown, warnings=tuple(w.message for w in result.warnings))

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._pdf = PdfConverter(ocr=self._pdf_ocr, language=self._pdf_language, workers=self._pdf_workers or None)
        ### vision is best-effort: without a key there is nothing to describe with, so images keep their
        ### bare `![]` reference rather than bricking startup.
        self._describer = self._common_vision() if self._image_describe and self._vision[1] is not None else None
        logger.info("anytomd opened", vision=self._describer is not None, pdf_ocr=self._pdf_ocr)
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
        logger.info("anytomd closed")

    async def health(self) -> bool:
        """The engine renders a line of text, and the PDF converter is open."""
        try:
            self._common_pdf()
            await self.convert(b"ping", extension="txt")
        except ProviderError as error:
            logger.warning("anytomd unhealthy", error=str(error))
            raise
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

    async def convert(self, data: bytes, *, extension: str) -> MDConversion:
        """Render bytes of a named format: a PDF through the bundled liteparse, everything else through anytomd."""
        logger.debug("anytomd convert", extension=extension, size=len(data))
        with self._common_guard():
            conversion = await (self._convert_pdf(data) if extension == "pdf" else self._convert_text(data, extension))
        ### returned after the block: a context manager may swallow an exit, so the type checker wants it bound.
        return conversion  # noqa: RET504
