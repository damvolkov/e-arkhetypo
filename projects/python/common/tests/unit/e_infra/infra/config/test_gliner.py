"""tests/unit/e_infra/infra/config/gliner: GlinerSettings — the NER service, its wait and its batches."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.gliner import GlinerSettings

if TYPE_CHECKING:
    import pytest


def test_gliner_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (GlinerSettings().batch, GlinerSettings().timeout) == (16, timedelta(seconds=60))
    monkeypatch.setenv("GLINER_BATCH", "4")
    assert GlinerSettings().batch == 4
