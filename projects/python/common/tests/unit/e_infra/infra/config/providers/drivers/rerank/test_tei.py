"""tests/unit/e_infra/infra/config/providers/drivers/rerank/tei: RerankTEISettings — the TEI server holding a cross-encoder."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.rerank.tei import RerankTEISettings

if TYPE_CHECKING:
    import pytest


def test_rerank_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (RerankTEISettings().batch, RerankTEISettings().timeout) == (64, timedelta(seconds=30))
    monkeypatch.setenv("RERANK_URL", "http://rerank:80")
    assert RerankTEISettings().url == "http://rerank:80"


def test_rerank_url_none_turns_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_URL", "none")
    assert RerankTEISettings().url is None
