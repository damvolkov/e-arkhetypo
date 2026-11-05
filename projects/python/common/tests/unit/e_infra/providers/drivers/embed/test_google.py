"""tests/unit/e_infra/providers/drivers/embed/google: gemini-embedding-001 behind `EmbedPort` — offline."""

from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from google.genai import errors
from pydantic import SecretStr as Secret

from e_infra.infra.errors import ModelError
from e_infra.ports.embed import EmbedPort
from e_infra.providers.drivers.embed import google as google_module
from e_infra.providers.drivers.embed.google import GoogleEmbedDriver
from unit.e_infra.conftest import google_embed_args


class FakeModels:
    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self.raises: BaseException | None = None

    async def embed_content(self, *, model: str, contents: list[str], config: Any) -> Any:
        self.asked.append({"model": model, "contents": contents, "config": config})
        match self.raises:
            case BaseException() as error:
                raise error
            case _:
                return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(len(text))] * 2) for text in contents])


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> FakeModels:
    fake = FakeModels()

    async def aclose() -> None: ...

    monkeypatch.setattr(
        google_module, "Client", lambda **_kw: SimpleNamespace(aio=SimpleNamespace(models=fake, aclose=aclose))
    )
    return fake


def settings(**values: Any) -> dict[str, Any]:
    return google_embed_args(api_key=Secret("k"), dimensions=2, batch=2, **values)


async def test_embed_google_meets_the_port() -> None:
    assert isinstance(GoogleEmbedDriver(**settings()), EmbedPort)


@pytest.mark.parametrize(("query", "task"), [(True, "RETRIEVAL_QUERY"), (False, "RETRIEVAL_DOCUMENT")])
async def test_embed_google_batches_in_order_with_its_task(models: FakeModels, query: bool, task: str) -> None:
    async with GoogleEmbedDriver(**settings()) as embed:
        assert await embed.embed(["a", "bb", "ccc"], query=query) == [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]
    assert [ask["contents"] for ask in models.asked] == [["a", "bb"], ["ccc"]]
    assert {(ask["model"], ask["config"].task_type, ask["config"].output_dimensionality) for ask in models.asked} == {
        ("gemini-embedding-001", task, 2)
    }


async def test_embed_google_nothing_is_no_call(models: FakeModels) -> None:
    async with GoogleEmbedDriver(**settings()) as embed:
        assert await embed.embed([]) == []
    assert models.asked == []


def test_embed_google_tokens_are_the_four_characters_rule() -> None:
    assert [GoogleEmbedDriver(**settings()).tokens(text) for text in ("", "abcd", "abcde")] == [0, 1, 2]


async def test_embed_google_health_embeds_one_word(models: FakeModels) -> None:
    async with GoogleEmbedDriver(**settings()) as embed:
        assert await embed.health() is True
    assert [ask["contents"] for ask in models.asked] == [["ping"]]


@pytest.mark.parametrize(
    "raised",
    [errors.APIError(500, {"error": {"message": "boom"}}), aiohttp.ClientConnectionError("refused"), TimeoutError()],
    ids=["api", "network", "timeout"],
)
async def test_embed_google_every_failure_is_a_model_error(models: FakeModels, raised: BaseException) -> None:
    models.raises = raised
    async with GoogleEmbedDriver(**settings()) as embed:
        with pytest.raises(ModelError):
            await embed.embed(["a"])


async def test_embed_google_not_open_refuses() -> None:
    with pytest.raises(ModelError, match="not open"):
        await GoogleEmbedDriver(**settings()).embed(["a"])
