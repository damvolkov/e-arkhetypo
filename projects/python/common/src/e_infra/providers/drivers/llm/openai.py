"""providers/drivers/llm/openai: a chat model over an OpenAI-compatible server (vLLM, OpenAI) — JSON-schema answers.

`response_format` with a strict `json_schema` makes the server decode under the schema (vLLM: guided decoding), so the
answer parses and conforms by construction; a reply that still does not parse is a `ModelError`, never a guess; one cut at
the output ceiling is a `TruncatedError`. The server is shared, so every call passes two gates: a semaphore
(`concurrency` in flight) and a token bucket (`rpm` a minute). Temperature 0: annotation is extraction, not
invention. It speaks through an `HTTPPort` received by constructor, the bearer riding every request."""

import asyncio
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar, Self

import msgspec

from e_infra.infra.errors import ModelError, ProviderError, TruncatedError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from pydantic import HttpUrl, SecretStr

    from e_infra.infra.payload import JSON
    from e_infra.ports.http import HTTPPort


##### WIRE #####
class OpenaiMessage(msgspec.Struct, frozen=True):
    content: str | None = None


class OpenaiChoice(msgspec.Struct, frozen=True):
    message: OpenaiMessage
    finish_reason: str | None = None


class OpenaiCompletion(msgspec.Struct, frozen=True):
    """The slice of an OpenAI chat completion this driver reads; every other field is ignored."""

    choices: Sequence[OpenaiChoice]


##### RATE #####
class OpenaiBucket:
    """An async token bucket: `rpm` tokens of burst, refilled at `rpm` a minute on the monotonic clock.

    A take never loops: it books its token at once — the balance may go negative, a queue of debt — and
    sleeps until its own token has refilled. The booking runs between awaits, so it is atomic on the loop."""

    __slots__ = ("_capacity", "_rate", "_stamp", "_tokens")

    def __init__(self, rpm: int) -> None:
        self._capacity = float(rpm)
        self._rate = rpm / 60.0
        self._tokens = self._capacity
        self._stamp = time.monotonic()

    async def take(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._stamp) * self._rate) - 1.0
        self._stamp = now
        await asyncio.sleep(max(0.0, -self._tokens / self._rate))


##### DRIVER #####
class OpenaiDriver:
    """An OpenAI-compatible server behind `LLMPort`, gated by concurrency and rate."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("openai", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_bucket", "_extra", "_gate", "_http", "_key", "_max_tokens", "_model", "_timeout", "_url")

    def __init__(
        self,
        http: HTTPPort,
        *,
        url: HttpUrl,
        key: SecretStr | None,
        timeout: timedelta,
        concurrency: int,
        rpm: int,
        max_tokens: int,
        model: str,
        extra: Mapping[str, JSON],
    ) -> None:
        self._http = http
        self._url = str(url).rstrip("/")
        self._key, self._timeout, self._max_tokens, self._model, self._extra = key, timeout, max_tokens, model, extra
        self._gate = asyncio.Semaphore(concurrency)
        self._bucket = OpenaiBucket(rpm)

    ##### PRIVATE #####

    def _structured_payload(self, system: str, prompt: str, schema: Mapping[str, JSON]) -> dict[str, JSON]:
        """The OpenAI chat-completions body, the provider's own fields (`extra`) merged over it."""
        return {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": dict(schema), "strict": True},
            },
            **self._extra,
        }

    def _common_headers(self) -> dict[str, str]:
        key = self._key
        return {"Authorization": f"Bearer {key.get_secret_value()}"} if key is not None else {}

    @staticmethod
    def _structured_answer(body: JSON) -> JSON:
        """The first choice's content, decoded; any other shape is a `ModelError`."""
        try:
            completion = msgspec.convert(body, OpenaiCompletion)
        except msgspec.ValidationError as error:
            msg = "the server answered without a chat-completion envelope"
            logger.error("openai answered outside the contract", error=str(error))
            raise ModelError(msg) from error
        match completion.choices:
            case [OpenaiChoice(message=OpenaiMessage(content=str() as content), finish_reason=reason), *_]:
                try:
                    return msgspec.json.decode(content)
                except msgspec.DecodeError as error:
                    ### `length` means max_tokens cut the answer: the tail shows where, the head what was asked.
                    msg = f"the answer is not JSON (finish {reason}, {len(content)} chars): …{content[-160:]!r}"
                    logger.error("openai answer is not JSON", finish=reason, chars=len(content))
                    raise (TruncatedError if reason == "length" else ModelError)(msg) from error
            case _:
                msg = "the server answered with no content"
                logger.error("openai answered no content")
                raise ModelError(msg)

    ############################################################

    ##### PUBLIC #####

    @property
    def model(self) -> str:
        """The served model's name: with the driver's, what a semantic label says read it."""
        return self._model

    async def __aenter__(self) -> Self:
        """Nothing to open: the HTTP pool is the lifespan's."""
        logger.info("openai opened", url=self._url, model=self._model)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""
        logger.info("openai closed")

    async def health(self) -> bool:
        """The served models, as any OpenAI-compatible server lists them (`/models`): the key and the server at once."""
        try:
            await self._http.get(f"{self._url}/models", within=self._timeout, headers=self._common_headers())
        except ProviderError as error:
            logger.warning("openai unhealthy", error=str(error))
            raise
        return True

    async def structured(self, system: str, prompt: str, schema: Mapping[str, JSON]) -> JSON:
        """The model's answer to `prompt` under `system`, decoded from JSON constrained by `schema`."""
        url = f"{self._url}/chat/completions"
        logger.debug("openai structured", model=self._model, prompt_chars=len(prompt))
        ### the rate wait comes first: a call sleeping on the bucket must not hold a concurrency slot.
        await self._bucket.take()
        async with self._gate:
            body = await self._http.post(
                url,
                self._structured_payload(system, prompt, schema),
                within=self._timeout,
                headers=self._common_headers(),
            )
        return self._structured_answer(body)
