"""models.run: what a caller sends to start a run — the seed of the run's `data` zone."""

from typing import Any

import msgspec


class RunRequest(msgspec.Struct, frozen=True, kw_only=True):
    """`data` is copied into `RunState.data` before the first node runs; the nodes read it from there."""

    data: dict[str, Any] = msgspec.field(default_factory=dict)
