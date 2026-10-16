"""cli.commands: the tool's verbs, free of any console — __main__ registers and renders what these return."""

from typing import TYPE_CHECKING

from e_management.adapters.graph import GraphStore
from e_management.adapters.infra import InfraStore
from e_management.adapters.manifest import ManifestReader
from e_management.adapters.scaffold import Scaffold
from e_management.adapters.stack import StackStore
from e_management.core.blueprint import Blueprint
from e_management.core.errors import InfraError

if TYPE_CHECKING:
    from pathlib import Path

    from e_management.core.infra import Library
    from e_management.core.plan import Plan
    from e_management.models.graph import Graph
    from e_management.models.infra import Defaults
    from e_management.models.manifest import Manifest, Template
    from e_management.models.stack import Stack


def registry(file: Path) -> Manifest:
    """The validated template registry."""
    return ManifestReader(file).load()


def library(root: Path) -> Library:
    """The CI library as one loaded object — the fragments behind every assembly."""
    return InfraStore(root).load()


def defaults(root: Path, template: Template) -> Defaults | None:
    """The system's CI reference when it holds one; None keeps a template outside the CI assembly."""
    try:
        return InfraStore(root).defaults(template.source)
    except InfraError:
        return None


def dependency_map(root: Path, spec: Manifest, template: str) -> Graph | None:
    """The live dependency graph of one system — derived fresh from its sources; None when it declares no common tree."""
    spec_t = spec.templates[template]
    return None if spec_t.common is None else GraphStore(root).build(spec_t, template)


def blueprint(root: Path, spec: Manifest, template: str, name: str) -> Blueprint:
    """The domain view of a template for a concrete name, wired with its dynamic dependency graph and CI library."""
    template_spec = spec.templates[template]
    return Blueprint(
        template_spec,
        name,
        dependency_map(root, spec, template),
        library(root) if defaults(root, template_spec) else None,
        defaults(root, template_spec),
    )


def plan(
    root: Path,
    spec: Manifest,
    template: str,
    name: str,
    *,
    off: frozenset[str] = frozenset(),
    drop: frozenset[str] = frozenset(),
    ci_off: frozenset[str] = frozenset(),
) -> Plan:
    """The ordered actions for ``template`` under the new ``name``, without touching the filesystem."""
    return blueprint(root, spec, template, name).plan(off, drop, ci_off)


def gen(
    root: Path,
    spec: Manifest,
    template: str,
    name: str,
    dest: Path,
    *,
    off: frozenset[str] = frozenset(),
    drop: frozenset[str] = frozenset(),
    ci_off: frozenset[str] = frozenset(),
) -> Path:
    """Materializes and generates the project, returning its path. Raises on any invalid selection."""
    return Scaffold(root).apply(plan(root, spec, template, name, off=off, drop=drop, ci_off=ci_off), dest)


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


def infra_check(root: Path, spec: Manifest) -> dict[str, list[str]]:
    """Per template: why its CI reference cannot assemble — unknown feature, unmet requires, missing token.

    The library itself is checked once (it is shared): every fragment the map names must exist."""
    store = InfraStore(root)
    lib = store.load()
    report: dict[str, list[str]] = {}
    for name, template in spec.templates.items():
        project_defaults = defaults(root, template)
        if project_defaults is None:
            report[name] = []
            continue
        try:
            Blueprint(template, "check", None, lib, project_defaults).plan()
        except (InfraError, ValueError) as error:
            report[name] = [str(error)]
        else:
            report[name] = []
    return report
