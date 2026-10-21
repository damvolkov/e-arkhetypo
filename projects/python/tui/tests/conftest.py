"""tests/conftest: system-wide fixtures for the layout language tests.

`template_resources` exposes the raw `tests/resources/` path for `Box.load`; `make_leaf` builds a legal
dynamic box bent by keyword overrides; `write_spec` serializes a spec to the format an extension names,
so the file-load tests exercise the same codec the app uses in production."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import eserde
import pytest

from e_tui.layout.spec import Box, Kind

if TYPE_CHECKING:
    from collections.abc import Callable

##### RESOURCES #####
RESOURCES: Path = Path(__file__).parent / "resources"


@pytest.fixture
def template_resources() -> Path:
    """The physical resource tree, for `Box.load`."""
    return RESOURCES


@pytest.fixture
def make_leaf() -> Callable[..., Box]:
    """A factory for one valid dynamic box, overridable by keyword."""

    def _make(**overrides: Any) -> Box:
        fields: dict[str, Any] = {"id": "slot", "kind": Kind.DYNAMIC}
        return Box(**{**fields, **overrides})

    return _make


@pytest.fixture
def write_spec() -> Callable[[Path, str, Box], None]:
    """Serialize a spec to the format its extension names (e-serde), for round-trip load tests."""

    def _write(path: Path, suffix: str, box: Box) -> None:
        eserde.dump(box, path, format=suffix)

    return _write
