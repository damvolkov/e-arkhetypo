"""logic.agent: the AgnosticAgent — one structured, async call over any model provider, for fused semantic specs.

A singleton like the adapters: built once, opened and closed by the lifespan, mounted at `logic.agent`.
It speaks to every provider any-llm reaches (52, plus any OpenAI-compatible endpoint as `CUSTOM`) through
one verb, `run`, and owns everything structured output needs above the transport:

- **where**: an `Endpoint` given on the fly or a `Tier` resolved from settings; `api_base` / `api_key`
  resolve run argument → endpoint → the provider's settings (its standard variables) → a dummy key for
  local servers, whose clients may insist on one the server never reads.
- **what shape**: always a structured one, never free text — resolved once into a `Shape` by type
  dispatch on the output's own class. A model (pydantic by its metaclass, msgspec Struct or dataclass)
  exports its JSON Schema and validates the reply into an instance of itself — the model is the
  contract, no schema validation on top. A raw JSON Schema (the fused schema of a section's semantic
  specs) must have an object root; it is compiled once by jsonschema-rs, which validates every reply,
  handed back as the JSON object it describes. Strict mode is applied where the provider demands it.
- **is it right**: a reply that does not fit is handed back to the model with the error, up to
  AGENT_RETRIES times, then an `InvalidError`. Truncation is avoided first: no token limit is imposed
  unless the caller sets `max_tokens`, so the server's own (the whole remaining context, on vLLM)
  holds; a reply cut at a caller's limit is asked again with the budget doubled, on the same retry
  budget, and only then a `TruncatedError`. A refusal or a content filter is a `RefusedError` at once.
  Every `OutputError` carries the raw reply, attempts, usage and finish reason, message included.
- **what it cost**: every reply carries its usage; inside `AgnosticAgent.meter()` (the instrument opens
  one per node) every call's usage also adds up, so a node's output reports what its agent spent.

Clients are pooled per (provider, base, key): an endpoint seen once is reused for every later call, and
the pool closes with the agent. Errors live in `logic.errors`: `SchemaError` (no known shape),
`EndpointError` (nothing to connect with), `ProviderError` (the provider failed the call), and the
`OutputError` family — `InvalidError`, `TruncatedError`, `RefusedError` (the model never produced the
shape, and why)."""

import dataclasses
import hashlib
import inspect
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache, partial, singledispatch
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Self, TypedDict, Unpack, cast, overload

import jsonschema_rs
import msgspec
import pydantic
from any_llm import AnyLLM
from any_llm.exceptions import MissingApiKeyError

from e_graph.logic.errors import (
    EndpointError,
    InvalidError,
    ProviderError,
    RefusedError,
    SchemaError,
    TruncatedError,
)
from e_graph.logic.models import (
    LOCAL,
    STRICT,
    Completion,
    Endpoint,
    JsonSchema,
    Message,
    Provider,
    Reply,
    Shape,
    Speaker,
    Tier,
    Usage,
)
from infra.settings import settings as st

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
    from any_llm.types.completion import ChatCompletionMessage

type Prompt = str | Sequence[Message]
### an output model: validated by pydantic when it is one, by msgspec otherwise.
type Model = pydantic.BaseModel | msgspec.Struct | DataclassInstance
### a raw JSON Schema: the reply comes back as the JSON object it describes.
type Schema = Mapping[str, Any]
type Output = type[Model] | Schema
type Target = Endpoint | Tier
type PoolKey = tuple[Provider, str, str]

DUMMY_KEY: Final[str] = "not-needed"
MS_PER_SECOND: Final[float] = 1000.0
TIERS: Final[Mapping[Tier, str]] = MappingProxyType(
    {
        Tier.HIGH: "high",
        Tier.MEDIUM: "medium",
        Tier.LOW: "low",
    }
)
RETRY_PROMPT: Final[str] = (
    "Your previous reply did not match the required structure: {error}. "
    "Reply again with only the corrected output, matching the schema exactly."
)
METER: Final[ContextVar[UsageMeter | None]] = ContextVar("agent_meter", default=None)


##### SHAPES #####
### dispatch on the output's own class: a model class by its metaclass, a raw schema by being a Mapping.
@singledispatch
def shape_output(output: object) -> Shape[Any]:
    """The output resolved for the wire and back; anything with no registered shape is refused."""
    msg = f"no output shape for {output!r}: a pydantic model, a msgspec Struct, a dataclass or a JSON Schema"
    raise SchemaError(msg)


def shape_pydantic(output: type[pydantic.BaseModel]) -> Shape[Any]:
    """A pydantic model: its own schema out, its own validation back."""
    return Shape(
        name=output.__name__,
        schema=output.model_json_schema(),
        parse=output.model_validate_json,
        errors=(pydantic.ValidationError,),
    )


def shape_msgspec(output: type[msgspec.Struct] | type[DataclassInstance]) -> Shape[Any]:
    """A msgspec Struct or a dataclass: msgspec exports the schema and decodes straight into the type."""
    return Shape(
        name=output.__name__,
        schema=msgspec.json.schema(output),
        parse=partial(msgspec.json.decode, type=output),
        errors=(msgspec.DecodeError,),
    )


def shape_class(output: type) -> Shape[Any]:
    """A plain class: a dataclass goes the msgspec way, any other class has no shape."""
    match output:
        case type() if dataclasses.is_dataclass(output):
            return shape_msgspec(output)
        case _:
            return shape_output.dispatch(object)(output)


def shape_schema(output: Schema) -> Shape[dict[str, Any]]:
    """A raw JSON Schema, checked and compiled once by being a `JsonSchema`; every reply is validated against it."""
    try:
        schema = JsonSchema(output)
    except ValueError as error:
        msg = f"invalid output: {error}"
        raise SchemaError(msg) from error
    return Shape(
        name=str(schema.get("title") or "output"),
        schema=dict(schema),
        parse=partial(validate_schema, schema.validator),
        errors=(msgspec.DecodeError, jsonschema_rs.ValidationError),
    )


def validate_schema(validator: jsonschema_rs.Validator, raw: str) -> dict[str, Any]:
    """A raw schema's reply: decoded, then validated in Rust; the root is an object by the schema's own law."""
    decoded = msgspec.json.decode(raw)
    validator.validate(decoded)
    return decoded


### explicit registration; model classes are cached — a class's shape never changes, a mapping's may.
shape_output.register(type(pydantic.BaseModel), cache(shape_pydantic))
shape_output.register(msgspec.StructMeta, cache(shape_msgspec))
shape_output.register(type, cache(shape_class))
shape_output.register(Mapping, shape_schema)


##### GENERATION #####
class Generation(TypedDict, total=False):
    """Generation options, passed to the provider as they are."""

    temperature: float
    top_p: float
    max_tokens: int
    seed: int
    stop: list[str]
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "auto"]
    extra_body: dict[str, Any]


##### METER #####
class UsageMeter:
    """What every agent call inside one `meter()` block cost, added up."""

    __slots__ = ("_usage",)

    def __init__(self) -> None:
        self._usage = Usage()

    @property
    def usage(self) -> Usage | None:
        """The total, or None when no call happened — so 'no agent activity' stays distinguishable."""
        return self._usage if self._usage.calls else None

    def add(self, usage: Usage) -> None:
        self._usage = self._usage + usage


##### AGENT #####
class AgnosticAgent:
    """One structured async call to any provider, with our own models; a singleton in `logic.agent`."""

    __slots__ = ("_pool", "_settings")

    def __init__(self, settings: Any = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._settings = st.agent if settings is None else settings
        self._pool: dict[PoolKey, AnyLLM] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    ##### PRIVATE METHODS #####

    def _run_endpoint(self, target: Target, api_base: str | None, api_key: str | None) -> Endpoint:
        """The endpoint to call, every connection field resolved: run argument → endpoint → settings → dummy."""
        endpoint = self._run_tier(target) if isinstance(target, Tier) else target
        provider = endpoint.provider
        base = api_base or endpoint.api_base or getattr(self._settings, f"{provider}_api_base", None) or ""
        secret = getattr(self._settings, f"{provider}_api_key", None)
        configured = secret.get_secret_value() if secret is not None else ""
        key = api_key or endpoint.api_key or configured or (DUMMY_KEY if provider in LOCAL else "")
        match (provider, base):
            case (Provider.CUSTOM, ""):
                msg = "a CUSTOM endpoint needs an api_base: pass it, set it on the endpoint, or set CUSTOM_API_BASE"
                raise EndpointError(msg)
            case _:
                return msgspec.structs.replace(endpoint, api_base=base, api_key=key)

    def _run_tier(self, tier: Tier) -> Endpoint:
        """The tier's endpoint from its sub-settings, already validated at load: only its absence is left to catch."""
        match getattr(self._settings, TIERS[tier]):
            case None:
                prefix = TIERS[tier].upper()
                msg = f"tier {tier} has no endpoint: set {prefix}__PROVIDER and {prefix}__MODEL"
                raise EndpointError(msg)
            case declared:
                key = declared.api_key.get_secret_value() if declared.api_key is not None else ""
                return Endpoint(
                    provider=Provider(declared.provider),
                    model=declared.model,
                    api_base=declared.api_base or "",
                    api_key=key,
                    options=dict(declared.options),
                )

    def _run_client(self, endpoint: Endpoint) -> AnyLLM:
        """The pooled client for the endpoint's provider, base and key — built once, reused after."""
        fingerprint = hashlib.sha256(endpoint.api_key.encode()).hexdigest()[:16]
        key: PoolKey = (endpoint.provider, endpoint.api_base, fingerprint)
        match self._pool.get(key):
            case None:
                client = self._run_connect(endpoint)
                self._pool[key] = client
                return client
            case client:
                return client

    @staticmethod
    def _run_connect(endpoint: Endpoint) -> AnyLLM:
        base, key = endpoint.api_base or None, endpoint.api_key or None
        try:
            match endpoint.provider:
                case Provider.CUSTOM:
                    return AnyLLM.create_openai_compatible(
                        name="custom", api_base=endpoint.api_base, api_key=key, **endpoint.options
                    )
                case provider:
                    return AnyLLM.create(provider.value, api_key=key, api_base=base, **endpoint.options)
        except MissingApiKeyError as error:
            msg = f"{endpoint.provider} needs an api_key: pass it, set it on the endpoint, or set its key variable"
            raise EndpointError(msg) from error

    @classmethod
    def _run_format(cls, shape: Shape[Any], provider: Provider) -> dict[str, Any]:
        """The provider's structured-output request, strict where the provider demands it."""
        strict = provider in STRICT
        body = cls._run_strict(shape.schema) if strict else shape.schema
        return {"type": "json_schema", "json_schema": {"name": shape.name, "schema": body, "strict": strict}}

    @classmethod
    def _run_strict(cls, node: Any) -> Any:
        """Strict mode, recursively: every object closed to extra keys, every property required."""
        match node:
            case {"type": "object", "properties": Mapping() as properties, **rest}:
                walked = {key: cls._run_strict(value) for key, value in properties.items()}
                closed = {**rest, "type": "object", "properties": walked}
                return closed | {"required": list(walked), "additionalProperties": False}
            case Mapping():
                return {key: cls._run_strict(value) for key, value in node.items()}
            case list():
                return [cls._run_strict(value) for value in node]
            case _:
                return node

    @staticmethod
    def _run_messages(instructions: str, prompt: Prompt) -> list[dict[str, str]]:
        """The chat the provider receives: the instructions as system, then the prompt's turns."""
        turns = [Message(Speaker.USER, prompt)] if isinstance(prompt, str) else list(prompt)
        return [
            {"role": message.role, "content": message.content}
            for message in (Message(Speaker.SYSTEM, instructions), *turns)
        ]

    async def _run_call(
        self,
        client: AnyLLM,
        endpoint: Endpoint,
        messages: list[dict[str, str]],
        request: dict[str, Any],
        options: Generation,
    ) -> Completion:
        """One provider call, metered: what it answered, what it cost, who answered and why it stopped."""
        try:
            reply = await client.acompletion(
                model=endpoint.model,
                messages=cast("list[dict[str, Any] | ChatCompletionMessage]", messages),
                response_format=request,
                stream=False,
                timeout=self._settings.timeout.total_seconds(),
                **options,
            )
        except Exception as error:
            msg = f"{endpoint.provider} failed the call: {type(error).__name__}: {error}"
            raise ProviderError(msg) from error
        completion = cast("Any", reply)
        tokens, choice = completion.usage, completion.choices[0]
        usage = Usage(
            input_tokens=getattr(tokens, "prompt_tokens", 0) or 0,
            output_tokens=getattr(tokens, "completion_tokens", 0) or 0,
            total_tokens=getattr(tokens, "total_tokens", 0) or 0,
            calls=1,
        )
        ### metered before any verdict: a reply that fails still spent its tokens.
        meter = METER.get()
        _ = meter.add(usage) if meter is not None else None
        return Completion(
            raw=choice.message.content or "",
            usage=usage,
            model=completion.model or endpoint.model,
            finish=getattr(choice, "finish_reason", None) or "",
            refusal=getattr(choice.message, "refusal", None) or "",
        )

    @staticmethod
    def _run_verdict(
        done: Completion, options: Generation, attempts: int, retries: int, spent: Usage
    ) -> Generation | None:
        """How the call stopped decides the next step: parse (None), ask again with a larger budget, or fail."""
        trace = {"raw": done.raw, "attempts": attempts, "usage": spent, "finish": done.finish}
        budget = options.get("max_tokens")
        match done:
            case Completion(refusal=refusal) if refusal:
                msg = f"{done.model} refused: {refusal}"
                raise RefusedError(msg, **trace)
            case Completion(finish="content_filter"):
                msg = f"{done.model} reply blocked by the provider's content filter"
                raise RefusedError(msg, **trace)
            case Completion(finish="length") if budget is not None and attempts <= retries:
                return {**options, "max_tokens": budget * 2}
            case Completion(finish="length"):
                limit = budget or "the provider's own (context exhausted)"
                msg = f"{done.model} reply cut at the token limit, max_tokens={limit}"
                raise TruncatedError(msg, **trace)
            case _:
                return None

    @staticmethod
    async def _common_release(client: AnyLLM) -> None:
        """Close a pooled client's underlying SDK client, sync or async alike, whichever the SDK offers."""
        closer = getattr(getattr(client, "client", None), "close", None)
        result = closer() if callable(closer) else None
        _ = await result if inspect.isawaitable(result) else result

    ############################################################

    ##### PUBLIC #####

    @staticmethod
    @contextmanager
    def meter() -> Iterator[UsageMeter]:
        """Add up the usage of every agent call made inside the block, in this task and the ones it awaits."""
        meter = UsageMeter()
        token = METER.set(meter)
        try:
            yield meter
        finally:
            METER.reset(token)

    @overload
    async def run[T: Model](
        self,
        instructions: str,
        prompt: Prompt,
        output: type[T],
        *,
        endpoint: Target = ...,
        api_base: str | None = ...,
        api_key: str | None = ...,
        **options: Unpack[Generation],
    ) -> Reply[T]: ...

    @overload
    async def run(
        self,
        instructions: str,
        prompt: Prompt,
        output: Schema,
        *,
        endpoint: Target = ...,
        api_base: str | None = ...,
        api_key: str | None = ...,
        **options: Unpack[Generation],
    ) -> Reply[dict[str, Any]]: ...

    async def run(
        self,
        instructions: str,
        prompt: Prompt,
        output: Output,
        *,
        endpoint: Target = Tier.MEDIUM,
        api_base: str | None = None,
        api_key: str | None = None,
        **options: Unpack[Generation],
    ) -> Reply[Any]:
        """One call: `instructions` + `prompt` in, the output in the shape asked out, validated and costed.

        `output` is always structured: a pydantic model, a msgspec Struct or a dataclass (validated into
        it) or a raw JSON Schema (validated as an object). `endpoint` is an `Endpoint` on the fly or a
        `Tier` from settings; `api_base` and `api_key` override whatever the endpoint or settings would
        give — a local server needs neither key nor argument. `options` reach the provider."""
        shape = shape_output(output)
        resolved = self._run_endpoint(endpoint, api_base, api_key)
        client = self._run_client(resolved)
        request = self._run_format(shape, resolved.provider)
        messages = self._run_messages(instructions, prompt)
        started, spent, attempts = time.perf_counter(), Usage(), 0
        retries = self._settings.retries
        while True:
            attempts += 1
            done = await self._run_call(client, resolved, messages, request, options)
            spent = spent + done.usage
            ### a larger budget comes back from the verdict: the same messages, asked again.
            match self._run_verdict(done, options, attempts, retries, spent):
                case None:
                    pass
                case larger:
                    options = larger
                    continue
            try:
                parsed = shape.parse(done.raw)
            except shape.errors as error:
                match attempts > retries:
                    case True:
                        msg = f"{done.model} gave no valid output: {error}"
                        raise InvalidError(
                            msg, raw=done.raw, attempts=attempts, usage=spent, finish=done.finish
                        ) from error
                    case _:
                        messages.extend(
                            (
                                {"role": Speaker.ASSISTANT, "content": done.raw},
                                {"role": Speaker.USER, "content": RETRY_PROMPT.format(error=error)},
                            )
                        )
                        continue
            return Reply(
                output=parsed,
                provider=resolved.provider,
                model=done.model,
                usage=spent,
                latency_ms=(time.perf_counter() - started) * MS_PER_SECOND,
                attempts=attempts,
            )

    def resolve(self, target: Target) -> Endpoint:
        """Where a call to `target` would go, every connection field resolved — what `run` itself would reach."""
        return self._run_endpoint(target, None, None)

    async def close(self) -> None:
        """Close every pooled client; the agent stays usable — the next call simply opens a fresh one."""
        clients, self._pool = list(self._pool.values()), {}
        for client in clients:
            await self._common_release(client)
