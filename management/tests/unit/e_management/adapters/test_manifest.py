"""tests/unit/e_management/adapters/manifest: the registry loads validated, and refuses to load otherwise."""

from typing import TYPE_CHECKING

import pytest

from e_management.adapters.manifest import ManifestReader

if TYPE_CHECKING:
    from pathlib import Path

    from e_management.models.manifest import Manifest


def test_manifest_reader_loads_the_live_registry(spec: Manifest) -> None:
    assert list(spec.templates) == ["api", "cli", "graph", "mcp", "tui"]
    api = spec.templates["api"]
    assert api.package == "e_api"
    assert len(api.materials) == 5
    assert api.common is not None
    assert api.common.skip == ("ops/tui",)
    assert api.choices[0].name == "websockets"
    assert {c.group.value for c in api.choices} == {"modules", "stack", "cicd"}
    assert "redis" not in {c.name for c in api.choices}
    assert api.mandatory
    assert any(v.tests for v in api.verify)


def test_manifest_reader_rejects_a_broken_registry(tmp_path: Path) -> None:
    broken = tmp_path / "templates.yml"
    broken.write_text("templates:\n  api:\n    package: e_api\n")
    with pytest.raises(ValueError, match="invalid template registry"):
        ManifestReader(broken).load()
