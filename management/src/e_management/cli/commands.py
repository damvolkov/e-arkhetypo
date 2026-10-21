"""cli.commands: the tool's verbs, free of any console — __main__ registers and renders what these return."""

from typing import TYPE_CHECKING

import eserde

from e_management.adapters.graph import GraphStore
from e_management.adapters.infra import InfraStore
from e_management.adapters.manifest import ManifestReader
from e_management.adapters.scaffold import Scaffold
from e_management.adapters.stack import StackStore
from e_management.core.blueprint import Blueprint
from e_management.core.errors import InfraError
from e_management.core.infra import assemble
from e_management.models.infra import Defaults
from e_management.models.manifest import Choice, Group, Template

if TYPE_CHECKING:
    from pathlib import Path

    from e_management.core.infra import Library
    from e_management.core.plan import Plan
    from e_management.models.graph import Graph
    from e_management.models.manifest import Manifest
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
    ci_on: frozenset[str] = frozenset(),
) -> Plan:
    """The ordered actions for ``template`` under the new ``name``, without touching the filesystem."""
    return blueprint(root, spec, template, name).plan(off, drop, ci_off, ci_on)


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
    ci_on: frozenset[str] = frozenset(),
) -> Path:
    """Materializes and generates the project, returning its path. Raises on any invalid selection."""
    return Scaffold(root).apply(plan(root, spec, template, name, off=off, drop=drop, ci_off=ci_off, ci_on=ci_on), dest)


def notice(
    root: Path,
    spec: Manifest,
    template: str,
    name: str,
    *,
    off: frozenset[str] = frozenset(),
    ci_off: frozenset[str] = frozenset(),
    ci_on: frozenset[str] = frozenset(),
) -> str:
    """What the user must enable by hand once ``template`` is generated under ``name`` — empty when nothing waits."""
    return blueprint(root, spec, template, name).infra_notice(off, ci_off, ci_on)


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


def infra_targets(root: Path, spec: Manifest) -> dict[str, Template]:
    """Every system that declares a CI reference: the registry templates plus sources outside it (core).

    A non-template source gates nothing through the wizard — its reference's own ``group.name``
    requires become the choices it already holds switched on."""
    lib = library(root)
    found = dict(spec.templates)
    for reference in sorted(root.glob("systems/*/.github/ci.defaults.yml")):
        if (name := reference.relative_to(root).parts[1]) in found:
            continue
        declared = eserde.load(reference, type=Defaults)
        requires = {
            req
            for feature in declared.features
            if feature in lib.map.features
            for req in lib.map.features[feature].requires
            if "." in req
        }
        found[name] = Template(
            source=f"systems/{name}",
            package=f"e_{name}",
            brand=f"e-{name}",
            choices=tuple(
                Choice(name=req.partition(".")[2], group=Group(req.partition(".")[0])) for req in sorted(requires)
            ),
        )
    return found


def infra_files(root: Path, name: str, template: Template) -> dict[str, str]:
    """The assembled CI files of one system — its reference plus the library, tokens derived from its name."""
    project_defaults = defaults(root, template)
    if project_defaults is None:
        return {}
    return Blueprint(template, name, None, library(root), project_defaults).infra_files()


def infra_write(root: Path, spec: Manifest) -> list[Path]:
    """Re-assemble every system's CI files onto disk from its reference; returns the paths written."""
    written: list[Path] = []
    for name, template in infra_targets(root, spec).items():
        for key, body in infra_files(root, name, template).items():
            path = root / template.source / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            written.append(path)
    return written


def infra_drift(root: Path, spec: Manifest) -> dict[str, list[str]]:
    """Per system: why its committed .github no longer matches the assembly — missing, edited or hand-written files."""
    report: dict[str, list[str]] = {}
    for name, template in infra_targets(root, spec).items():
        files = infra_files(root, name, template)
        issues = [
            f"{key}: {'missing' if not path.is_file() else 'drifted'}"
            for key, body in files.items()
            if (path := root / template.source / key) and not (path.is_file() and path.read_text() == body)
        ]
        expected = {key for key in files if key.startswith(".github/workflows/")}
        workflows = root / template.source / ".github" / "workflows"
        issues += [
            f".github/workflows/{path.name}: not in the assembly — hand-written"
            for path in sorted(workflows.glob("*.yml"))
            if f".github/workflows/{path.name}" not in expected
        ]
        report[name] = issues
    return report


def infra_check(root: Path, spec: Manifest) -> dict[str, list[str]]:
    """Per system: why its CI reference cannot assemble or no longer matches its committed output.

    The library itself is checked once (it is shared): every fragment the map names must exist."""
    store = InfraStore(root)
    lib = store.load()
    drift = infra_drift(root, spec)
    report: dict[str, list[str]] = {}
    for name, template in infra_targets(root, spec).items():
        project_defaults = defaults(root, template)
        if project_defaults is None:
            report[name] = []
            continue
        try:
            Blueprint(template, "check", None, lib, project_defaults).plan()
        except (InfraError, ValueError) as error:
            report[name] = [str(error)]
        else:
            report[name] = drift.get(name, [])
    return report


def repo_defaults(root: Path) -> Defaults:
    """The repository's own CI reference: the root ``.github/ci.defaults.yml`` of a wide repo."""
    return InfraStore(root).defaults(".")


def repo_files(root: Path) -> dict[str, str]:
    """What the repo assembles for itself — the contract test excluded: the root tree holds no test project."""
    spec = repo_defaults(root)
    return {
        key: body
        for key, body in assemble(library(root), spec.tokens, frozenset(spec.features)).items()
        if not key.startswith("tests/")
    }


def repo_write(root: Path) -> list[Path]:
    """Assemble the repo's own CI files onto disk; returns the paths written."""
    written: list[Path] = []
    for key, body in repo_files(root).items():
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        written.append(path)
    return written


def repo_drift(root: Path) -> list[str]:
    """Why the repo's committed .github no longer matches the assembly of its own reference."""
    files = repo_files(root)
    issues = [
        f"{key}: {'missing' if not path.is_file() else 'drifted'}"
        for key, body in files.items()
        if (path := root / key) and not (path.is_file() and path.read_text() == body)
    ]
    expected = {key for key in files if key.startswith(".github/workflows/")}
    issues += [
        f".github/workflows/{path.name}: not in the assembly — hand-written"
        for path in sorted((root / ".github" / "workflows").glob("*.yml"))
        if f".github/workflows/{path.name}" not in expected
    ]
    return issues
