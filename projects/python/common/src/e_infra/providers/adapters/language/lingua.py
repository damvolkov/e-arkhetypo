"""providers/adapters/language/lingua: language identification on lingua (Rust), the `LanguagePort`.

Over the configured languages only: what it may answer is a closed set. `annotator` names lingua at its version (an
annotation's version reads it). It reads a prefix of each text, and a text too short is told by no one. Pickled, it
travels as its languages and builds its detector again where it lands (a worker process)."""

from importlib.metadata import version
from itertools import groupby
from operator import itemgetter
from typing import TYPE_CHECKING, ClassVar, Final, Self

from lingua import IsoCode639_1, Language, LanguageDetector, LanguageDetectorBuilder

from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Sequence

    from e_infra.infra.config.providers.adapters.language.lingua import LinguaSettings

### lingua reads a prefix: past a few pages the verdict no longer moves, the cost still does.
SAMPLED: Final[int] = 20_000
### under this many characters lingua guesses more than it reads: such a text is told by no one.
SHORT: Final[int] = 40


##### ADAPTER #####
class LinguaAdapter:
    """Language identification over a closed set of ISO 639-1 codes; `annotator` names lingua at its version."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("lingua", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.THREAD)

    __slots__ = ("_conf", "_detector", "annotator")

    def __init__(self, settings: LinguaSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.adapters.language.lingua if settings is None else settings
        self._detector: LanguageDetector = LanguageDetectorBuilder.from_languages(
            *(Language.from_iso_code_639_1(IsoCode639_1.from_str(code)) for code in self._conf.languages)
        ).build()
        self.annotator = f"lingua@{version('lingua-language-detector')}"

    ##### PRIVATE #####

    @staticmethod
    def _common_code(language: Language) -> str:
        return language.iso_code_639_1.name.lower()

    ############################################################

    ##### PUBLIC #####

    def __reduce__(self) -> tuple[type[LinguaAdapter], tuple[LinguaSettings]]:
        """Pickled as its settings: the detector (a Rust object) is built again where it lands."""
        return type(self), (self._conf,)

    async def __aenter__(self) -> Self:
        logger.info("lingua opened", languages=list(self._conf.languages), annotator=self.annotator)
        return self

    async def __aexit__(self, *exc: object) -> None:
        logger.info("lingua closed")

    async def health(self) -> bool:
        """In process: the detector was built, it answers."""
        return True

    def detect(self, text: str) -> tuple[str, float] | None:
        """The language of a text's prefix and the confidence in it; None when nothing can be told."""
        top = self._detector.compute_language_confidence_values(text[:SAMPLED])[0]
        return (self._common_code(top.language), top.value) if top.value > 0 else None

    def each(self, texts: Sequence[str]) -> list[str]:
        """Every text's language, in parallel; empty for a text too short or too mixed to tell."""
        found = self._detector.detect_languages_in_parallel_of([text[:SAMPLED] for text in texts])
        return [
            self._common_code(language) if language is not None and len(text.strip()) >= SHORT else ""
            for text, language in zip(texts, found, strict=True)
        ]

    def document(self, texts: Sequence[str], langs: Sequence[str]) -> tuple[str, float] | None:
        """The language most characters of the told texts are in, and its share of them; the joined prefix read whole
        when none was told."""
        told = sorted((lang, len(text)) for text, lang in zip(texts, langs, strict=True) if lang)
        weights = {lang: sum(map(itemgetter(1), group)) for lang, group in groupby(told, key=itemgetter(0))}
        top = max(weights, key=weights.__getitem__, default="")
        return (top, weights[top] / sum(weights.values())) if top else self.detect("\n".join(texts))
