"""tests/unit/e_infra/infra/config: DocsSettings — canonical root, its aliases, its renderers, validated on load."""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from e_infra.infra.config.docs import DocsRenderer, DocsSettings

if TYPE_CHECKING:
    from typing import Any


def test_docs_defaults_swagger_at_docs_aliased_by_schema() -> None:
    docs = DocsSettings()
    assert (docs.docs_path, docs.docs_aliases) == ("/docs", ["/schema"])
    assert docs.docs_renderers[0] is DocsRenderer.SWAGGER


def test_docs_reads_env_and_normalizes_trailing_slashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_PATH", "/api/docs/")
    monkeypatch.setenv("DOCS_ALIASES", '["/schema/", "/swagger"]')
    monkeypatch.setenv("DOCS_RENDERERS", '["redoc"]')
    docs = DocsSettings()
    assert (docs.docs_path, docs.docs_aliases, docs.docs_renderers) == (
        "/api/docs",
        ["/schema", "/swagger"],
        [DocsRenderer.REDOC],
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"docs_path": "docs"},
        {"docs_aliases": ["schema"]},
        {"docs_aliases": ["/docs"]},
        {"docs_renderers": []},
        {"docs_renderers": ["openapi-ui"]},
    ],
    ids=["relative-root", "relative-alias", "alias-is-root", "no-renderer", "unknown-renderer"],
)
def test_docs_rejects_at_load(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DocsSettings(**fields)
