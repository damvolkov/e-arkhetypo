"""models/telemetry: structured websocket payloads — client heartbeat in, server event out."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

import msgspec

##### DEFAULTS #####
LAG_MS: float = 250.0
DOWN_MS: float = 1000.0


##### TYPES #####
class Status(StrEnum):
    OK = "ok"
    LAG = "lag"
    DOWN = "down"

    @classmethod
    def from_latency(cls, ms: float) -> Status:
        """Grade a round-trip into a status band."""
        match ms:
            case value if value < LAG_MS:
                return cls.OK
            case value if value < DOWN_MS:
                return cls.LAG
            case _:
                return cls.DOWN


class Heartbeat(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Inbound frame: a client's sequenced ping."""

    seq: Annotated[int, msgspec.Meta(ge=0)]
    sent_at: datetime


class TelemetryEvent(msgspec.Struct, frozen=True):
    """Outbound frame: server verdict on the heartbeat it just heard."""

    seq: int
    status: Status
    latency_ms: Annotated[float, msgspec.Meta(ge=0)]
    emitted_at: datetime
