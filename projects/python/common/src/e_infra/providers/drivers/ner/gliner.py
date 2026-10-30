"""providers/drivers/ner/gliner: zero-shot entities from a gliner service — `POST /ner/batch`, NDJSON streamed both ways.

A request is one header line (the labels and the threshold for every item) and one line per text, its id its index;
the body is a generator, so the service reads it as it is produced. The answer is one line per text as each completes,
out of order, matched back by id; a line the service refused (`{"id"|"line", "error"}`) or a text left unanswered fails
the call with a `ModelError` — never "found nothing". The service bounds its own predictions; GLINER_TIMEOUT bounds the
wait for each next line, not the whole stream. Opening calls nothing: a process may start with the service down.
`refresh` reads the served model card (`GET /models`) — `gliner:<model>@<version>`, the version a digest of the model's
files — so a promotion there is another annotator here from the next read on.

It keeps a wreq client of its own, not an `HttpPort`: the port speaks JSON bodies, and this exchange streams a request
body and reads the answer frame by frame."""

from contextlib import contextmanager
from itertools import batched, chain
from typing import TYPE_CHECKING, ClassVar, Final, Self

import msgspec
import wreq

from e_infra.infra.errors import HttpError, ModelError, ProviderError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.ner import NerEntity
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator, Iterator, Sequence

    from e_infra.infra.config.providers.drivers.ner.gliner import GlinerSettings

NEWLINE: Final[bytes] = b"\n"
NDJSON: Final[str] = "application/x-ndjson"
WIRE: Final = (
    wreq.BodyError,
    wreq.BuilderError,
    wreq.ConnectionError,
    wreq.ConnectionResetError,
    wreq.DecodingError,
    wreq.ProxyConnectionError,
    wreq.RedirectError,
    wreq.RequestError,
    wreq.StatusError,
    wreq.TimeoutError,
    wreq.TlsError,
)


##### WIRE #####
class GlinerCard(msgspec.Struct, frozen=True):
    """What `GET /models` says is served: the model's name and the digest of its files."""

    model: str
    version: str


class GlinerAnswer(msgspec.Struct, frozen=True):
    """One line of a batch answer: a text's entities by its id, or an error on an item (`id`) or a line (`line`)."""

    id: str = ""
    line: int = 0
    entities: tuple[NerEntity, ...] = ()
    error: str | None = None


##### DRIVER #####
class GlinerDriver:
    """One wreq client per process, behind `NerPort`; the served model is read on `refresh`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("gliner", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_annotator", "_batch", "_client", "_timeout", "_url")

    def __init__(self, settings: GlinerSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        conf = st.providers.drivers.ner.gliner if settings is None else settings
        self._url = conf.url.rstrip("/")
        self._timeout = conf.timeout
        self._batch = conf.batch
        self._client: wreq.Client | None = None
        self._annotator = ""

    ##### PRIVATE #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """wreq's own errors, as the tree's `HttpError`."""
        try:
            yield
        except WIRE as error:
            logger.error("gliner failed", error=str(error))
            raise HttpError(str(error)) from error

    def _common_open(self) -> wreq.Client:
        match self._client:
            case None:
                msg = "GlinerDriver is not open: the lifespan opens it, annotators never do"
                raise ModelError(msg)
            case client:
                return client

    @staticmethod
    def _entities_body(texts: Sequence[str], labels: Sequence[str], threshold: float) -> Iterator[bytes]:
        """The header, then one item a text, each line encoded only when the service reads it."""
        head = {"labels": list(labels), "threshold": threshold}
        items = ({"id": str(at), "text": text} for at, text in enumerate(texts))
        return (msgspec.json.encode(line) + NEWLINE for line in chain((head,), items))

    @staticmethod
    async def _entities_lines(stream: wreq.Streamer) -> AsyncIterator[list[bytes]]:
        """The streamed body cut into lines, the whole ones of each frame together; HTTP trailers are skipped."""
        rest = b""
        ### an async stream is consumed by a loop: each frame's whole lines go out, the partial one waits;
        ### wreq's stub declares `__aiter__` as a coroutine, which the checker refuses.
        async for frame in stream:  # ty: ignore[not-iterable]
            match frame:
                case memoryview() | bytes():
                    *lines, rest = (rest + bytes(frame)).split(NEWLINE)
                    yield lines
                case _:
                    pass
        yield [rest]

    @staticmethod
    def _entities_check(answers: Sequence[GlinerAnswer], count: int) -> dict[str, tuple[NerEntity, ...]]:
        """The entities by id, once every text is answered and no line was refused."""
        refused = [f"{answer.id or f'line {answer.line}'}: {answer.error}" for answer in answers if answer.error]
        found = {answer.id: answer.entities for answer in answers if answer.error is None}
        match (refused, len(found)):
            case ([], answered) if answered == count:
                return found
            case _:
                msg = f"gliner answered {len(found)} of {count} texts; refused: {'; '.join(refused) or 'none'}"
                logger.error("gliner left texts unanswered", answered=len(found), count=count, refused=len(refused))
                raise ModelError(msg)

    async def _entities_batch(
        self, texts: Sequence[str], labels: Sequence[str], threshold: float
    ) -> list[tuple[NerEntity, ...]]:
        """One request: the texts' entities, in order."""
        logger.debug("gliner batch", texts=len(texts), labels=len(labels))
        with self._common_guard():
            response = await self._common_open().post(
                f"{self._url}/ner/batch",
                body=self._entities_body(texts, labels, threshold),
                headers={"content-type": NDJSON},
            )
            response.raise_for_status()
            async with response.stream() as stream:
                answers = [
                    msgspec.json.decode(line, type=GlinerAnswer)
                    async for lines in self._entities_lines(stream)
                    for line in lines
                    if line.strip()
                ]
        found = self._entities_check(answers, len(texts))
        return [found[str(at)] for at in range(len(texts))]

    ############################################################

    ##### PUBLIC #####

    @property
    def annotator(self) -> str:
        return self._annotator

    async def __aenter__(self) -> Self:
        self._client = wreq.Client(read_timeout=self._timeout)
        logger.info("gliner opened", url=self._url)
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._client:
            case None:
                return
            case client:
                client.close()
                self._client = None
                logger.info("gliner closed")

    async def health(self) -> bool:
        """The service's readiness route: 200 once the model is loaded, 503 before."""
        try:
            with self._common_guard():
                response = await self._common_open().get(f"{self._url}/ready")
                response.raise_for_status()
        except ProviderError as error:
            logger.warning("gliner unhealthy", error=str(error))
            return False
        return True

    async def refresh(self) -> str:
        """The served model, read now; the last one read stays when the service cannot answer (and this raises)."""
        with self._common_guard():
            response = await self._common_open().get(f"{self._url}/models")
            response.raise_for_status()
            body = await response.bytes()
        card = msgspec.json.decode(body, type=GlinerCard)
        self._annotator = f"gliner:{card.model}@{card.version}"
        logger.debug("gliner refreshed", annotator=self._annotator)
        return self._annotator

    async def entities(
        self, texts: Sequence[str], *, labels: Sequence[str], threshold: float
    ) -> list[tuple[NerEntity, ...]]:
        """Each text's entities, in order, GLINER_BATCH texts a request; no text, no call."""
        return [
            entities
            for batch in batched(texts, self._batch, strict=False)
            for entities in await self._entities_batch(batch, labels, threshold)
        ]
