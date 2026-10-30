"""tests/unit/e_infra/ops: the textual harness and the compose fixtures — resources behind fixtures, output models pinned as goldens."""

import os
from pathlib import Path
from typing import TYPE_CHECKING

import eserde
import pytest
from textual.app import App, ComposeResult

from e_infra.ops.compose import StackCompose

if TYPE_CHECKING:
    from collections.abc import Callable

    from e_infra.ops.tui import HeaderTui

_RES = Path(__file__).resolve().parents[3] / "resources" / "compose"
_GOLDENS = Path(__file__).resolve().parent / "__snapshots__"


class HostApp(App[None]):
    """The minimum app that composes the header under test."""

    def __init__(self, masthead: HeaderTui) -> None:
        super().__init__()
        self.masthead = masthead

    def compose(self) -> ComposeResult:
        yield self.masthead


@pytest.fixture
def host_app() -> Callable[[HeaderTui], App[None]]:
    """The app class: tests mount their own HeaderTui through it."""
    return HostApp


@pytest.fixture(scope="session")
def tool() -> StackCompose:
    """The tool over the resource stack tree (``<category>/<service>/compose.yml``)."""
    return StackCompose(_RES / "stack")


@pytest.fixture(scope="session")
def fragments() -> dict[str, dict]:
    """Every top-level resource fragment loaded as a raw mapping, for ``documents`` mode."""
    return {path.stem: eserde.loads(path.read_bytes(), format="yaml") for path in sorted(_RES.glob("*.yml"))}


@pytest.fixture(scope="session")
def repo() -> Path:
    return next(p for p in Path(__file__).resolve().parents if (p / "stack" / "_template").is_dir())


@pytest.fixture(scope="session")
def snap() -> Callable[[str, bytes], None]:
    """Compare snapshot bytes against the golden file; ``SNAPSHOT_UPDATE=1`` rewrites the goldens."""

    def _snap(name: str, payload: bytes) -> None:
        golden = _GOLDENS / f"{name}.json"
        match (os.environ.get("SNAPSHOT_UPDATE") == "1", golden.exists()):
            case True, _:
                _GOLDENS.mkdir(parents=True, exist_ok=True)
                golden.write_bytes(payload)
            case False, True:
                assert payload == golden.read_bytes(), f"snapshot drift: {name}"
            case False, False:
                msg = f"missing snapshot '{name}': run once with SNAPSHOT_UPDATE=1 and review the diff"
                raise AssertionError(msg)

    return _snap
