"""tests/unit/e_infra/infra/config/providers/drivers/embed/tei: TeiEmbedSettings — the TEI server, its model and its batches."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.embed.tei import TeiEmbedSettings


def test_embed_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (TeiEmbedSettings().dimensions, TeiEmbedSettings().timeout) == (1024, timedelta(seconds=60))
    monkeypatch.setenv("EMBED_URL", "http://tei:80")
    monkeypatch.setenv("EMBED_BATCH", "8")
    assert (TeiEmbedSettings().url, TeiEmbedSettings().batch) == ("http://tei:80", 8)


def test_embed_batch_is_positive() -> None:
    with pytest.raises(ValidationError):
        TeiEmbedSettings(batch=0)
