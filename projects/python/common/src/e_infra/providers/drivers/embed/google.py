"""providers/drivers/embed/google: gemini-embedding-001 behind `EmbedPort` — the Gemini API or Vertex, one client.

A question and a passage are embedded under their own task (`RETRIEVAL_QUERY`, `RETRIEVAL_DOCUMENT`), at the width
GENAI_EMBED_DIMENSIONS asks, in batches of GENAI_EMBED_BATCH, in order. The tokenizer is the service's, never local:
`tokens` sizes text by Google's own rule of thumb, about four characters a token."""

import math
from itertools import batched
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

import aiohttp
from google.genai import Client, errors, types

from e_infra.infra.errors import ModelError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import SecretStr

### characters a token holds, by Google's guidance for Gemini models: a sizing rule, never a count.
CHARS: Final[int] = 4


### what the SDK raises when Google refuses (`APIError`) or does not answer (its aiohttp transport): the port's error.
FAILURES: Final[tuple[type[Exception], ...]] = (errors.APIError, aiohttp.ClientError, TimeoutError)


class GoogleEmbedDriver:
    """gemini-embedding-001 behind `EmbedPort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("google-embed", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = (
        "_api_key",
        "_batch",
        "_client",
        "_dimensions",
        "_enterprise",
        "_location",
        "_model",
        "_project",
        "_timeout_ms",
    )

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        enterprise: bool,
        project: str | None,
        location: str,
        model: str,
        dimensions: int,
        batch: int,
        timeout_ms: int,
    ) -> None:
        (
            self._api_key,
            self._enterprise,
            self._project,
            self._location,
            self._model,
            self._dimensions,
            self._batch,
            self._timeout_ms,
        ) = api_key, enterprise, project, location, model, dimensions, batch, timeout_ms
        self._client: Any = None

    ##### PRIVATE #####

    def _common_client(self) -> Any:
        match self._client:
            case None:
                msg = "GoogleEmbedDriver is not open: the lifespan opens it, callers never do"
                raise ModelError(msg)
            case client:
                return client

    async def _embed_batch(self, texts: Sequence[str], task: str) -> list[list[float]]:
        config = types.EmbedContentConfig(task_type=task, output_dimensionality=self._dimensions)
        try:
            response = await self._common_client().aio.models.embed_content(
                model=self._model, contents=list(texts), config=config
            )
        except FAILURES as error:
            logger.error("google-embed failed", model=self._model, error=str(error))
            raise ModelError(str(error)) from error
        return [list(each.values) for each in response.embeddings]

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        options = types.HttpOptions(timeout=self._timeout_ms)
        key = self._api_key.get_secret_value() if self._api_key is not None else None
        self._client = (
            Client(enterprise=True, project=self._project, location=self._location, http_options=options)
            if self._enterprise
            else Client(enterprise=False, api_key=key, http_options=options)
        )
        logger.info("google-embed opened", model=self._model, dimensions=self._dimensions)
        return self

    async def __aexit__(self, *exc: object) -> None:
        client, self._client = self._client, None
        _ = client is not None and await client.aio.aclose()
        logger.info("google-embed closed")

    async def health(self) -> bool:
        """One word embedded: the key or the credentials and the model at once."""
        await self.embed(["ping"])
        return True

    async def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        """One vector per text, in order, under the task its role names. No texts, no call."""
        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
        return [
            vector
            for batch in batched(texts, self._batch, strict=False)
            for vector in await self._embed_batch(batch, task)
        ]

    def tokens(self, text: str) -> int:
        """A token count by the four-characters rule."""
        return math.ceil(len(text) / CHARS)
