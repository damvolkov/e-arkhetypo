"""tests/unit: instrument.models — run frames as one tagged union on the wire, the role spelled on every node frame."""

from datetime import UTC, datetime

import msgspec

from e_graph.instrument.models import NodeOutput, NodeRole, NodeStatus, RunEnd, RunFrame, RunStatus

FRAMES = msgspec.json.Decoder(RunFrame)


def test_frames_round_trip_by_tag() -> None:
    node = NodeOutput(
        run_id="r", name="n", category="extract", role=NodeRole.MID, status=NodeStatus.RUNNING, at=datetime.now(UTC)
    )
    end = RunEnd(run_id="r", status=RunStatus.SUCCEEDED, latency_ms=1.5, skipped=("x",))
    assert msgspec.json.decode(msgspec.json.encode(node))["type"] == "node"
    assert msgspec.json.decode(msgspec.json.encode(end))["type"] == "run"
    assert FRAMES.decode(msgspec.json.encode(node)) == node
    assert FRAMES.decode(msgspec.json.encode(end)) == end

    assert msgspec.json.decode(msgspec.json.encode(node))["role"] == "mid"
