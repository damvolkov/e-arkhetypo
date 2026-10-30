"""e_infra/providers/drivers/rerank/tei: reranking against a stand-in TEI, offline."""

from typing import TYPE_CHECKING, Any

import msgspec

from e_infra.infra.config.providers.drivers.rerank.tei import TeiRerankSettings
from e_infra.ports.rerank import RerankPort
from e_infra.providers.drivers.rerank.tei import TeiRerankDriver

if TYPE_CHECKING:
    from e_infra.ports.http import HttpPort
    from unit.e_infra.conftest import Logs
    from unit.e_infra.providers.drivers.conftest import Stub


async def test_rerank_scores_back_in_the_texts_order_by_batch(stub: Stub, http: HttpPort) -> None:
    """TEI answers best first by index; two requests of two texts, the scores put back in order."""
    answers: list[Any] = [[{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}], [{"index": 0, "score": 0.5}]]
    stub.on("POST", "/rerank", lambda _body: (200, msgspec.json.encode(answers.pop(0))))
    async with TeiRerankDriver(http, TeiRerankSettings(url=stub.url, batch=2)) as rerank:
        assert isinstance(rerank, RerankPort)
        assert await rerank.rerank("q", ["a", "b", "c"]) == [0.1, 0.9, 0.5]
        assert await rerank.rerank("q", []) == []
    assert len(stub.bodies("/rerank")) == 2


async def test_rerank_health(stub: Stub, http: HttpPort) -> None:
    stub.on("GET", "/health", lambda _body: (200, b""))
    async with TeiRerankDriver(http, TeiRerankSettings(url=stub.url)) as rerank:
        assert await rerank.health()
    stub.routes.clear()
    async with TeiRerankDriver(http, TeiRerankSettings(url=stub.url)) as rerank:
        assert not await rerank.health()


async def test_rerank_lifecycle_requests_and_an_unhealthy_server_are_logged(
    stub: Stub, http: HttpPort, logs: Logs
) -> None:
    stub.on("POST", "/rerank", lambda _body: (200, msgspec.json.encode([{"index": 0, "score": 0.5}])))
    async with TeiRerankDriver(http, TeiRerankSettings(url=stub.url)) as rerank:
        await rerank.rerank("q", ["a"])
        assert not await rerank.health()
    assert logs.at("info", "tei") == ["tei rerank opened", "tei rerank closed"]
    assert logs.at("debug", "tei") == ["tei rerank"]
    assert logs.at("warning", "tei") == ["tei rerank unhealthy"]
