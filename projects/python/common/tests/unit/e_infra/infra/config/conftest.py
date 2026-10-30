"""tests/unit/e_infra/infra/config: a settings test sees the defaults and the variables it sets — never the host's.

Every variable a scope reads by prefix is removed for the test and no `.env` of the working directory is read: the machine
running the tests, or a CI job pointing the services at an unused port, changes no default asserted here."""

import os
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from pathlib import Path

PREFIXES: Final = (
    "AGENT_", "APP_", "ASYNCPG_", "CACHE_", "CLI_", "DARTS_", "DB_", "DOC_", "DOCLING_", "DOCS_", "EMBED_", "GLINER_",
    "HTTP_", "LLM_", "MD_", "OTEL_", "PING_", "POSTGRES_", "QUEUE_", "REDIS_", "RERANK_", "THEME_", "UI_",
)  # fmt: skip


@pytest.fixture(autouse=True)
def host_env_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _ = [monkeypatch.delenv(name) for name in tuple(os.environ) if name.startswith(PREFIXES)]
    monkeypatch.chdir(tmp_path)
