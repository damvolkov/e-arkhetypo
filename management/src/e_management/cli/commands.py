"""cli.commands: the tool's verbs, free of any console — __main__ registers and renders what these return."""

from typing import TYPE_CHECKING

from e_management.adapters.graph import GraphStore
from e_management.adapters.manifest import ManifestReader
from e_management.adapters.scaffold import Scaffold
from e_management.adapters.stack import StackStore
from e_management.core.blueprint import Blueprint

if TYPE_CHECKING:
    from pathlib import Path

    from e_management.core.plan import Plan
    from e_management.models.graph import Graph
    from e_management.models.manifest import Manifest
    from e_management.models.stack import Stack


def registry(file: Path) -> Manifest:
    """The validated template registry."""
    return ManifestReader(file).load()


def dependency_map(root: Path, spec: Manifest, template: str) -> Graph | None:
    """The live dependency graph of one system — derived fresh from its sources; None when it declares no common tree."""
    spec_t = spec.templates[template]
    return None if spec_t.common is None else GraphStore(root).build(spec_t, template)


def blueprint(root: Path, spec: Manifest, template: str, name: str) -> Blueprint:
    """The domain view of a template for a concrete name, wired with its dynamic dependency graph."""
    return Blueprint(spec.templates[template], name, dependency_map(root, spec, template))


def plan(
    root: Path,
    spec: Manifest,
    template: str,
    name: str,
    *,
    off: frozenset[str] = frozenset(),
    drop: frozenset[str] = frozenset(),
) -> Plan:
    """The ordered actions for ``template`` under the new ``name``, without touching the filesystem."""
    return blueprint(root, spec, template, name).plan(off, drop)


def gen(
    root: Path,
    spec: Manifest,
    template: str,
    name: str,
    dest: Path,
    *,
    off: frozenset[str] = frozenset(),
    drop: frozenset[str] = frozenset(),
) -> Path:
    """Materializes and generates the project, returning its path. Raises on any invalid selection."""
    return Scaffold(root).apply(plan(root, spec, template, name, off=off, drop=drop), dest)


def drift(root: Path, spec: Manifest) -> dict[str, list[str]]:
    """Per template: the material files its system holds that no longer match the sources."""
    return {name: Scaffold(root).drift(template) for name, template in spec.templates.items()}


def graph(root: Path, spec: Manifest) -> dict[str, Path]:
    """Regenerate every system's dependency lock from its sources; returns the paths written."""
    store = GraphStore(root)
    return {name: store.write(template, name) for name, template in spec.templates.items()}


def graph_drift(root: Path, spec: Manifest) -> dict[str, list[str]]:
    """Per template: why its committed dependency lock no longer matches its sources. Empty means in sync."""
    store = GraphStore(root)
    return {name: store.drift(template, name) for name, template in spec.templates.items()}


def stack_map(root: Path) -> Stack:
    """The live dependency map of the stack services — derived fresh from stack/, never from the lock."""
    return StackStore(root).build()


def stack_write(root: Path) -> Path:
    """Regenerate the stack dependency lock from the services on disk."""
    return StackStore(root).write()


def stack_drift(root: Path) -> list[str]:
    """Why the committed stack lock no longer matches stack/ — empty means in sync."""
    return StackStore(root).drift()
