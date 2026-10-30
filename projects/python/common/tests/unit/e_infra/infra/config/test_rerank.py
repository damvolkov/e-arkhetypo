"""tests/unit/e_infra/infra/config/rerank: RerankSettings — the TEI server holding a cross-encoder."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.rerank import RerankSettings

if TYPE_CHECKING:
    import pytest


def test_rerank_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (RerankSettings().batch, RerankSettings().timeout) == (64, timedelta(seconds=30))
    monkeypatch.setenv("RERANK_URL", "http://rerank:80")
    assert RerankSettings().url == "http://rerank:80"
