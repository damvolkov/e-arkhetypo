"""providers/drivers/embed/tei: embeddings on text-embeddings-inference — `POST /embed`, behind `EmbedPort`.

TEI normalizes and truncates server-side (`normalize`, `truncate`), so a vector is ready for cosine and an over-long
text never fails a batch. Batch sizing is the caller's: the driver sends what it is given. It speaks through an
`HttpPort` received by constructor, absolute URLs. Token counts come from the model's own HF tokenizer, loaded once on
entry off the loop; `from_pretrained` reads the Hub cache and honours HF_HUB_OFFLINE, so a cached model loads with no
network."""

from typing import TYPE_CHECKING, ClassVar, Self

import anyio
from tokenizers import Tokenizer

from e_infra.infra.errors import ModelError, ProviderError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Sequence

    from e_infra.infra.config.providers.drivers.embed.tei import TeiEmbedSettings
    from e_infra.ports.http import HttpPort


##### EMBED #####
class TeiEmbedDriver:
    """TEI's embedding route behind `EmbedPort`, and the model's tokenizer."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "tei-embed", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, warmup=True
    )

    __slots__ = ("_conf", "_http", "_tokenizer")

    def __init__(self, http: HttpPort, settings: TeiEmbedSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.drivers.embed.tei if settings is None else settings
        self._http = http
        self._tokenizer: Tokenizer | None = None

    ##### PRIVATE #####

    async def _embed_post(self, inputs: list[str]) -> list[list[float]]:
        payload = {"inputs": inputs, "normalize": True, "truncate": True}
        logger.debug("tei embed", texts=len(inputs))
        return await self._http.post(
            f"{self._conf.url.rstrip('/')}/embed", payload, as_=list[list[float]], within=self._conf.timeout
        )

    def _common_tokenizer(self) -> Tokenizer:
        match self._tokenizer:
            case None:
                msg = "TeiEmbedDriver is not open: the lifespan opens it, handlers never do"
                raise ModelError(msg)
            case tokenizer:
                return tokenizer

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        ### the Hub lookup and the JSON parse block: a thread, not the loop.
        self._tokenizer = await anyio.to_thread.run_sync(Tokenizer.from_pretrained, self._conf.model)
        logger.info("tei embed opened", model=self._conf.model, url=self._conf.url)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._tokenizer = None
        logger.info("tei embed closed")

    async def health(self) -> bool:
        """TEI's own health route: 200 once the model answers."""
        try:
            await self._http.raw(f"{self._conf.url.rstrip('/')}/health", within=self._conf.timeout)
        except ProviderError as error:
            logger.warning("tei embed unhealthy", error=str(error))
            return False
        return self._tokenizer is not None

    async def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        """One vector per text, in order; a query carries EMBED_QUERY_PREFIX. No texts, no call (TEI rejects it)."""
        prefix = self._conf.query_prefix if query else ""
        match [f"{prefix}{text}" for text in texts]:
            case []:
                return []
            case inputs:
                return await self._embed_post(inputs)

    def tokens(self, text: str) -> int:
        """Tokens the embedder sees, special tokens included — TEI appends them too."""
        return len(self._common_tokenizer().encode(text))
