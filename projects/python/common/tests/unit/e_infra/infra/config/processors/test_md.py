"""tests/unit/e_infra/infra/config/processors/md: MDSettings — the input ceiling, the ZIP fan-out and its guard."""

import pytest
from pydantic import ValidationError

from e_infra.infra.config.processors.md import MDSettings


def test_md_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = MDSettings()
    assert (conf.concurrency, conf.zip_max_entries, conf.max_input_bytes) == (8, 1024, 100 * 1024 * 1024)
    monkeypatch.setenv("MD_CONCURRENCY", "2")
    assert MDSettings().concurrency == 2


def test_md_concurrency_is_positive() -> None:
    with pytest.raises(ValidationError):
        MDSettings(concurrency=0)
