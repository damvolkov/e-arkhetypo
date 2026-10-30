"""tests/unit/e_infra/infra: the events the in-process publisher is tested with, and the supervisor's logger recorder.

`Saved` and `Other` are the events the publisher is tested with; `warnings` records what the supervisor warns, in
place of its logger."""

import msgspec
import pytest

from unit.e_infra.conftest import Warnings


class Saved(msgspec.Struct, frozen=True):
    """An event a test publishes: something saved, by name."""

    name: str


class Other(msgspec.Struct, frozen=True):
    """An event of another type: its subscribers never see a `Saved`."""

    name: str


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> Warnings:
    recorder = Warnings()
    monkeypatch.setattr("e_infra.infra.background.logger", recorder)
    return recorder
