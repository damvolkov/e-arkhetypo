"""providers/drivers/rerank/tei: reranking on text-embeddings-inference — `POST /rerank`, behind `RerankPort`.

TEI answers best first, by index; the driver hands the scores back in the texts' order, cutting RERANK_BATCH texts a
request. It speaks through an `HTTPPort` received by constructor, absolute URLs."""

from typing import TYPE_CHECKING, ClassVar, Self

from e_infra.infra.errors import ProviderError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Sequence

    from e_infra.infra.config.providers.drivers.rerank.tei import RerankTEISettings
    from e_infra.ports.http import HTTPPort


##### RERANK #####
class RerankTEIDriver:
    """TEI's rerank route behind `RerankPort`: it answers best first, by index; scores come back in the texts' order."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("tei-rerank", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_base", "_conf", "_http")

    def __init__(self, http: HTTPPort, settings: RerankTEISettings | None = None) -> None:
        self._conf = st.providers.drivers.rerank.tei if settings is None else settings
        self._http = http
        ### no URL is the reranker off: the root builds no driver; one built anyway refuses to open.
        self._base = (self._conf.url or "").rstrip("/")

    ##### PRIVATE #####

    async def _rerank_post(self, question: str, texts: Sequence[str]) -> list[dict[str, float]]:
        payload = {"query": question, "texts": list(texts), "truncate": True}
        logger.debug("tei rerank", texts=len(texts))
        return await self._http.post(
            f"{self._base}/rerank", payload, as_=list[dict[str, float]], within=self._conf.timeout
        )

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        """Nothing to open: the HTTP pool is the lifespan's; no URL is the reranker off, refused."""
        match self._base:
            case "":
                msg = "RERANK_URL is none: the reranker is off, the composition root builds no driver"
                raise ProviderError(msg)
            case _:
                pass
        logger.info("tei rerank opened", url=self._base)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""
        logger.info("tei rerank closed")

    async def health(self) -> bool:
        """TEI's own health route: 200 once the model answers."""
        try:
            await self._http.raw(f"{self._base}/health", within=self._conf.timeout)
        except ProviderError as error:
            logger.warning("tei rerank unhealthy", error=str(error))
            raise
        return True

    async def rerank(self, question: str, texts: Sequence[str]) -> list[float]:
        """Each text's score against the question, in the texts' order, RERANK_BATCH a request; no texts, no call."""
        size = self._conf.batch
        answers = [
            (start, await self._rerank_post(question, texts[start : start + size]))
            for start in range(0, len(texts), size)
        ]
        scores = {start + int(scored["index"]): scored["score"] for start, answer in answers for scored in answer}
        return [scores[at] for at in range(len(texts))]
