"""logic.rules: the laws a pipeline's specs and runners keep — the discovery's tools, one function per law.

Each rule reads what was found and yields a `RuleError` per breach, never raises: the discovery runs
them all and reports every breach at once. Three scopes, in the order the discovery meets them:

- TREE — the pipeline's folders: one per `Section` (plus `wiki`), spec files `.yaml`, runner files `.py`.
- SOURCE — one spec file's text, before decoding: no YAML merge keys (`<<`), which the parser leaves
  unresolved. Anchors and aliases resolve, and stay allowed.
- SECTION — a decoded `Draft`, as a whole (a spec file that failed to decode counts as present, never
  as missing — its own breach is enough): file named as its spec, dependencies and fallbacks that exist
  and keep their shape, an acyclic dependency graph, runner modules that pair one-to-one with specs and
  define only their spec kind's hooks, each with the exact signature and a docstring, wiki terms that exist.

What one spec can say about itself (its name's regex, its schema, its examples) is msgspec's job while
decoding, never repeated here."""

import re
from collections.abc import Callable, Iterator
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import rustworkx as rx

from e_graph.logic.errors import Rule, RuleError
from e_graph.logic.models import SIGNATURES, Draft, Hook
from e_graph.models.section import Section

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

type Violations = Iterator[RuleError]

WIKI: Final[str] = "wiki"
SPEC_SUFFIX: Final[str] = ".yaml"
RUNNER_SUFFIX: Final[str] = ".py"
SECTIONS: Final[frozenset[str]] = frozenset(Section)
HOOKS: Final[frozenset[str]] = frozenset(Hook)
MERGE_KEY: Final[re.Pattern[str]] = re.compile(r"^\s*-?\s*<<\s*:", re.MULTILINE)


##### TREE #####
def rule_tree(root: Path, suffix: str) -> Violations:
    """A pipeline folder holds section folders (and `wiki`), each holding only files of its tree's suffix."""
    entries = sorted(root.iterdir()) if root.is_dir() else []
    yield from (
        RuleError(Rule.TREE, str(entry), "neither a section folder nor wiki")
        for entry in entries
        if not entry.is_dir() or (entry.name not in SECTIONS and entry.name != WIKI)
    )
    yield from (
        RuleError(Rule.TREE, str(file), f"a {root.parent.name} folder holds only {suffix} files")
        for entry in entries
        if entry.is_dir() and entry.name in SECTIONS
        for file in sorted(entry.iterdir())
        if not file.name.startswith((".", "__")) and (file.is_dir() or file.suffix != suffix)
    )


##### SOURCE #####
def rule_merge(file: Path, text: str) -> Violations:
    """YAML merge keys are refused: the parser would keep `<<` as a plain key, silently."""
    yield from (
        RuleError(
            Rule.MERGE, str(file), f"line {text.count(chr(10), 0, match.start()) + 1}: merge keys (<<) are banned"
        )
        for match in MERGE_KEY.finditer(text)
    )


##### SECTION · SPECS #####
def rule_filename(draft: Draft) -> Violations:
    """The file is named as the spec it holds: the path is the name."""
    yield from (
        RuleError(Rule.FILENAME, stem, f"the file holds spec {spec.name!r}")
        for stem, spec in draft.specs.items()
        if spec.name != stem
    )


def rule_depends(draft: Draft) -> Violations:
    """Every dependency is a spec of the same section."""
    yield from (
        RuleError(Rule.DEPENDS, spec.name, f"depends on {dependency!r}, no such spec in {draft.section}")
        for spec in draft.specs.values()
        for dependency in spec.depends
        if dependency not in draft.known
    )


def rule_fallback(draft: Draft) -> Violations:
    """A fallback exists, takes no fallback of its own, depends on nothing, and nothing depends on it.

    It runs only in its parent's place, in its parent's slot: a chain, a dependency of its own, or a
    spec waiting on it would give it a schedule it never has."""
    yield from (
        RuleError(Rule.FALLBACK, spec.name, f"falls back to {spec.fallback!r}, no such spec in {draft.section}")
        for spec in draft.specs.values()
        if spec.fallback is not None and spec.fallback not in draft.known
    )
    found = {
        spec.fallback: draft.specs[spec.fallback]
        for spec in draft.specs.values()
        if spec.fallback is not None and spec.fallback in draft.specs
    }
    yield from (
        RuleError(Rule.FALLBACK, name, f"a fallback cannot fall back again (to {spec.fallback!r})")
        for name, spec in found.items()
        if spec.fallback is not None
    )
    yield from (
        RuleError(Rule.FALLBACK, name, f"a fallback cannot depend on anything: {list(spec.depends)}")
        for name, spec in found.items()
        if spec.depends
    )
    yield from (
        RuleError(Rule.FALLBACK, spec.name, f"depends on {dependency!r}, which only runs as a fallback")
        for spec in draft.specs.values()
        for dependency in spec.depends
        if dependency in found
    )


def rule_cycle(draft: Draft) -> Violations:
    """The section's dependency graph is acyclic: one cycle found is one breach, named edge by edge."""
    graph: rx.PyDiGraph[str, None] = rx.PyDiGraph()
    index = {name: graph.add_node(name) for name in draft.specs}
    graph.add_edges_from_no_data(
        [
            (index[dependency], index[spec.name])
            for spec in draft.specs.values()
            for dependency in spec.depends
            if dependency in index
        ]
    )
    match rx.is_directed_acyclic_graph(graph):
        case True:
            pass
        case _:
            cycle = [graph[node] for node in next(iter(rx.simple_cycles(graph)))]
            path = " → ".join([*cycle, cycle[0]])
            yield RuleError(Rule.CYCLE, draft.section, f"dependency cycle {path}")


##### SECTION · RUNNERS #####
def rule_runner(draft: Draft) -> Violations:
    """Every hook a spec kind requires is defined in the runner module named as the spec's file."""
    yield from (
        RuleError(Rule.RUNNER, stem, f"a {spec.__struct_config__.tag} spec needs `{hook}` in {stem}.py")
        for stem, spec in draft.specs.items()
        for hook in sorted(type(spec).REQUIRED - {function.name for function in draft.functions.get(stem, ())})
    )


def rule_orphan(draft: Draft) -> Violations:
    """Every runner module serves a spec of its name; one serving none is deprecated, and refused."""
    yield from (
        RuleError(Rule.ORPHAN, stem, f"no spec {stem!r} in {draft.section}: deprecated runner")
        for stem in draft.functions
        if stem not in draft.known
    )


def rule_hook(draft: Draft) -> Violations:
    """A runner module defines only the hooks its spec's kind admits — no other function, no other name."""
    yield from (
        RuleError(Rule.HOOK, f"{stem}.{function.name}", f"not a hook of a {spec.__struct_config__.tag} spec: {allowed}")
        for stem, functions in draft.functions.items()
        if (spec := draft.specs.get(stem)) is not None
        for allowed in (", ".join(sorted(type(spec).HOOKS)),)
        for function in functions
        if function.name not in type(spec).HOOKS
    )


def rule_signature(draft: Draft) -> Violations:
    """Each hook reads exactly as its contract: async, the RunState in, the hook's own type out."""
    yield from (
        RuleError(Rule.SIGNATURE, f"{stem}.{function.name}", f"must read `{expected}`, reads `{function.signature}`")
        for stem, functions in draft.functions.items()
        for function in functions
        if function.name in HOOKS
        if (expected := SIGNATURES[Hook(function.name)]) != function.signature
    )


def rule_doc(draft: Draft) -> Violations:
    """Each hook says what it does: its docstring becomes the runner's description."""
    yield from (
        RuleError(Rule.DOC, f"{stem}.{function.name}", "a runner needs a docstring")
        for stem, functions in draft.functions.items()
        for function in functions
        if function.name in HOOKS and not function.doc.strip()
    )


##### SECTION · WIKI #####
def rule_wiki(draft: Draft) -> Violations:
    """Every wiki term a spec names is explained in the pipeline's wiki or the shared one."""
    yield from (
        RuleError(Rule.WIKI, spec.name, f"wiki term {term!r} has no {term}.md")
        for spec in draft.specs.values()
        for term in spec.wiki
        if term not in draft.wiki
    )


##### TABLE #####
SECTION_RULES: Final[Mapping[Rule, Callable[[Draft], Violations]]] = MappingProxyType(
    {
        Rule.FILENAME: rule_filename,
        Rule.DEPENDS: rule_depends,
        Rule.FALLBACK: rule_fallback,
        Rule.CYCLE: rule_cycle,
        Rule.RUNNER: rule_runner,
        Rule.ORPHAN: rule_orphan,
        Rule.HOOK: rule_hook,
        Rule.SIGNATURE: rule_signature,
        Rule.DOC: rule_doc,
        Rule.WIKI: rule_wiki,
    }
)


def judge_section(draft: Draft) -> list[RuleError]:
    """Every section law over one draft, every breach collected."""
    return [error for rule in SECTION_RULES.values() for error in rule(draft)]
