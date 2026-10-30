"""providers/drivers/openai: a chat model over an OpenAI-compatible server (vLLM, OpenAI) — answers under a JSON schema.

`response_format` with a strict `json_schema` makes the server decode under the schema (vLLM: guided decoding), so the
answer parses and conforms by construction; a reply that still does not parse is a `ModelError`, never a guess; one cut at
the output ceiling is a `TruncatedError`. The server is shared, so every call passes two gates: a semaphore
(LLM_CONCURRENCY in flight) and a token bucket (LLM_RPM a minute). Temperature 0: annotation is extraction, not
invention. It speaks through an `HttpPort` received by constructor, the bearer riding every request."""

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar, Self

import msgspec

from e_infra.infra.errors import ModelError, ProviderError, TruncatedError
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.config.llm import LlmSettings
    from e_infra.ports.http import HttpPort


##### WIRE #####
class OpenaiMessage(msgspec.Struct, frozen=True):
    content: str | None = None


class OpenaiChoice(msgspec.Struct, frozen=True):
    message: OpenaiMessage
    finish_reason: str | None = None


class OpenaiCompletion(msgspec.Struct, frozen=True):
    """The slice of an OpenAI chat completion this driver reads; every other field is ignored."""

    choices: list[OpenaiChoice]


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
    """An OpenAI-compatible server behind `LlmPort`, gated by concurrency and rate."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("openai", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_bucket", "_conf", "_gate", "_http")

    def __init__(self, http: HttpPort, settings: LlmSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.llm if settings is None else settings
        self._http = http
        self._gate = asyncio.Semaphore(self._conf.concurrency)
        self._bucket = OpenaiBucket(self._conf.rpm)

    ##### PRIVATE #####

    def _structured_payload(self, system: str, prompt: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        """The OpenAI chat-completions body, the provider's own fields (LLM_EXTRA) merged over it."""
        return {
            "model": self._conf.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self._conf.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": dict(schema), "strict": True},
            },
            **self._conf.extra,
        }

    def _common_headers(self) -> dict[str, str]:
        key = self._conf.key
        return {"Authorization": f"Bearer {key.get_secret_value()}"} if key is not None else {}

    @staticmethod
    def _structured_answer(body: object) -> Any:
        """The first choice's content, decoded; any other shape is a `ModelError`."""
        try:
            completion = msgspec.convert(body, OpenaiCompletion)
        except msgspec.ValidationError as error:
            msg = "the server answered without a chat-completion envelope"
            raise ModelError(msg) from error
        match completion.choices:
            case [OpenaiChoice(message=OpenaiMessage(content=str() as content), finish_reason=reason), *_]:
                try:
                    return msgspec.json.decode(content)
                except msgspec.DecodeError as error:
                    ### `length` means max_tokens cut the answer: the tail shows where, the head what was asked.
                    msg = f"the answer is not JSON (finish {reason}, {len(content)} chars): …{content[-160:]!r}"
                    raise (TruncatedError if reason == "length" else ModelError)(msg) from error
            case _:
                msg = "the server answered with no content"
                raise ModelError(msg)

    ############################################################

    ##### PUBLIC #####

    @property
    def model(self) -> str:
        """The served model's name: with the driver's, what a semantic label says read it."""
        return self._conf.model

    async def __aenter__(self) -> Self:
        """Nothing to open: the HTTP pool is the lifespan's."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        """The served models, as any OpenAI-compatible server lists them (`/models`): the key and the server at once."""
        try:
            await self._http.get(
                f"{self._conf.url.rstrip('/')}/models", within=self._conf.timeout, headers=self._common_headers()
            )
        except ProviderError:
            return False
        return True

    async def structured(self, system: str, prompt: str, schema: Mapping[str, Any]) -> Any:
        """The model's answer to `prompt` under `system`, decoded from JSON constrained by `schema`."""
        url = f"{self._conf.url.rstrip('/')}/chat/completions"
        ### the rate wait comes first: a call sleeping on the bucket must not hold a concurrency slot.
        await self._bucket.take()
        async with self._gate:
            body = await self._http.post(
                url,
                self._structured_payload(system, prompt, schema),
                within=self._conf.timeout,
                headers=self._common_headers(),
            )
        return self._structured_answer(body)
