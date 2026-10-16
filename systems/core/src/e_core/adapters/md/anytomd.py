"""adapters/md/anytomd: anytomd bound to Python — one engine for every format, PDF and image descriptions folded in.

`convert_bytes` renders office, markup, tables, notebooks, code and text; a PDF goes through the bundled
liteparse `PdfConverter`; an image is annotated by the configured OpenAI-compatible vision model. Format
detection, zip-bomb limits and size caps are the engine's own. Its failures surface as `ConvertError`
subclasses, which `MDProcessor` records per file rather than letting one bad member abort a batch."""

from typing import TYPE_CHECKING, ClassVar

from anytomd import AsyncOpenAIDescriber, PdfConverter, convert_bytes_async

from e_core.adapters.base import BaseAdapter
from e_core.adapters.ports import MdConversion
from e_core.core.settings import settings as st

if TYPE_CHECKING:
    from e_core.core.settings.md import MDSettings


##### ADAPTER #####
class AnytomdAdapter(BaseAdapter):
    """One anytomd converter per app: `convert` renders bytes of a named format, PDF and image descriptions included."""

    name: ClassVar[str] = "anytomd"

    __slots__ = ("_conf", "_describer", "_pdf")

    def __init__(self, settings: MDSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.md if settings is None else settings
        self._pdf: PdfConverter | None = None
        self._describer: AsyncOpenAIDescriber | None = None

    ##### PRIVATE #####

    def _common_pdf(self) -> PdfConverter:
        match self._pdf:
            case None:
                msg = "AnytomdAdapter not connected: the lifespan opens it, callers never do"
                raise RuntimeError(msg)
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

    ############################################################

    ##### LIFECYCLE #####

    async def connect(self) -> None:
        conf = self._conf
        self._pdf = PdfConverter(
            ocr=conf.md_pdf_ocr, language=conf.md_pdf_language, workers=conf.md_pdf_workers or None
        )
        ### vision is best-effort: without a key there is nothing to describe with, so images keep their
        ### bare `![]` reference rather than bricking startup.
        self._describer = (
            self._common_vision() if conf.md_image_describe and conf.md_vision_api_key is not None else None
        )

    async def close(self) -> None:
        aclose = getattr(self._describer, "aclose", None)
        if aclose is not None:
            await aclose()  # release the vision client's sockets
        self._pdf = None
        self._describer = None

    ##### PUBLIC #####

    async def convert(self, data: bytes, *, extension: str) -> MdConversion:
        """Render bytes of a named format: a PDF through the bundled liteparse, everything else through anytomd."""
        if extension == "pdf":
            document = await self._common_pdf().convert_bytes_async(data)
            return MdConversion(markdown=document.markdown, warnings=document.warnings)
        result = await convert_bytes_async(
            data,
            extension,
            async_image_describer=self._describer,
            extract_comments=self._conf.md_extract_comments,
            strict=self._conf.md_strict,
            max_input_bytes=self._conf.md_max_input_bytes,
        )
        return MdConversion(markdown=result.markdown, warnings=tuple(w.message for w in result.warnings))
