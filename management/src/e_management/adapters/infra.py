"""adapters.infra: the port onto the CI library — reads ``infra/`` into memory, reads a system's ``ci.defaults.yml``.

The library is a tree of text fragments: the map, the workflow shells, the triggers, the atomic jobs,
the config files, the setup documents, and the contract-test template. Nothing here interprets them —
that is `core.infra` — the store only guarantees that what it loads parses and that every path the map
names actually exists, so a gap surfaces at load, not mid-assembly."""

from pathlib import Path
from typing import TYPE_CHECKING

import eserde

from e_management.core.errors import InfraError
from e_management.core.infra import Library
from e_management.models.infra import Defaults, FeatureMap

if TYPE_CHECKING:
    from collections.abc import Iterator


##### STORE #####


class InfraStore:
    """Reads the CI library under ``infra/`` once, complete or raising with what it is missing."""

    __slots__ = ("root",)

    def __init__(self, root: Path) -> None:
        self.root = root

    ##### PUBLIC #####

    def load(self) -> Library:
        """The whole library: the map parsed, every fragment keyed by its path under ``infra/``."""
        features_file = self.root / "infra" / "features.yml"
        library = Library(map=self._map(features_file), fragments=self._fragments())
        gaps = [
            f"jobs/{workflow}/{job}.yml"
            for feature in library.map.features.values()
            for workflow, jobs in feature.jobs.items()
            for job in jobs
            if f"jobs/{workflow}/{job}.yml" not in library.fragments
        ] + [
            path
            for feature in library.map.features.values()
            for path in (*feature.files, *(("setup/" + feature.setup,) if feature.setup else ()))
            if _fragment_key(path) not in library.fragments
        ]
        if gaps:
            msg = f"the CI library references fragments it does not hold: {', '.join(sorted(gaps))}"
            raise InfraError(msg)
        return library

    def defaults(self, system: str) -> Defaults:
        """What a project ships by default: the features and name-neutral tokens of its ``.github/ci.defaults.yml``."""
        path = self.root / system / ".github" / "ci.defaults.yml"
        if not path.is_file():
            msg = f"{system}: no .github/ci.defaults.yml — the project declares no CI reference"
            raise InfraError(msg)
        return eserde.load(path, type=Defaults)

    ##### PRIVATE #####

    def _map(self, path: Path) -> FeatureMap:
        try:
            return eserde.load(path, type=FeatureMap)
        except (eserde.LoaderError, OSError) as error:
            msg = f"invalid CI feature map {path}: {error}"
            raise InfraError(msg) from error

    def _fragments(self) -> dict[str, str]:
        """Every text file under ``infra/`` except the map itself, keyed by its infra-relative path."""
        base = self.root / "infra"
        return {str(path.relative_to(base)): path.read_text() for path in _walk(base) if path != base / "features.yml"}


def _fragment_key(path: str) -> str:
    """Where a map reference lives on disk: setup documents under setup/, everything else under files/."""
    return path if path.startswith("setup/") else f"files/{path}"


def _walk(base: Path) -> Iterator[Path]:
    """The library's files in stable order, caches and pyc leftovers out of the tree."""
    return (
        path
        for path in sorted(base.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".yml", ".json", ".md", ".py", ".j2"}
    )
