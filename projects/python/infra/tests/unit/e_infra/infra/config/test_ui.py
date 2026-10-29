"""tests/unit/e_infra/infra/config: UiSettings — the canvas tunables, defaults and env overrides."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.ui import UiSettings

if TYPE_CHECKING:
    import pytest


def test_ui_defaults() -> None:
    ui = UiSettings()
    assert ui.ui_toast == timedelta(seconds=2.5)
    assert ui.ui_pace == timedelta(seconds=0.35)
    assert (ui.ui_lane_gap, ui.ui_rank_gap) == (240, 140)


def test_ui_reads_iso_durations_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_TOAST", "PT4S")
    monkeypatch.setenv("UI_LANE_GAP", "300")
    ui = UiSettings()
    assert ui.ui_toast == timedelta(seconds=4)
    assert ui.ui_lane_gap == 300
