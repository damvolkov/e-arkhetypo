"""tests/unit/e_management/adapters/infra: the real library loads whole — every fragment the map names exists, every system's reference parses."""

import pytest

from e_management.adapters.infra import InfraStore
from e_management.core.errors import InfraError

##### TESTS #####


def test_the_real_library_loads_complete(repo) -> None:
    library = InfraStore(repo).load()
    assert library.map.version == 1
    assert {"ci-basics", "docs", "pypi", "image", "frontend", "rust", "selfmaintain"} <= library.map.features.keys()
    assert library.fragments["workflows/ci.yml"]
    assert library.fragments["jobs/workflow/maintenance.yml"]


def test_load_names_the_fragments_a_map_loses(tmp_path) -> None:
    base = tmp_path / "infra"
    (base / "jobs" / "ci").mkdir(parents=True)
    (base / "features.yml").write_text(
        "version: 1\nfeatures:\n  ci:\n    label: gates\n    jobs:\n      ci: [missing]\n"
    )
    (base / "workflows").mkdir()
    with pytest.raises(InfraError, match=r"jobs/ci/missing\.yml"):
        InfraStore(tmp_path).load()


@pytest.mark.parametrize("system", ["api", "cli", "core", "graph", "mcp", "tui"])
def test_every_system_ships_a_ci_reference(repo, system: str) -> None:
    defaults = InfraStore(repo).defaults(f"systems/{system}")
    assert defaults.tokens, f"{system}: the reference must carry its matrix and markers"
    assert "ci-basics" in defaults.features


def test_a_reference_absent_names_the_system_it_was_asked_for(repo, tmp_path) -> None:
    with pytest.raises(InfraError, match=r"no \.github/ci\.defaults\.yml"):
        InfraStore(tmp_path).defaults("systems/api")
