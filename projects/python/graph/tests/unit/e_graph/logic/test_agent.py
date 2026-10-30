"""tests/unit: logic.agent — resolution, pool, schema, parse, retries, errors and the meter, the provider mocked."""

import dataclasses
import re
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import msgspec
import pydantic
import pytest
from any_llm import AnyLLM
from any_llm.exceptions import MissingApiKeyError

from e_graph.logic.agent import DUMMY_KEY, RETRY_PROMPT, AgnosticAgent, shape_output
from e_graph.logic.errors import (
    AgentError,
    EndpointError,
    InvalidError,
    OutputError,
    ProviderError,
    RefusedError,
    SchemaError,
    TruncatedError,
)
from e_graph.logic.models import Endpoint, Message, Provider, Speaker, Tier, Usage

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture, MockType

VLLM = Endpoint(provider=Provider.VLLM, model="qwen", api_base="http://vllm/v1")


class Ack(msgspec.Struct):
    ok: bool


class Census(pydantic.BaseModel):
    city: str
    people: int


@dataclasses.dataclass(frozen=True)
class Kind:
    kind: str
    pages: int


class Invoice(msgspec.Struct):
    total: float
    lines: list[Line]


class Line(msgspec.Struct):
    sku: str
    note: str | None = None


def completion(
    content: str | None = '{"ok": true}',
    *,
    usage: object = None,
    model: str | None = "served",
    finish: str = "stop",
    refusal: str | None = None,
) -> SimpleNamespace:
    """A chat completion as any-llm returns it, reduced to what the agent reads."""
    tokens = SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5) if usage is None else usage
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=tokens, model=model)


@pytest.fixture
def client(mocker: MockerFixture) -> MockType:
    """The provider client every connect hands out: `acompletion` answers what each test queues."""
    fake = mocker.Mock(spec=["acompletion", "client"])
    fake.acompletion = mocker.AsyncMock(return_value=completion())
    fake.client = mocker.Mock(spec=["close"])
    return fake


@pytest.fixture
def create(mocker: MockerFixture, client: MockType) -> MockType:
    return mocker.patch.object(AnyLLM, "create", return_value=client)


@pytest.fixture
def compatible(mocker: MockerFixture, client: MockType) -> MockType:
    return mocker.patch.object(AnyLLM, "create_openai_compatible", return_value=client)


@pytest.fixture
def agent(settings: Callable[..., Any], create: MockType) -> AgnosticAgent:
    return AgnosticAgent(settings(retries=1))


def sent(client: MockType, call: int = -1) -> dict[str, Any]:
    """The keyword arguments of one provider call."""
    return client.acompletion.await_args_list[call].kwargs


##### RESOLUTION #####
async def test_run_tier_resolved_from_settings(settings: Callable[..., Any], create: MockType) -> None:
    agent = AgnosticAgent(settings(high={"provider": "vllm", "model": "big", "api_base": "http://h/v1"}))
    reply = await agent.run("be brief", "hi", Ack, endpoint=Tier.HIGH)
    assert (reply.output, reply.provider, reply.model, reply.attempts) == (Ack(ok=True), Provider.VLLM, "served", 1)
    create.assert_called_once_with("vllm", api_key=DUMMY_KEY, api_base="http://h/v1")


def test_resolve_names_where_a_call_would_go(settings: Callable[..., Any]) -> None:
    agent = AgnosticAgent(settings(medium={"provider": "vllm", "model": "m", "api_base": "http://v/v1"}))
    endpoint = agent.resolve(Tier.MEDIUM)
    assert (endpoint.provider, endpoint.model, endpoint.api_base, endpoint.api_key) == (
        Provider.VLLM,
        "m",
        "http://v/v1",
        DUMMY_KEY,
    )


async def test_run_tier_carries_its_key_and_options(settings: Callable[..., Any], create: MockType) -> None:
    tier = {"provider": "openai", "model": "m", "api_key": "k-tier", "options": {"organization": "o"}}
    await AgnosticAgent(settings(low=tier)).run("i", "p", Ack, endpoint=Tier.LOW)
    create.assert_called_once_with("openai", api_key="k-tier", api_base=None, organization="o")


async def test_run_arguments_beat_endpoint_and_settings(settings: Callable[..., Any], create: MockType) -> None:
    agent = AgnosticAgent(settings(openai_api_key="from-settings", openai_api_base="http://settings"))
    endpoint = Endpoint(provider=Provider.OPENAI, model="m", api_base="http://endpoint", api_key="from-endpoint")
    await agent.run("i", "p", Ack, endpoint=endpoint, api_base="http://run", api_key="from-run")
    await agent.run("i", "p", Ack, endpoint=endpoint)
    await agent.run("i", "p", Ack, endpoint=Endpoint(provider=Provider.OPENAI, model="m"))
    assert [call.kwargs for call in create.call_args_list] == [
        {"api_key": "from-run", "api_base": "http://run"},
        {"api_key": "from-endpoint", "api_base": "http://endpoint"},
        {"api_key": "from-settings", "api_base": "http://settings"},
    ]


async def test_run_custom_reached_openai_compatible(agent: AgnosticAgent, compatible: MockType) -> None:
    endpoint = Endpoint(provider=Provider.CUSTOM, model="m", options={"timeout": 5})
    await agent.run("i", "p", Ack, endpoint=endpoint, api_base="http://own/v1")
    compatible.assert_called_once_with(name="custom", api_base="http://own/v1", api_key=DUMMY_KEY, timeout=5)


##### POOL #####
async def test_pool_reuses_a_client_per_provider_base_key(agent: AgnosticAgent, create: MockType) -> None:
    await agent.run("i", "p", Ack, endpoint=VLLM)
    await agent.run("i", "p", Ack, endpoint=VLLM)
    await agent.run("i", "p", Ack, endpoint=VLLM, api_key="other")
    assert create.call_count == 2


async def test_close_releases_sync_and_async_clients(
    settings: Callable[..., Any], mocker: MockerFixture, client: MockType
) -> None:
    async_client = mocker.Mock(spec=["acompletion", "client"], acompletion=client.acompletion)
    async_client.client = mocker.Mock(spec=["close"], close=mocker.AsyncMock())
    bare = mocker.Mock(spec=["acompletion"], acompletion=client.acompletion)
    mocker.patch.object(AnyLLM, "create", side_effect=[client, async_client, bare, client])
    async with AgnosticAgent(settings()) as agent:
        for key in ("a", "b", "c"):
            await agent.run("i", "p", Ack, endpoint=VLLM, api_key=key)
    client.client.close.assert_called_once_with()
    async_client.client.close.assert_awaited_once_with()
    await agent.run("i", "p", Ack, endpoint=VLLM, api_key="a")
    assert client.acompletion.await_count == 4


##### SCHEMA #####
async def test_schema_from_a_model(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.return_value = completion('{"total": 2.5, "lines": [{"sku": "a"}]}')
    reply = await agent.run("i", "p", Invoice, endpoint=VLLM)
    assert reply.output == Invoice(total=2.5, lines=[Line(sku="a")])
    request = sent(client)["response_format"]
    assert (request["type"], request["json_schema"]["strict"]) == ("json_schema", False)
    assert request["json_schema"]["schema"] == msgspec.json.schema(Invoice)
    assert request["json_schema"]["name"] == "Invoice"


async def test_schema_strict_closes_every_object(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.return_value = completion('{"total": 1, "lines": []}')
    await agent.run("i", "p", Invoice, endpoint=Endpoint(provider=Provider.OPENAI, model="m", api_key="k"))
    request = sent(client)["response_format"]["json_schema"]
    line = request["schema"]["$defs"]["Line"]
    assert request["strict"] is True
    assert (line["required"], line["additionalProperties"]) == (["sku", "note"], False)
    assert request["schema"]["$defs"]["Invoice"]["required"] == ["total", "lines"]


async def test_schema_raw_mapping_named_by_title(agent: AgnosticAgent, client: MockType) -> None:
    schema = {"title": "fused", "type": "object", "properties": {"kind": {"type": "string"}}}
    client.acompletion.return_value = completion('{"kind": "invoice"}')
    reply = await agent.run("i", "p", schema, endpoint=VLLM)
    assert reply.output == {"kind": "invoice"}
    assert sent(client)["response_format"]["json_schema"] == {"name": "fused", "schema": schema, "strict": False}


async def test_generation_options_and_turns_reach_the_provider(agent: AgnosticAgent, client: MockType) -> None:
    turns = [Message(Speaker.USER, "q"), Message(Speaker.ASSISTANT, "a"), Message(Speaker.USER, "again")]
    reply = await agent.run("sys", turns, Ack, endpoint=VLLM, temperature=0.0, seed=7)
    request = sent(client)
    assert (reply.output, request["stream"]) == (Ack(ok=True), False)
    assert (request["temperature"], request["seed"], request["timeout"]) == (0.0, 7, 60.0)
    assert [message["role"] for message in request["messages"]] == ["system", "user", "assistant", "user"]


async def test_shape_from_a_pydantic_model(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.return_value = completion('{"city": "Paris", "people": 2}')
    reply = await agent.run("i", "p", Census, endpoint=VLLM)
    assert reply.output == Census(city="Paris", people=2)
    assert sent(client)["response_format"]["json_schema"] == {
        "name": "Census",
        "schema": Census.model_json_schema(),
        "strict": False,
    }


async def test_shape_from_a_dataclass(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.return_value = completion('{"kind": "invoice", "pages": 3}')
    reply = await agent.run("i", "p", Kind, endpoint=VLLM)
    assert reply.output == Kind(kind="invoice", pages=3)
    assert sent(client)["response_format"]["json_schema"]["name"] == "Kind"


##### RETRIES #####
async def test_invalid_reply_retried_with_the_error(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.side_effect = [completion('{"total": "x"}'), completion('{"total": 1, "lines": []}')]
    reply = await agent.run("i", "p", Invoice, endpoint=VLLM)
    assert (reply.attempts, reply.usage) == (2, Usage(input_tokens=6, output_tokens=4, total_tokens=10, calls=2))
    retried = sent(client)["messages"]
    assert retried[-2] == {"role": Speaker.ASSISTANT, "content": '{"total": "x"}'}
    assert retried[-1]["content"].startswith(RETRY_PROMPT.split("{", 1)[0])
    assert "Expected `float`" in retried[-1]["content"]


async def test_non_object_reply_retried(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.side_effect = [completion("[1]"), completion('{"a": 1}')]
    reply = await agent.run("i", "p", {"type": "object"}, endpoint=VLLM)
    assert (reply.output, reply.attempts) == ({"a": 1}, 2)
    assert 'is not of type "object"' in sent(client)["messages"][-1]["content"]


async def test_raw_schema_reply_validated_in_rust(agent: AgnosticAgent, client: MockType) -> None:
    schema = {"type": "object", "properties": {"kind": {"enum": ["invoice", "receipt"]}}, "required": ["kind"]}
    client.acompletion.side_effect = [completion('{"kind": "memo"}'), completion('{"kind": "receipt"}')]
    reply = await agent.run("i", "p", schema, endpoint=VLLM)
    assert (reply.output, reply.attempts) == ({"kind": "receipt"}, 2)
    assert '"memo" is not one of' in sent(client)["messages"][-1]["content"]


def test_model_shape_resolved_once_per_class() -> None:
    assert shape_output(Census) is shape_output(Census)
    assert shape_output(Kind) is shape_output(Kind)
    assert shape_output({"type": "object"}) is not shape_output({"type": "object"})


async def test_pydantic_invalid_reply_retried(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.side_effect = [completion('{"city": "Paris"}'), completion('{"city": "Paris", "people": 2}')]
    reply = await agent.run("i", "p", Census, endpoint=VLLM)
    assert reply.attempts == 2
    assert "people" in sent(client)["messages"][-1]["content"]


##### BUDGET #####
async def test_cut_reply_asked_again_with_double_budget(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.side_effect = [completion('{"ok": tr', finish="length"), completion()]
    reply = await agent.run("i", "p", Ack, endpoint=VLLM, max_tokens=8)
    assert (reply.output, reply.attempts, reply.usage.calls) == (Ack(ok=True), 2, 2)
    assert [call.kwargs["max_tokens"] for call in client.acompletion.await_args_list] == [8, 16]
    assert sent(client)["messages"] == sent(client, 0)["messages"]


async def test_no_token_limit_imposed_by_default(agent: AgnosticAgent, client: MockType) -> None:
    await agent.run("i", "p", Ack, endpoint=VLLM)
    assert "max_tokens" not in sent(client)


##### PROVIDER #####
async def test_sparse_completion_read_safely(agent: AgnosticAgent, client: MockType) -> None:
    client.acompletion.return_value = completion(usage=SimpleNamespace(prompt_tokens=None), model=None)
    reply = await agent.run("i", "p", Ack, endpoint=VLLM)
    assert (reply.output, reply.model, reply.usage) == (Ack(ok=True), "qwen", Usage(calls=1))
    assert reply.latency_ms >= 0


##### METER #####
async def test_meter_adds_up_calls_inside_the_block(agent: AgnosticAgent) -> None:
    await agent.run("i", "outside", Ack, endpoint=VLLM)
    with AgnosticAgent.meter() as meter:
        assert meter.usage is None
        await agent.run("i", "p", Ack, endpoint=VLLM)
        await agent.run("i", "p", Ack, endpoint=VLLM)
    assert cast("Usage", meter.usage) == Usage(input_tokens=6, output_tokens=4, total_tokens=10, calls=2)


##### FAILURES — every error the agent raises, each from the condition that causes it #####
@dataclasses.dataclass(frozen=True, slots=True)
class Failure:
    """One way a run fails: the setup that causes it, the typed error it must raise, and its trace."""

    error: type[AgentError]
    match: str
    output: Any = Ack
    endpoint: Any = VLLM
    tiers: dict[str, Any] = dataclasses.field(default_factory=dict)
    connect: Exception | None = None
    replies: tuple[Any, ...] = ()
    options: dict[str, Any] = dataclasses.field(default_factory=dict)
    calls: int = 0
    finish: str = ""


CUT = completion('{"ok": tr', finish="length")
FAILURES: dict[str, Failure] = {
    "schema-class": Failure(SchemaError, "no output shape for <class 'int'>", output=int),
    "schema-none": Failure(SchemaError, "no output shape for None", output=None),
    "schema-string": Failure(SchemaError, "no output shape for 'schema'", output="schema"),
    "schema-generic": Failure(SchemaError, "no output shape", output=list[int]),
    "schema-array-root": Failure(SchemaError, "object root", output={"type": "array"}),
    "schema-untyped-root": Failure(SchemaError, "object root", output={"properties": {}}),
    "schema-invalid": Failure(SchemaError, "no valid JSON Schema", output={"type": "object", "minProperties": "x"}),
    "endpoint-tier-unset": Failure(EndpointError, "tier medium has no endpoint", endpoint=Tier.MEDIUM),
    "endpoint-custom-unbased": Failure(
        EndpointError, "CUSTOM_API_BASE", endpoint=Endpoint(provider=Provider.CUSTOM, model="m")
    ),
    "endpoint-key-missing": Failure(
        EndpointError,
        "openai needs an api_key",
        endpoint=Endpoint(provider=Provider.OPENAI, model="m"),
        connect=MissingApiKeyError("openai", "OPENAI_API_KEY"),
    ),
    "provider-transport": Failure(
        ProviderError, "vllm failed the call: ConnectionError: refused", replies=(ConnectionError("refused"),), calls=1
    ),
    "provider-timeout": Failure(ProviderError, "TimeoutError", replies=(TimeoutError(),), calls=1),
    "invalid-json": Failure(
        InvalidError, "gave no valid output", replies=(completion("nope"),) * 2, calls=2, finish="stop"
    ),
    "invalid-empty": Failure(
        InvalidError, "gave no valid output", replies=(completion(None),) * 2, calls=2, finish="stop"
    ),
    "invalid-msgspec": Failure(
        InvalidError,
        "Expected `float`",
        output=Invoice,
        replies=(completion('{"total": "x"}'),) * 2,
        calls=2,
        finish="stop",
    ),
    "invalid-pydantic": Failure(
        InvalidError, "people", output=Census, replies=(completion('{"city": "x"}'),) * 2, calls=2, finish="stop"
    ),
    "invalid-raw-schema": Failure(
        InvalidError,
        '"memo" is not one of',
        output={"type": "object", "properties": {"kind": {"enum": ["invoice"]}}},
        replies=(completion('{"kind": "memo"}'),) * 2,
        calls=2,
        finish="stop",
    ),
    "truncated-provider-limit": Failure(
        TruncatedError, "max_tokens=the provider's own", replies=(CUT,), calls=1, finish="length"
    ),
    "truncated-budget-spent": Failure(
        TruncatedError, "max_tokens=16", replies=(CUT, CUT), options={"max_tokens": 8}, calls=2, finish="length"
    ),
    "refused-filter": Failure(
        RefusedError,
        "content filter",
        replies=(completion("", finish="content_filter"),),
        calls=1,
        finish="content_filter",
    ),
    "refused-model": Failure(
        RefusedError,
        "served refused: not allowed",
        replies=(completion(None, refusal="not allowed"),),
        calls=1,
        finish="stop",
    ),
}


@pytest.mark.parametrize("case", FAILURES.values(), ids=FAILURES.keys())
async def test_run_fails_typed_and_traced(
    settings: Callable[..., Any], create: MockType, client: MockType, case: Failure
) -> None:
    create.side_effect = case.connect
    client.acompletion.side_effect = list(case.replies) or None
    agent = AgnosticAgent(settings(retries=1, **case.tiers))
    with AgnosticAgent.meter() as meter, pytest.raises(case.error, match=re.escape(case.match)) as caught:
        await agent.run("i", "p", case.output, endpoint=case.endpoint, **case.options)
    assert type(caught.value) is case.error
    assert client.acompletion.await_count == case.calls
    ### every call the provider answered is metered, failed or not; a call that never came back cost nothing.
    answered = 0 if case.error is ProviderError else case.calls
    assert (meter.usage.calls if meter.usage else 0) == answered
    match caught.value:
        case OutputError() as failed:
            assert (failed.attempts, failed.usage.calls, failed.finish) == (case.calls, case.calls, case.finish)
            assert failed.raw == (case.replies[-1].choices[0].message.content or "")
            assert f"[finish={case.finish}, attempts={case.calls}, output_tokens={2 * case.calls}]" in str(failed)
        case _:
            pass
