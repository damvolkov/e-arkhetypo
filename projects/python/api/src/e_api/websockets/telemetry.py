"""websockets.telemetry: active listener — Heartbeat in, TelemetryEvent out, msgspec per frame.

`websocket_listener` owns accept/receive/loop and serializes the return value automatically; for pure
server push the sibling pattern is `websocket_stream` (async generator + DI), registered the same way.
"""

from datetime import UTC, datetime

from litestar import websocket_listener
from litestar.di import NamedDependency, Provide
from litestar.dto import MsgspecDTO
from litestar.handlers import WebsocketRouteHandler

from core.logger import logger
from e_api.api.deps import correlation_id
from e_api.models.telemetry import Heartbeat, Status, TelemetryEvent


async def telemetry(data: Heartbeat, correlation_id: NamedDependency[str]) -> TelemetryEvent:
    """Grade one heartbeat's arrival latency and answer with the round's verdict."""
    latency_ms = max(0.0, (datetime.now(UTC) - data.sent_at).total_seconds() * 1000)
    event = TelemetryEvent(
        seq=data.seq,
        status=Status.from_latency(latency_ms),
        latency_ms=latency_ms,
        emitted_at=datetime.now(UTC),
    )
    logger.info(
        "telemetry",
        seq=event.seq,
        status=event.status.value,
        latency_ms=round(event.latency_ms, 1),
        correlation=correlation_id,
    )
    return event


def ws_routes() -> tuple[WebsocketRouteHandler, ...]:
    """Fresh listener per app: litestar binds a route handler to the app it registers in, so no module singleton here."""
    listener = websocket_listener(
        "/ws/telemetry",
        name="telemetry",
        dto=MsgspecDTO[Heartbeat],
        dependencies={"correlation_id": Provide(correlation_id, sync_to_thread=False)},
    )
    return (listener(telemetry),)
