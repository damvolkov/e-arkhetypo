"""tests/unit/e_infra/infra/config/providers/drivers/rerank/tei: TeiRerankSettings — the TEI server holding a cross-encoder."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.rerank.tei import TeiRerankSettings

if TYPE_CHECKING:
    import pytest


def test_rerank_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (TeiRerankSettings().batch, TeiRerankSettings().timeout) == (64, timedelta(seconds=30))
    monkeypatch.setenv("RERANK_URL", "http://rerank:80")
    assert TeiRerankSettings().url == "http://rerank:80"
