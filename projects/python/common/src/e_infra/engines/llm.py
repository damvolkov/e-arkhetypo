"""engines/llm: the model agent — a tier answers a typed contract or a typed error; text becomes vectors of one embedder.

Callers ask for a tier, never a model: `run(tier, instructions, prompt, output)` returns an instance of `output` (a
msgspec Struct, a dataclass, a TypedDict — what msgspec types), there is no free-text verb. The schema sent is the
contract's, `$ref`s inlined and the keywords constrained decoders refuse (`uniqueItems`, `pattern`: vLLM's xgrammar)
left out, the same for every provider; the contract, those keywords included, is held on decode. A reply that does not
decode goes back to the model with msgspec's error, LLM_RETRIES times, then `InvalidOutputError`; a cut reply is the
driver's `TruncatedError`, a declined one its `RefusalError`. `embed(texts, purpose)` returns `Vectors` stamped with
the embedder that wrote them: vectors of two embedders never meet.

Every answer and every vector is kept by content (`ModelCache`): a run's key is the model, the instructions, the prompt
and the contract's whole schema; a vector's, the embedder, its width, the purpose and the text — a change to any of them
is a new key, `KEY_VERSION` a new space. RECORD reads first and keeps what the model answered (the reply that decoded,
after its retries); REPLAY reads only, and a key it lacks is `ReplayMissError`; OFF asks the model. Two misses of one key
at once pay one call: the second waits on the key's lock and reads what the first kept. A cache that fails is said and
skipped in RECORD — the model answers — and raised in REPLAY. The engine keeps references, settings and the locks of the
keys in flight."""

import asyncio
import hashlib
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any, Final
from weakref import WeakValueDictionary

import msgspec

from e_infra.infra.config.engines import CacheMode, Tier
from e_infra.infra.errors import InvalidOutputError, ModelError, ProviderError, ReplayMissError
from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from e_infra.ports.cache import CachePort
    from e_infra.ports.embed import EmbedPort
    from e_infra.ports.llm import LLMPort

### schema keywords a constrained decoder may refuse: never sent, always held on decode.
LOOSE: Final[frozenset[str]] = frozenset({"uniqueItems", "pattern"})
### what is said to a model whose reply did not decode, before the request again.
AGAIN: Final[str] = (
    "\n\nYour previous answer did not decode against the schema: {error}. Answer again, the whole object."
)
### the version of every cache key: bumped, every answer and vector is asked again.
KEY_VERSION: Final[int] = 1


##### VALUES #####
class Purpose(StrEnum):
    """What a text is embedded as: a question, or a passage that may answer one."""

    QUERY = auto()
    DOCUMENT = auto()


class Vectors(msgspec.Struct, frozen=True, kw_only=True):
    """Vectors in the order of their texts, and the embedder whose space they live in (`provider:model`)."""

    embedder: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class ModelCache:
    """Where the engine keeps what the models answered: `answers` the replies that decoded, `vectors` one per text."""

    answers: CachePort[Any]
    vectors: CachePort[list[float]]
    mode: CacheMode


##### ENGINE #####
class LLMEngine:
    """The tiers' models and the embedder, as one agent."""

    __slots__ = ("_cache", "_dimensions", "_embed", "_embedder", "_locks", "_retries", "_tiers")

    def __init__(
        self,
        tiers: Mapping[Tier, LLMPort],
        embed: EmbedPort,
        embedder: str,
        dimensions: int,
        *,
        retries: int,
        cache: ModelCache,
    ) -> None:
        match [str(tier) for tier in Tier if tier not in tiers]:
            case [_, *_] as missing:
                msg = f"no model serves the tiers {missing}"
                raise ModelError(msg)
        self._retries = retries
        self._tiers = dict(tiers)
        self._embed = embed
        self._embedder = embedder
        self._dimensions = dimensions
        self._cache = cache
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    ##### PRIVATE #####

    @classmethod
    def _run_schema(cls, output: type[Any]) -> dict[str, Any]:
        """The contract's JSON schema as sent: references inlined, the loose keywords left out."""
        schema = msgspec.json.schema(output)
        return cls._run_inline(schema, schema.get("$defs", {}))

    @classmethod
    def _run_inline(cls, node: Any, defs: Mapping[str, Any]) -> Any:
        """A schema node with every `$ref` replaced by its definition; `$defs` and the loose keywords dropped."""
        match node:
            case {"$ref": str() as ref}:
                return cls._run_inline(defs[ref.rpartition("/")[2]], defs)
            case dict():
                return {
                    key: cls._run_inline(value, defs) for key, value in node.items() if key not in LOOSE | {"$defs"}
                }
            case list():
                return [cls._run_inline(value, defs) for value in node]
            case _:
                return node

    async def _run_attempt(
        self, model: LLMPort, *, instructions: str, prompt: str, output: type[Any], schema: Mapping[str, Any], left: int
    ) -> Any:
        """The first reply that decodes, as the model wrote it; on a decode error, the same request again with the error
        — while retries are left."""
        answer = await model.structured(instructions, prompt, schema)
        try:
            msgspec.convert(answer, output, strict=False)
        except msgspec.ValidationError as error:
            logger.warning("llm reply did not decode", model=model.model, left=left, error=str(error))
            match left:
                case 0:
                    msg = f"{model.model}: {self._retries + 1} replies outside the contract, the last: {error}"
                    raise InvalidOutputError(msg) from error
                case _:
                    again = prompt + AGAIN.format(error=error)
                    return await self._run_attempt(
                        model, instructions=instructions, prompt=again, output=output, schema=schema, left=left - 1
                    )
        return answer

    @staticmethod
    def _common_key(*parts: object) -> str:
        """A cache key: the sha256 of the parts, encoded deterministically, under the key version."""
        return hashlib.sha256(msgspec.msgpack.encode((KEY_VERSION, *parts), order="deterministic")).hexdigest()

    async def _common_read[V](self, cache: CachePort[V], keys: Sequence[str]) -> dict[str, V]:
        """What the cache holds of `keys`; a cache that fails is said, and holds nothing (REPLAY raises it)."""
        try:
            return await cache.many(keys)
        except ProviderError as error:
            logger.warning("llm cache read failed", mode=str(self._cache.mode), error=str(error))
            match self._cache.mode:
                case CacheMode.REPLAY:
                    raise
                case _:
                    return {}

    async def _common_keep[V](self, cache: CachePort[V], items: Mapping[str, V]) -> None:
        """Keep what the models answered; a cache that fails is said, never the caller's failure."""
        try:
            await cache.put_many(items)
        except ProviderError as error:
            logger.warning("llm cache write failed", keys=len(items), error=str(error))

    @staticmethod
    def _common_missing(keys: Sequence[str], held: Mapping[str, object]) -> None:
        """In REPLAY, a key the cache lacks is an error: no model is asked."""
        match [key for key in keys if key not in held]:
            case [_, *_] as missing:
                msg = f"{len(missing)} of {len(keys)} calls are not in the cache (REPLAY asks no model)"
                raise ReplayMissError(msg)

    async def _run_answer(self, key: str, ask: Callable[[], Awaitable[Any]]) -> Any:
        """The answer of a run by its key, as the cache mode decides."""
        match self._cache.mode:
            case CacheMode.OFF:
                return await ask()
            case CacheMode.REPLAY:
                held = await self._common_read(self._cache.answers, [key])
                self._common_missing([key], held)
                return held[key]
            case CacheMode.RECORD:
                return await self._run_record(key, ask)

    async def _run_record(self, key: str, ask: Callable[[], Awaitable[Any]]) -> Any:
        """Read, else ask and keep — under the key's lock, so a second miss of it reads what the first kept."""
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            held = await self._common_read(self._cache.answers, [key])
            return held[key] if key in held else await self._run_keep(key, await ask())

    async def _run_keep(self, key: str, answer: Any) -> Any:
        await self._common_keep(self._cache.answers, {key: answer})
        return answer

    async def _embed_vectors(self, texts: Sequence[str], purpose: Purpose) -> list[list[float]]:
        """One vector per text, as the cache mode decides: only the texts it lacks reach the embedder, once each."""
        query = purpose is Purpose.QUERY
        keys = [self._common_key("embed", self._embedder, self._dimensions, str(purpose), text) for text in texts]
        match self._cache.mode:
            case CacheMode.OFF:
                return await self._embed.embed(texts, query=query)
            case CacheMode.REPLAY:
                held = await self._common_read(self._cache.vectors, keys)
                self._common_missing(keys, held)
            case CacheMode.RECORD:
                held = await self._common_read(self._cache.vectors, keys)
                lacking = {key: text for key, text in zip(keys, texts, strict=True) if key not in held}
                found = await self._embed.embed(list(lacking.values()), query=query) if lacking else []
                fresh = dict(zip(lacking, found, strict=True))
                _ = fresh and await self._common_keep(self._cache.vectors, fresh)
                held |= fresh
        return [held[key] for key in keys]

    ############################################################

    ##### PUBLIC #####

    async def run[T](self, tier: Tier, instructions: str, prompt: str, output: type[T]) -> T:
        """The tier's model answering `prompt` under `instructions`, as an instance of `output`."""
        model = self._tiers[tier]
        logger.debug("llm run", tier=str(tier), model=model.model, output=getattr(output, "__name__", str(output)))
        schema = self._run_schema(output)
        key = self._common_key("run", model.model, instructions, prompt, msgspec.json.schema(output))
        answer = await self._run_answer(
            key,
            lambda: self._run_attempt(
                model, instructions=instructions, prompt=prompt, output=output, schema=schema, left=self._retries
            ),
        )
        return msgspec.convert(answer, output, strict=False)

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Vectors:
        """One vector per text, in order, in the embedder's space; a width other than declared is refused."""
        found = await self._embed_vectors(texts, purpose) if texts else []
        match sorted({len(vector) for vector in found} - {self._dimensions}):
            case [_, *_] as wrong:
                msg = f"{self._embedder} answered vectors of width {wrong}, declared {self._dimensions}"
                raise ModelError(msg)
        return Vectors(embedder=self._embedder, dimensions=self._dimensions, vectors=tuple(map(tuple, found)))
