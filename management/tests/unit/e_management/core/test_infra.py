"""tests/unit/e_management/core/infra: the assembler is pure — a hand-built library answers the whole contract, no filesystem.

The fixtures write exactly the shapes the library holds: workflow shells with their slot tokens,
job fragments with feature tags, triggers, a setup body and a contract seam. Every test states the
selection and reads back the emitted files: order, requires, replacement, gates, tokens."""

import re

import pytest

from e_management.core.errors import InfraError
from e_management.core.infra import Library, assemble, derive, resolve
from e_management.models.infra import Feature, FeatureMap

##### FRAGMENTS #####
FRAGMENTS = {
    "workflows/ci.yml": "name: CI\njobs:\n{{ci_jobs}}\n",
    "workflows/release.yml": "name: Release\non:\n{{release_trigger}}\njobs:\n{{release_jobs}}\n",
    "triggers/dispatch.yml": "  workflow_dispatch:\n",
    "triggers/tag.yml": "  push:\n    tags: [v*]\n",
    "jobs/ci/quality.yml": "  quality:\n    name: static gates\n",
    "jobs/ci/docs.yml": "  docs:\n    name: docs build\n    if: vars.DOCS_DEPLOY == 'true'\n",
    "jobs/ci/extra.yml": "  extra:\n    name: the gateless job\n",
    "jobs/release/bump.yml": "  bump:\n    name: tag {{brand}}\n",
    "jobs/release/build.yml": "  build:\n    name: wheel\n",
    "jobs/release/push.yml": "  push:\n    name: upload\n    if: vars.PUSH == 'true'\n",
    "jobs/workflow/sync.yml": "name: sync\n",
    "files/renovate.json": "{}\n",
    "files/qwen.md": "# agent\n",
    "files/renovate.repo.json": '{"repo": true}\n',
    "files/qwen.repo.md": "# wide agent\n",
    "contract.py.j2": "def test_contract():\n    assert True\n",
    "setup/docs.md": "# docs\n\nset DOCS_DEPLOY true once.\n",
    "setup/none.md": "",
}

MAP = FeatureMap(
    version=1,
    features={
        "ci": Feature(label="static gates", jobs={"ci": ("quality",)}),
        "docs": Feature(
            label="pages",
            jobs={"ci": ("docs",)},
            gate="DOCS_DEPLOY",
            vars=("DOCS_DEPLOY",),
            setup="docs.md",
            tokens=("brand",),
        ),
        "extra": Feature(label="gateless", jobs={"ci": ("extra",)}, requires=("docs",)),
        "ship": Feature(
            label="release", jobs={"release": ("bump", "build")}, gate="PUSH", vars=("PUSH",), tokens=("brand",)
        ),
        "rust": Feature(
            label="binding", jobs={"release": ("push",)}, requires=("ship",), replaces=("ship",), tag_trigger=True
        ),
        "loop": Feature(
            label="bots",
            jobs={"workflow": ("sync",)},
            files=("renovate.json", "qwen.md"),
            requires=("ci",),
            vars=("APP_CLIENT_ID",),
        ),
        "wide": Feature(label="areas", jobs={}, files=("renovate.repo.json", "qwen.repo.md"), requires=("ci",)),
    },
)

TOKENS = {**derive("e_myapp", "e-myapp"), "site": "site", "os": "[ubuntu-latest]"}


##### RESOLVE #####


def test_resolve_keeps_library_order_and_requires() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    assert resolve(library, frozenset({"extra", "docs", "ci"})) == ["ci", "docs", "extra"]


def test_resolve_refuses_unknown_features() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    with pytest.raises(InfraError, match="unknown CI feature"):
        resolve(library, frozenset({"nope", "ci"}))


def test_resolve_refuses_unmet_requires() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    with pytest.raises(InfraError, match=r"'extra' requires docs, which is not selected"):
        resolve(library, frozenset({"ci", "extra"}))


def test_resolve_folds_replaced_features_and_counts_choices() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    assert resolve(library, frozenset({"ci", "ship", "rust"})) == ["ci", "rust"]


def test_choice_requires_satisfied_by_on_choices() -> None:
    library = Library(
        map=FeatureMap(
            version=1, features={"x": Feature(label="l", jobs={"ci": ("extra",)}, requires=("stack.docker",))}
        ),
        fragments=FRAGMENTS,
    )
    assert resolve(library, frozenset({"x"}), frozenset({"stack.docker"})) == ["x"]


##### ASSEMBLE #####


def test_assemble_emits_shells_with_feature_tagged_jobs() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "docs"}))
    ci = files[".github/workflows/ci.yml"]
    assert ci.index("# feature: ci") < ci.index("# feature: docs")
    assert "if: vars.DOCS_DEPLOY == 'true'" in ci
    assert files[".github/ci.map.yml"] == "features:\n  - ci\n  - docs\n"


def test_assemble_builds_release_only_when_a_release_feature_ships() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    assert ".github/workflows/release.yml" not in assemble(library, TOKENS, frozenset({"ci"}))
    files = assemble(library, TOKENS, frozenset({"ci", "ship"}))
    assert "name: tag e-myapp" in files[".github/workflows/release.yml"]  # the token substituted from identity
    assert "workflow_dispatch" in files[".github/workflows/release.yml"]


def test_assemble_tag_trigger_and_replacement_survive_to_the_shell() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "ship", "rust"}))
    release = files[".github/workflows/release.yml"]
    assert "tags: [v*]" in release
    assert "name: tag e-myapp" not in release  # ship replaced by rust: only push remains
    assert "upload" in release


def test_assemble_stands_up_standalone_workflows_and_files() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "loop"}))
    assert files[".github/workflows/sync.yml"] == "name: sync\n"
    assert files[".github/renovate.json"] == "{}\n"
    assert files["QWEN.md"] == "# agent\n"


def test_assemble_manifests_gates_inert_and_documents_install_once() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "docs", "ship"}))
    manifest = files[".github/ci.vars.example"]
    assert "DOCS_DEPLOY=false" in manifest
    assert "PUSH=false" in manifest
    install = files[".github/INSTALL.md"]
    assert install.count("set DOCS_DEPLOY true once") == 1
    assert "docs → " not in install


def test_assemble_carries_the_contract_test_verbatim() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    assert "def test_contract" in assemble(library, TOKENS, frozenset({"ci"}))["tests/unit/test_ci_contract.py"]


def test_assemble_refuses_selection_tokens_nothing_provides() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    with pytest.raises(InfraError, match="demands tokens"):
        assemble(library, {"site": "site"}, frozenset({"ci", "docs"}))


def test_unknown_tokens_stay_literal_for_the_contract_test_to_catch() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, {}, frozenset({"ci"}))
    assert "{{" not in files[".github/workflows/ci.yml"]  # ci needs no tokens at all


def test_derive_carries_the_verify_command() -> None:
    assert "prek" in derive("e_myapp", "e-myapp")["verify"]


def test_assemble_lands_the_wide_repo_files_on_the_same_targets() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "wide"}))
    assert files[".github/renovate.json"] == '{"repo": true}\n'
    assert files["QWEN.md"] == "# wide agent\n"


def test_assemble_replaced_features_leave_their_files_out() -> None:
    map_with_replacement = FeatureMap(
        version=1,
        features={
            **MAP.features,
            "wide": Feature(label="areas", jobs={}, files=("renovate.repo.json", "qwen.repo.md"), replaces=("loop",)),
        },
    )
    library = Library(map=map_with_replacement, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "loop", "wide"}))
    assert ".github/workflows/sync.yml" not in files  # loop is folded away, its workflow never lands
    assert files["QWEN.md"] == "# wide agent\n"


def test_assemble_maps_config_vars_apart_from_gates() -> None:
    library = Library(map=MAP, fragments=FRAGMENTS)
    files = assemble(library, TOKENS, frozenset({"ci", "docs", "loop"}))
    assert files[".github/ci.map.yml"] == "features:\n  - ci\n  - docs\n  - loop\nvars:\n  - APP_CLIENT_ID\n"
    assert "APP_CLIENT_ID" not in files[".github/ci.vars.example"]


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("src/e_myapp/core/state.py", True),
        ("tests/unit/test_x.py", True),
        ("docs/index.md", True),
        ("CHANGELOG.md", True),
        ("README.md", True),
        (".github/workflows/ci.yml", False),
        ("pyproject.toml", False),
        ("src/e_other/x.py", False),
    ],
)
def test_derive_allowlist_admits_code_paths_and_nothing_else(path: str, allowed: bool) -> None:
    assert bool(re.fullmatch(f"^({derive('e_myapp', 'e-myapp')['allowlist']})$", path)) is allowed
