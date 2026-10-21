"""tests/unit/e_api/api/lifespan: what the lifespans log, recorded — structlog caches its bound logger on first use, so
a capture installed later never sees it; the lifespan module's `logger` is swapped for a recorder instead."""

from dataclasses import dataclass, field

import pytest

from e_api.api.lifespan import adapters


@dataclass(slots=True)
class LogRecorder:
    """Every event logged through it: its level, its name, its fields."""

    events: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append(("warning", event, fields))


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, object]]]:
    """The adapters lifespan's events as they are logged — level, name, fields."""
    recorder = LogRecorder()
    monkeypatch.setattr(adapters, "logger", recorder)
    return recorder.events
