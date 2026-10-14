"""logic.rules: the laws a pipeline's specs and runners keep — the discovery's tools, one function per law.

Each rule reads what was found and yields a `RuleError` per breach, never raises: the discovery runs
them all and reports every breach at once. Three scopes, in the order the discovery meets them:

- TREE — the folders: `specs/<pipeline>/<section>` of `.yaml`, `runners/owned/<pipeline>/<section>` and
  `runners/agnostic/<capability>` of one-word `.py` modules.
- SOURCE — one spec file's text, before decoding: no YAML merge keys (`<<`), which the parser leaves
  unresolved. Anchors and aliases resolve, and stay allowed.
- SECTION — a decoded `Draft`, as a whole (a spec file that failed to decode counts as present, never
  as missing — its own breach is enough): file named as its spec, dependencies and fallbacks that exist
  and keep their shape, an acyclic dependency graph; every runner a spec plugs exists, defines exactly one
  function whose role fits the slot, with its role's exact signature and a docstring; every owned runner of
  the section is plugged by some spec (else it is deprecated); wiki terms that exist.

What one spec can say about itself (its name's regex, its schema, its examples) is msgspec's job while
decoding, never repeated here."""

import re
from collections.abc import Callable, Iterator
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import rustworkx as rx

from e_graph.logic.errors import Rule, RuleError
from e_graph.logic.models import ROLES, SIGNATURES, Draft, Role
from e_graph.models.section import Section

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

type Violations = Iterator[RuleError]

WIKI: Final[str] = "wiki"
SPEC_SUFFIX: Final[str] = ".yaml"
RUNNER_SUFFIX: Final[str] = ".py"
SECTIONS: Final[frozenset[str]] = frozenset(Section)
ROLE_NAMES: Final[frozenset[str]] = frozenset(Role)
### a runner module, a capability, a pipeline: one lowercase word.
WORD: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9]*")
MERGE_KEY: Final[re.Pattern[str]] = re.compile(r"^\s*-?\s*<<\s*:", re.MULTILINE)


##### TREE #####
def rule_tree(
    root: Path, suffix: str, folders: Callable[[str], object], *, skip: frozenset[str] = frozenset()
) -> Violations:
    """A root holds only folders `folders` admits; each (but `skip`) only files of `suffix`, named as a module is."""
    entries = sorted(root.iterdir()) if root.is_dir() else []
    yield from (
        RuleError(Rule.TREE, str(entry), "not a folder this root admits")
        for entry in entries
        if not entry.name.startswith((".", "__")) and (not entry.is_dir() or not folders(entry.name))
    )
    yield from (
        RuleError(Rule.TREE, str(file), f"holds only {suffix} files named in one word ({WORD.pattern})")
        for entry in entries
        if entry.is_dir() and folders(entry.name) and entry.name not in skip
        for file in sorted(entry.iterdir())
        if not file.name.startswith((".", "__"))
        and (file.is_dir() or file.suffix != suffix or (suffix == RUNNER_SUFFIX and not WORD.fullmatch(file.stem)))
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
            ### keyed by file, as `draft.specs` is: a misnamed file is FILENAME's breach, never a crash here.
            (index[dependency], index[stem])
            for stem, spec in draft.specs.items()
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
    """Every runner a spec plugs exists: `owned/<name>` in the section's owned folder, `agnostic/...` in the tools."""
    yield from (
        RuleError(Rule.RUNNER, f"{stem}.{slot}", f"plugs {ref}: no module at {draft.modules[ref].file}")
        for stem, spec in draft.specs.items()
        for slot, ref in spec.plugs.items()
        if not draft.modules[ref].exists
    )


def rule_shape(draft: Draft) -> Violations:
    """A runner module defines exactly one function — its role — and nothing else to call."""
    yield from (
        RuleError(
            Rule.SHAPE, ref, f"a runner module defines exactly one function, found {[f.name for f in module.functions]}"
        )
        for ref, module in draft.modules.items()
        if module.exists and len(module.functions) != 1
    )


def rule_role(draft: Draft) -> Violations:
    """A runner is plugged only where its role belongs: a `check` slot takes a `check`, a `pre` a `pre_run`..."""
    yield from (
        RuleError(
            Rule.ROLE, f"{stem}.{slot}", f"plugs {ref}, a `{function.name}`: the {slot} slot takes a `{ROLES[slot]}`"
        )
        for stem, spec in draft.specs.items()
        for slot, ref in spec.plugs.items()
        if (module := draft.modules[ref]).exists and len(module.functions) == 1
        for function in module.functions
        if function.name != ROLES[slot]
    )


def rule_signature(draft: Draft) -> Violations:
    """A runner reads exactly as its role's contract: async, the RunState and the Call in, the role's type out."""
    yield from (
        RuleError(Rule.SIGNATURE, ref, f"must read `{SIGNATURES[Role(function.name)]}`, reads `{function.signature}`")
        for ref, module in draft.modules.items()
        if len(module.functions) == 1
        for function in module.functions
        if function.name in ROLE_NAMES and function.signature != SIGNATURES[Role(function.name)]
    )


def rule_doc(draft: Draft) -> Violations:
    """A runner says what it does: its docstring becomes its description."""
    yield from (
        RuleError(Rule.DOC, ref, "a runner needs a docstring")
        for ref, module in draft.modules.items()
        for function in module.functions
        if not function.doc.strip()
    )


def rule_orphan(draft: Draft) -> Violations:
    """Every owned runner of the section is plugged by one of its specs; one plugged by none is deprecated.
    A spec that did not decode plugs what nobody can tell: the law waits until the section decodes whole."""
    yield from (
        RuleError(
            Rule.ORPHAN, f"owned/{name}", f"no spec of {draft.pipeline}/{draft.section} plugs it: deprecated runner"
        )
        for name in sorted(draft.owned - draft.plugged if not draft.broken else ())
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
        Rule.SHAPE: rule_shape,
        Rule.ROLE: rule_role,
        Rule.SIGNATURE: rule_signature,
        Rule.DOC: rule_doc,
        Rule.WIKI: rule_wiki,
        Rule.ORPHAN: rule_orphan,
    }
)


def judge_section(draft: Draft) -> list[RuleError]:
    """Every section law over one draft, every breach collected."""
    return [error for rule in SECTION_RULES.values() for error in rule(draft)]
