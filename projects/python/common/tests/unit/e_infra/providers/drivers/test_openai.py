"""tests/unit/e_infra/providers/drivers/openai: answers under a JSON schema, the gates, and every way a reply goes wrong."""

import time
from typing import TYPE_CHECKING

import msgspec
import pytest

from e_infra.infra.config.base import Secret
from e_infra.infra.config.llm import LlmSettings
from e_infra.infra.errors import HttpError, ModelError, TruncatedError
from e_infra.ports.llm import LlmPort
from e_infra.providers.drivers.openai import OpenaiBucket, OpenaiDriver

if TYPE_CHECKING:
    from e_infra.ports.http import HttpPort
    from unit.e_infra.providers.drivers.conftest import Stub

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}}


def completion(content: str | None, finish: str = "stop") -> dict[str, object]:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


def settings(stub: Stub, **values: object) -> LlmSettings:
    return LlmSettings(url=f"{stub.url}/v1", key=Secret("k"), **values)  # ty: ignore[invalid-argument-type]


async def test_openai_structured_answer_under_the_schema(stub: Stub, http: HttpPort) -> None:
    stub.json("POST", "/v1/chat/completions", completion('{"n": 3}'))
    async with OpenaiDriver(http, settings(stub, model="m", extra={"enable_thinking": False})) as llm:
        assert isinstance(llm, LlmPort)
        assert (await llm.structured("sys", "ask", SCHEMA), llm.model) == ({"n": 3}, "m")
    _method, _path, headers, body = stub.sent[0]
    sent = msgspec.json.decode(body)
    assert headers["authorization"] == "Bearer k"
    assert (sent["model"], sent["temperature"], sent["enable_thinking"]) == ("m", 0, False)
    assert sent["response_format"]["json_schema"] == {"name": "answer", "schema": SCHEMA, "strict": True}
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


async def test_openai_no_key_no_bearer(stub: Stub, http: HttpPort) -> None:
    stub.json("POST", "/v1/chat/completions", completion("{}"))
    async with OpenaiDriver(http, LlmSettings(url=f"{stub.url}/v1")) as llm:
        await llm.structured("s", "p", SCHEMA)
    assert "authorization" not in stub.sent[0][2]


@pytest.mark.parametrize(
    ("payload", "error", "message"),
    [
        (completion("not json", "length"), TruncatedError, "finish length"),
        (completion("not json"), ModelError, "not JSON"),
        (completion(None), ModelError, "no content"),
        ({"choices": []}, ModelError, "no content"),
        ({"unexpected": 1}, ModelError, "envelope"),
    ],
    ids=["truncated", "not-json", "null-content", "no-choice", "no-envelope"],
)
async def test_openai_reply_outside_the_contract(
    stub: Stub, http: HttpPort, payload: object, error: type[Exception], message: str
) -> None:
    stub.json("POST", "/v1/chat/completions", payload)
    async with OpenaiDriver(http, settings(stub)) as llm:
        with pytest.raises(error, match=message):
            await llm.structured("s", "p", SCHEMA)


async def test_openai_server_error_is_an_http_error(stub: Stub, http: HttpPort) -> None:
    stub.json("POST", "/v1/chat/completions", {}, status=429)
    async with OpenaiDriver(http, settings(stub)) as llm:
        with pytest.raises(HttpError) as caught:
            await llm.structured("s", "p", SCHEMA)
    assert caught.value.status == 429


async def test_openai_health_lists_the_models(stub: Stub, http: HttpPort) -> None:
    stub.json("GET", "/v1/models", {"data": []})
    async with OpenaiDriver(http, settings(stub)) as llm:
        assert await llm.health()
        stub.routes.clear()
        assert not await llm.health()
    assert stub.sent[0][2]["authorization"] == "Bearer k"


async def test_openai_bucket_waits_for_its_own_token() -> None:
    """Burst of `rpm`, then a take owes: it sleeps until its own token has refilled."""
    bucket = OpenaiBucket(rpm=6000)
    bucket._tokens = -6.0
    start = time.monotonic()
    await bucket.take()
    assert time.monotonic() - start >= 0.05
