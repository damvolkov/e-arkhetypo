"""tests/unit/e_cli: the harness — a real `ecli` per test on its own sqlite file, and an in-memory StorePort."""

from typing import TYPE_CHECKING, ClassVar, Self

import pytest

from e_cli.cli import build
from ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path


class MemoryStore:
    """StorePort over a dict: the services and the journal are tested against the port, not against sqlite."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("memory", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.healthy = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def health(self) -> bool:
        return self.healthy

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value: bytes) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def keys(self, prefix: str = "") -> AsyncIterator[str]:
        for key in sorted(self.data):
            if key.startswith(prefix):
                yield key


@pytest.fixture(autouse=True)
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test runs in its own directory: the default relative DB_PATH lands in it, never in the repo."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def ecli(capfd: pytest.CaptureFixture[str]) -> Callable[..., tuple[int, str, str]]:
    """Run the real app on a token list: (exit code, stdout, stderr), exactly what a shell would see."""

    def run(*tokens: str) -> tuple[int, str, str]:
        capfd.readouterr()
        code = build().meta(list(tokens))
        out, err = capfd.readouterr()
        return code or 0, out, err

    return run
