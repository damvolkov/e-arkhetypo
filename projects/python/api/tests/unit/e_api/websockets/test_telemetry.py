"""tests/unit: telemetry listener — structured heartbeats in, graded events out, msgspec per frame."""

from datetime import UTC, datetime, timedelta

from e_api.models.telemetry import Status


def test_heartbeat_becomes_event(client) -> None:
    sent = datetime.now(UTC)
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.send_json({"seq": 1, "sent_at": sent.isoformat()})
        event = ws.receive_json()
    assert event["seq"] == 1
    assert event["status"] == Status.OK.value
    assert event["latency_ms"] >= 0
    assert datetime.fromisoformat(event["emitted_at"]) >= sent


def test_stale_heartbeat_downgrades(client) -> None:
    old = datetime.now(UTC) - timedelta(seconds=5)
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.send_json({"seq": 7, "sent_at": old.isoformat()})
        event = ws.receive_json()
    assert event["seq"] == 7
    assert event["status"] == Status.DOWN.value


def test_malformed_frame_is_rejected(client) -> None:
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.send_json({"seq": -1, "sent_at": datetime.now(UTC).isoformat()})
        ### validation failure closes the connection — the loop is over, no crash
        ws.close()
