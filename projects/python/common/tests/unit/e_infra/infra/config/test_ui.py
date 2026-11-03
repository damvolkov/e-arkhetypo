"""tests/unit/e_infra/infra/config: UISettings — the canvas tunables, defaults and env overrides."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.ui import UISettings

if TYPE_CHECKING:
    import pytest


def test_ui_defaults() -> None:
    ui = UISettings()
    assert ui.toast == timedelta(seconds=2.5)
    assert ui.pace == timedelta(seconds=0.35)
    assert (ui.lane_gap, ui.rank_gap) == (240, 140)


def test_ui_reads_iso_durations_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_TOAST", "PT4S")
    monkeypatch.setenv("UI_LANE_GAP", "300")
    ui = UISettings()
    assert ui.toast == timedelta(seconds=4)
    assert ui.lane_gap == 300
