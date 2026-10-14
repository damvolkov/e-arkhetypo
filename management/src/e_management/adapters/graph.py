"""adapters.graph: the port that persists a system's dependency lock — reads the sources, calls the ops analysis, writes the YAML.

Paths are project-relative POSIX throughout, so the ``files`` and ``root`` strings the graph carries are the same ones
the exporter prunes on. ``tach`` owns the module-boundary contract in ``tach.toml``; this store owns the file-level
unit graph beside it, and a content hash that turns any drift of the sources into a failing gate.
"""

from typing import TYPE_CHECKING

import eserde

from e_management.models.graph import SCHEMA, Graph
from e_management.ops.deps import digest
from e_management.ops.graph import areas_of, catalog, core_tests, imports_of, resolve

if TYPE_CHECKING:
    from pathlib import Path

    from e_management.models.manifest import Template


##### TYPES #####
class GraphStore:
    """Builds, writes, reads and diffs one system's dependency lock over a repository root."""

    __slots__ = ("root",)

    def __init__(self, root: Path) -> None:
        self.root = root

    ##### PRIVATE #####

    def _build_sources(self, system: Path, files_of: dict[str, tuple[str, ...]], package: str) -> dict[str, bytes]:
        """Every project file the graph reads: the common units' sources and the app root that pins them."""
        app = {path.relative_to(system).as_posix() for path in (system / "src" / package).rglob("*.py")}
        paths = {src for group in files_of.values() for src in group} | app
        return {path: (system / path).read_bytes() for path in sorted(paths)}

    ############################################################

    ##### PUBLIC #####

    def build(self, template: Template, system: str) -> Graph:
        """The resolved dependency graph of one system template, derived only from its committed sources."""
        common = template.common
        if common is None:
            msg = f"{system} declares no common tree to graph"
            raise ValueError(msg)
        system_dir = self.root / template.source
        src = system_dir / "src"
        areas = areas_of(src, template.package)
        skip = frozenset(common.skip)
        detach = frozenset(rule.unit for rule in common.detach)
        files_of, package_of = catalog(src, areas)
        sources = self._build_sources(system_dir, files_of, template.package)
        imports_map = {path: imports_of(content.decode(), frozenset(areas)) for path, content in sources.items()}
        root_files = tuple(path for path in sources if path.startswith(f"src/{template.package}/"))
        units = resolve(
            keys=files_of,
            files_of=files_of,
            tests_of=core_tests(common, self.root / common.root, files_of),
            package_of=package_of,
            imports_map=imports_map,
            root_files=root_files,
            detach=detach,
            skip=skip,
        )
        rules = (
            f"schema={SCHEMA}",
            f"package={template.package}",
            f"areas={','.join(areas)}",
            f"skip={','.join(sorted(skip))}",
            f"detach={','.join(sorted(detach))}",
        )
        return Graph(
            schema=SCHEMA,
            system=system,
            package=template.package,
            source=template.source,
            areas=areas,
            inputs_hash=digest(sources, rules),
            units=units,
        )

    def path(self, template: Template) -> Path:
        """Where a system's lock lives, beside its ``tach.toml``."""
        return self.root / template.source / "graph.lock.yml"

    def dump(self, graph: Graph) -> bytes:
        """The canonical YAML bytes of a graph — the exact body written or diffed."""
        return eserde.dumps(graph, format="yaml")

    def write(self, template: Template, system: str) -> Path:
        """Derive and persist the lock; returns its path."""
        target = self.path(template)
        target.write_bytes(self.dump(self.build(template, system)))
        return target

    def read(self, template: Template) -> Graph:
        """The committed lock, decoded back into the validated DTO."""
        return eserde.load(self.path(template), type=Graph)

    def drift(self, template: Template, system: str) -> list[str]:
        """Why the committed lock no longer matches the sources — empty means in sync."""
        target = self.path(template)
        fresh = self.dump(self.build(template, system))
        match target.is_file():
            case False:
                return ["graph.lock.yml: missing"]
            case True if target.read_bytes() == fresh:
                return []
            case True if _schema(target) != SCHEMA:
                return ["graph.lock.yml: stale schema, run make graph"]
            case True:
                return ["graph.lock.yml: drifted from sources, run make graph"]


def _schema(path: Path) -> int | None:
    try:
        return eserde.load(path, type=Graph).schema
    except eserde.LoaderError:
        return None
