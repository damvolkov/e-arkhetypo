"""tests/unit/e_infra/providers/drivers/llm/google: Gemini API or Vertex behind `LLMPort` — offline.

The SDK's client is a fake at its one seam (`Client`): what the driver builds, what it asks, and how each way a reply
can end becomes the tree's error."""

from types import SimpleNamespace
from typing import Any, ClassVar

import aiohttp
import pytest
from google.genai import errors, types
from pydantic import SecretStr as Secret

from e_infra.infra.errors import ModelError, RefusalError, TruncatedError
from e_infra.ports.llm import LLMPort
from e_infra.providers.drivers.llm import google as google_module
from e_infra.providers.drivers.llm.google import GoogleLLMDriver
from unit.e_infra.conftest import google_llm_args

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


def reply(text: str = '{"a": 1}', finish: types.FinishReason = types.FinishReason.STOP, block: Any = None) -> Any:
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=finish)],
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
    )


class FakeModels:
    def __init__(self, answer: Any) -> None:
        self.answer, self.asked = answer, []

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.asked.append({"model": model, "contents": contents, "config": config})
        match self.answer:
            case BaseException() as error:
                raise error
            case answer:
                return answer

    async def get(self, *, model: str) -> Any:
        self.asked.append({"get": model})
        match self.answer:
            case BaseException() as error:
                raise error
            case _:
                return SimpleNamespace(name=model)


class FakeClient:
    built: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, answer: Any, **kwargs: Any) -> None:
        FakeClient.built.append(kwargs)
        self.aio = SimpleNamespace(models=FakeModels(answer), aclose=self._aclose)
        self.closed = False

    async def _aclose(self) -> None:
        self.closed = True


@pytest.fixture
def answered(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point the driver at a fake client answering `answer`; the clients built are kept."""
    FakeClient.built = []

    def install(answer: Any = None) -> None:
        monkeypatch.setattr(google_module, "Client", lambda **kwargs: FakeClient(answer or reply(), **kwargs))

    return install


def gemini(**values: Any) -> dict[str, Any]:
    return google_llm_args(api_key=Secret("k"), model="gemini-3.8-flash", **values)


async def test_google_meets_the_port() -> None:
    assert isinstance(GoogleLLMDriver(**gemini()), LLMPort)
    assert GoogleLLMDriver(**gemini()).model == "gemini-3.8-flash"


async def test_google_gemini_builds_with_the_key_vertex_with_the_project(answered: Any) -> None:
    answered()
    async with GoogleLLMDriver(**gemini(timeout_ms=5000)):
        pass
    async with GoogleLLMDriver(
        **google_llm_args(enterprise=True, project="p", location="europe-southwest1", model="m")
    ):
        pass
    gem, vertex = FakeClient.built
    assert (gem["api_key"], gem["enterprise"], gem["http_options"].timeout) == ("k", False, 5000)
    assert (vertex["enterprise"], vertex["project"], vertex["location"], vertex.get("api_key")) == (
        True,
        "p",
        "europe-southwest1",
        None,
    )


async def test_google_asks_under_the_schema_with_no_sampling(answered: Any) -> None:
    answered()
    async with GoogleLLMDriver(**gemini()) as llm:
        assert await llm.structured("be exact", "read", SCHEMA) == {"a": 1}
        asked = llm._client.aio.models.asked[0]
    config = asked["config"]
    assert (asked["model"], asked["contents"], config.system_instruction) == ("gemini-3.8-flash", "read", "be exact")
    assert (config.response_mime_type, config.response_json_schema, config.temperature) == (
        "application/json",
        SCHEMA,
        None,
    )


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (reply('{"a": ', types.FinishReason.MAX_TOKENS), TruncatedError),
        (reply("", types.FinishReason.SAFETY), RefusalError),
        (reply("", types.FinishReason.PROHIBITED_CONTENT), RefusalError),
        (reply("", block=types.BlockedReason.SAFETY), RefusalError),
        (reply("not json"), ModelError),
        (errors.APIError(503, {"error": {"message": "overloaded"}}), ModelError),
        (aiohttp.ClientConnectionError("refused"), ModelError),
        (TimeoutError(), ModelError),
    ],
    ids=["truncated", "safety", "prohibited", "blocked-prompt", "not-json", "api-error", "network", "timeout"],
)
async def test_google_every_ending_is_a_typed_error(answered: Any, answer: Any, error: type[Exception]) -> None:
    answered(answer)
    async with GoogleLLMDriver(**gemini()) as llm:
        with pytest.raises(error):
            await llm.structured("s", "p", SCHEMA)


async def test_google_closes_its_client_and_refuses_when_closed(answered: Any) -> None:
    answered()
    driver = GoogleLLMDriver(**gemini())
    async with driver:
        client = driver._client
        assert await driver.health()
    assert client.closed
    with pytest.raises(ModelError, match="not open"):
        await driver.structured("s", "p", SCHEMA)


@pytest.mark.parametrize(
    "raised",
    [errors.APIError(404, {"error": {"message": "no such model"}}), aiohttp.ClientConnectionError("refused")],
    ids=["api", "network"],
)
async def test_google_health_that_fails_is_a_model_error(answered: Any, raised: BaseException) -> None:
    answered(raised)
    async with GoogleLLMDriver(**gemini()) as llm:
        with pytest.raises(ModelError):
            await llm.health()
