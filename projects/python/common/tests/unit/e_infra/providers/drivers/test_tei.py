"""tests/unit/e_infra/providers/drivers/tei: embeddings and reranking against a stand-in TEI, offline."""

from typing import TYPE_CHECKING, Any

import msgspec
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from e_infra.infra.config.embed import EmbedSettings
from e_infra.infra.config.rerank import RerankSettings
from e_infra.infra.errors import HttpError, ModelError
from e_infra.ports.embed import EmbedPort
from e_infra.ports.rerank import RerankPort
from e_infra.providers.drivers import tei
from e_infra.providers.drivers.tei import TeiEmbedDriver, TeiRerankDriver

if TYPE_CHECKING:
    from e_infra.ports.http import HttpPort
    from unit.e_infra.providers.drivers.conftest import Stub


@pytest.fixture(autouse=True)
def words(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Hub never answers in a unit test: the model's tokenizer is a three-word vocabulary."""
    tokenizer = Tokenizer(models.WordLevel({"a": 0, "b": 1, "[UNK]": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    monkeypatch.setattr(tei.Tokenizer, "from_pretrained", lambda _model: tokenizer)


async def test_embed_vectors_in_order_with_the_query_prefix(stub: Stub, http: HttpPort) -> None:
    stub.json("POST", "/embed", [[0.1, 0.2], [0.3, 0.4]])
    conf = EmbedSettings(url=stub.url, query_prefix="Q: ")
    async with TeiEmbedDriver(http, conf) as embed:
        assert isinstance(embed, EmbedPort)
        assert await embed.embed(["x", "y"], query=True) == [[0.1, 0.2], [0.3, 0.4]]
        assert await embed.embed([]) == []
    sent = msgspec.json.decode(stub.bodies("/embed")[0])
    assert (sent["inputs"], sent["normalize"], sent["truncate"]) == (["Q: x", "Q: y"], True, True)
    assert len(stub.bodies("/embed")) == 1


async def test_embed_tokens_from_the_models_tokenizer(stub: Stub, http: HttpPort) -> None:
    async with TeiEmbedDriver(http, EmbedSettings(url=stub.url)) as embed:
        assert embed.tokens("a b a") == 3
    with pytest.raises(ModelError, match="not open"):
        embed.tokens("a")


async def test_embed_server_error_is_an_http_error(stub: Stub, http: HttpPort) -> None:
    stub.json("POST", "/embed", {"error": "boom"}, status=500)
    async with TeiEmbedDriver(http, EmbedSettings(url=stub.url)) as embed:
        with pytest.raises(HttpError) as caught:
            await embed.embed(["x"])
    assert caught.value.status == 500


async def test_embed_health(stub: Stub, http: HttpPort) -> None:
    stub.on("GET", "/health", lambda _body: (200, b""))
    embed = TeiEmbedDriver(http, EmbedSettings(url=stub.url))
    assert not await embed.health()
    async with embed:
        assert await embed.health()
        stub.on("GET", "/health", lambda _body: (503, b""))
        assert not await embed.health()


async def test_rerank_scores_back_in_the_texts_order_by_batch(stub: Stub, http: HttpPort) -> None:
    """TEI answers best first by index; two requests of two texts, the scores put back in order."""
    answers: list[Any] = [[{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}], [{"index": 0, "score": 0.5}]]
    stub.on("POST", "/rerank", lambda _body: (200, msgspec.json.encode(answers.pop(0))))
    async with TeiRerankDriver(http, RerankSettings(url=stub.url, batch=2)) as rerank:
        assert isinstance(rerank, RerankPort)
        assert await rerank.rerank("q", ["a", "b", "c"]) == [0.1, 0.9, 0.5]
        assert await rerank.rerank("q", []) == []
    assert len(stub.bodies("/rerank")) == 2


async def test_rerank_health(stub: Stub, http: HttpPort) -> None:
    stub.on("GET", "/health", lambda _body: (200, b""))
    async with TeiRerankDriver(http, RerankSettings(url=stub.url)) as rerank:
        assert await rerank.health()
    stub.routes.clear()
    async with TeiRerankDriver(http, RerankSettings(url=stub.url)) as rerank:
        assert not await rerank.health()
