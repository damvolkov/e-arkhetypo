"""e_infra/providers/drivers/ner/gliner: NDJSON streamed both ways against a stand-in service, offline."""

from typing import TYPE_CHECKING, Any, Final

import msgspec
import pytest

from e_infra.infra.config.providers.drivers.ner.gliner import GlinerSettings
from e_infra.infra.errors import HttpError, ModelError
from e_infra.ports.ner import NerEntity, NerPort
from e_infra.providers.drivers.ner.gliner import GlinerDriver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from unit.e_infra.providers.drivers.conftest import Stub

PERSON: Final[dict[str, Any]] = {"start": 0, "end": 3, "text": "Ada", "label": "person", "score": 0.9}


def lines(*answers: object) -> bytes:
    return b"".join(msgspec.json.encode(answer) + b"\n" for answer in answers)


async def test_gliner_entities_matched_back_by_id_out_of_order(stub: Stub) -> None:
    stub.on(
        "POST", "/ner/batch", lambda _body: (200, lines({"id": "1", "entities": []}, {"id": "0", "entities": [PERSON]}))
    )
    async with GlinerDriver(GlinerSettings(url=stub.url)) as ner:
        assert isinstance(ner, NerPort)
        found = await ner.entities(["Ada wrote", "nothing"], labels=["person"], threshold=0.5)
    assert found == [(NerEntity(**PERSON),), ()]
    head, first, second = stub.bodies("/ner/batch")[0].splitlines()
    assert msgspec.json.decode(head) == {"labels": ["person"], "threshold": 0.5}
    assert (msgspec.json.decode(first), msgspec.json.decode(second)) == (
        {"id": "0", "text": "Ada wrote"},
        {"id": "1", "text": "nothing"},
    )


async def test_gliner_batches_and_no_text_no_call(stub: Stub) -> None:
    stub.on(
        "POST",
        "/ner/batch",
        lambda body: (200, lines(*({"id": str(n), "entities": []} for n in range(body.count(b"text"))))),
    )
    async with GlinerDriver(GlinerSettings(url=stub.url, batch=2)) as ner:
        assert await ner.entities(["a", "b", "c"], labels=["x"], threshold=0.1) == [(), (), ()]
        assert await ner.entities([], labels=["x"], threshold=0.1) == []
    assert len(stub.bodies("/ner/batch")) == 2


@pytest.mark.parametrize(
    "answer",
    [lines({"id": "0", "error": "too long"}), lines({"line": 2, "error": "bad line"}), lines()],
    ids=["item-refused", "line-refused", "unanswered"],
)
async def test_gliner_a_refusal_or_silence_fails_the_call(stub: Stub, answer: bytes) -> None:
    stub.on("POST", "/ner/batch", lambda _body: (200, answer))
    async with GlinerDriver(GlinerSettings(url=stub.url)) as ner:
        with pytest.raises(ModelError, match="answered"):
            await ner.entities(["a"], labels=["x"], threshold=0.1)


async def test_gliner_server_error_is_an_http_error(stub: Stub) -> None:
    stub.on("POST", "/ner/batch", lambda _body: (503, b"{}"))
    async with GlinerDriver(GlinerSettings(url=stub.url)) as ner:
        with pytest.raises(HttpError):
            await ner.entities(["a"], labels=["x"], threshold=0.1)


async def test_gliner_refresh_reads_the_card(stub: Stub) -> None:
    stub.json("GET", "/models", {"model": "gliner-x", "version": "abc"})
    async with GlinerDriver(GlinerSettings(url=stub.url)) as ner:
        assert ner.annotator == ""
        assert await ner.refresh() == "gliner:gliner-x@abc"
        assert ner.annotator == "gliner:gliner-x@abc"
        stub.routes.clear()
        with pytest.raises(HttpError):
            await ner.refresh()
        assert ner.annotator == "gliner:gliner-x@abc"


async def test_gliner_health_and_unopen(stub: Stub) -> None:
    stub.json("GET", "/ready", {})
    ner = GlinerDriver(GlinerSettings(url=stub.url))
    assert not await ner.health()
    with pytest.raises(ModelError, match="not open"):
        await ner.refresh()
    async with ner:
        assert await ner.health()
        stub.routes.clear()
        assert not await ner.health()


async def test_gliner_lines_cut_across_frames_and_skip_trailers() -> None:
    """A line split between two frames is joined; a trailer between frames is skipped; the last partial line comes out."""

    async def frames() -> AsyncIterator[object]:
        yield b'{"id": "0"}\n{"id"'
        yield {"trailer": "x"}
        yield memoryview(b': "1"}\nrest')

    cut = [part async for part in GlinerDriver._entities_lines(frames())]  # ty: ignore[invalid-argument-type]
    assert cut == [[b'{"id": "0"}'], [b'{"id": "1"}'], [b"rest"]]


async def test_gliner_exit_unopen_is_quiet() -> None:
    await GlinerDriver(GlinerSettings()).__aexit__(None, None, None)
