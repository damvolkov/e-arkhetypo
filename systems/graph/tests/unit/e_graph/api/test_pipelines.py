"""tests/unit: api.router.pipelines — list, topology, batch and stream, addressed by id, as any client would."""

from typing import TYPE_CHECKING

import msgspec
import pytest
from litestar.exceptions import WebSocketDisconnect
from litestar.status_codes import WS_1007_INVALID_FRAME_PAYLOAD_DATA
from syrupy.extensions.json import JSONSnapshotExtension

from e_graph.instrument.models import NodeOutput, NodeRole, NodeStatus, RunEnd, RunFrame, RunStatus

if TYPE_CHECKING:
    from pytest_resources import Resources
    from syrupy.assertion import SnapshotAssertion

FRAMES = msgspec.json.Decoder(RunFrame)


@pytest.fixture
def snapshot_json(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.use_extension(JSONSnapshotExtension)


def test_list_names_every_pipeline(client) -> None:
    response = client.get("/api/pipelines/list")
    assert response.status_code == 200
    doc, filing, note = response.json()
    assert (doc["id"], doc["nodes"]) == ("doc", 7)
    assert doc["summary"].startswith("Document intake")
    assert (filing["id"], filing["nodes"]) == ("filing", 4)
    assert (note["id"], note["nodes"]) == ("note", 5)


def test_topology_is_the_pinned_map(client, snapshot_json: SnapshotAssertion) -> None:
    """Every node's role, rank and lane and every arc of the doc pipeline; a drift fails until `--snapshot-update`."""
    response = client.get("/api/pipelines/topology/doc")
    assert response.status_code == 200
    assert response.json() == snapshot_json


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/pipelines/topology/nope"), ("post", "/api/pipelines/batch/nope")],
)
def test_unknown_id_is_a_404_naming_the_known(client, method: str, path: str) -> None:
    response = client.request(method, path, json={"data": {}})
    assert response.status_code == 404
    assert "known: ['doc', 'filing', 'note']" in response.json()["detail"]


def test_batch_succeeds(client, resources: Resources) -> None:
    response = client.post("/api/pipelines/batch/doc", json=resources.runs.ok)
    assert response.status_code == 200
    body = response.json()
    assert body["end"]["status"] == "succeeded"
    assert (body["outputs"][-1]["name"], body["outputs"][-1]["role"]) == ("report", "end")


def test_batch_failure_is_a_verdict(client, resources: Resources) -> None:
    response = client.post("/api/pipelines/batch/doc", json=resources.runs.fail)
    assert response.status_code == 200
    assert response.json()["end"]["skipped"] == ["validate", "transform", "report"]


def test_stream_frames_until_the_end(client, resources: Resources) -> None:
    with client.websocket_connect("/api/pipelines/stream/doc") as socket:
        socket.send_json(resources.runs.ok)
        frames: list[RunFrame] = [FRAMES.decode(socket.receive_text())]
        while not isinstance(frames[-1], RunEnd):
            frames.append(FRAMES.decode(socket.receive_text()))
    first, end = frames[0], frames[-1]
    assert isinstance(first, NodeOutput)
    assert (first.name, first.role, first.status) == ("ingest", NodeRole.START, NodeStatus.RUNNING)
    assert isinstance(end, RunEnd)
    assert end.status is RunStatus.SUCCEEDED
    assert {frame.run_id for frame in frames} == {end.run_id}


def test_stream_refuses_malformed_request(client) -> None:
    with client.websocket_connect("/api/pipelines/stream/doc") as socket:
        socket.send_text("{broken")
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_text()
    assert closed.value.code == WS_1007_INVALID_FRAME_PAYLOAD_DATA
