"""tests/unit: logic.discover against crafted pipelines — coherent ones read back as crafted, every law broken on purpose.

Each test meets several random pipelines (the `crafter` fixture is seeded three ways). A breach is
applied to a coherent crafted section and the discovery must name exactly it — its rule and its
subject — with no cascade: a spec that fails to decode is reported once, never again as a missing
dependency or an orphaned runner. Then laziness: what is not consumed is never read, what is read
is read once, and no runner is ever imported by discovering it."""

import asyncio
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.discover import SpecDiscover
from e_graph.logic.errors import AuditError, CatalogError, Rule
from e_graph.logic.models import DeterministicSpec, Hook, SemanticSpec
from e_graph.models.section import ORDER, Section

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture

    from support.crafter import Blueprint, SpecCrafter

SECTION = Section.EXTRACT
type Breaches = set[tuple[Rule, str]]


def subject(raw: str) -> str:
    """A breach's subject, short: a file by its stem, a spec or function as named."""
    return raw.rpartition("/")[2].removesuffix(".yaml")


def found(error: CatalogError) -> Breaches:
    return {(breach.rule, subject(breach.subject)) for breach in error.breaches}


async def breaches(crafter: SpecCrafter) -> CatalogError:
    with pytest.raises(CatalogError) as caught:
        await crafter.discover().catalog(SECTION)
    return caught.value


@pytest.fixture
def blueprint(crafter: SpecCrafter) -> Blueprint:
    """A coherent extract section: both kinds, a random DAG, two fallbacks, wiki terms."""
    crafted = crafter.craft(SECTION, n=12, semantic=0.5, fallbacks=2)
    assert crafted.deterministic, "a seed must craft deterministic specs"
    assert crafted.semantic, "a seed must craft semantic specs"
    assert crafted.edges, "a seed must craft dependencies"
    return crafted


##### PICKS — which crafted spec a breach hits #####
def targets(bp: Blueprint) -> set[str]:
    return set(bp.fallbacks.values())


def regular(bp: Blueprint, kind: type) -> str:
    """The first spec of `kind` that is no fallback target: free to take depends, fallbacks, anything."""
    return next(name for name in bp.specs if isinstance(bp.specs[name], kind) and name not in targets(bp))


def det(bp: Blueprint) -> str:
    return regular(bp, DeterministicSpec)


def sem(bp: Blueprint) -> str:
    return regular(bp, SemanticSpec)


##### COHERENT — what is crafted is what is discovered #####
async def test_crafted_pipeline_reads_back_as_crafted(crafter: SpecCrafter) -> None:
    crafted = {section: crafter.craft(section, n=9) for section in (Section.CLASSIFY, Section.EXTRACT, Section.CUSTOM)}
    catalogs = {catalog.section: catalog for catalog in await crafter.discover().audit()}
    assert list(catalogs) == [Section.CLASSIFY, Section.EXTRACT, Section.CUSTOM]
    assert {
        section: {name: node.spec for name, node in catalog.nodes.items()} for section, catalog in catalogs.items()
    } == {section: bp.specs for section, bp in crafted.items()}
    assert {
        section: {name: set(node.hooks) for name, node in catalog.nodes.items()}
        for section, catalog in catalogs.items()
    } == {section: {name: set(hooks) for name, hooks in bp.hooks.items()} for section, bp in crafted.items()}


async def test_every_crafted_hook_carries_its_doc(crafter: SpecCrafter, blueprint: Blueprint) -> None:
    catalog = await crafter.discover().catalog(SECTION)
    runners = [runner for node in catalog.nodes.values() for runner in node.hooks.values()]
    assert runners
    assert {runner.doc for runner in runners} == {"Crafted hook."}
    assert all(runner.name == f"{runner.spec}.{runner.hook}" for runner in runners)


##### FIELD BREACHES — one document, caught by msgspec while decoding #####
@dataclass(frozen=True, slots=True)
class Field:
    """A field broken in one spec's YAML: which kind it hits, the change, the error it must surface."""

    pick: Callable[[Blueprint], str]
    change: Callable[[str], dict[str, Any]]
    detail: str


FIELDS: dict[str, Field] = {
    "name-uppercase": Field(det, lambda _: {"name": "EXT-Bad-name"}, "at `$.name`"),
    "name-other-section": Field(det, lambda _: {"name": "CLS-kind"}, "matching regex '^EXT-"),
    "name-missing": Field(det, lambda _: {"name": ...}, "missing required field `name`"),
    "description-blank": Field(sem, lambda _: {"description": "   "}, "at `$.description`"),
    "description-missing": Field(det, lambda _: {"description": ...}, "missing required field `description`"),
    "output-array-root": Field(
        det, lambda _: {"output": {"type": "array"}}, 'needs an object root: {"type": "object", ...} - at `$.output`'
    ),
    "output-meta-schema": Field(
        sem, lambda _: {"output": {"type": "object", "minProperties": "x"}}, "meta-schema - at `$.output`"
    ),
    "output-missing": Field(det, lambda _: {"output": ...}, "missing required field `output`"),
    "depends-other-section": Field(det, lambda _: {"depends": ["INF-total-1"]}, "at `$.depends[0]`"),
    "depends-self": Field(det, lambda name: {"depends": [name]}, "a spec cannot depend on itself"),
    "depends-repeated": Field(sem, lambda _: {"depends": ["EXT-x-1", "EXT-x-1"]}, "depends repeats a spec"),
    "depends-not-a-list": Field(det, lambda _: {"depends": "EXT-x-1"}, "at `$.depends`"),
    "fallback-other-section": Field(det, lambda _: {"fallback": "REP-out-1"}, "at `$.fallback`"),
    "fallback-self": Field(sem, lambda name: {"fallback": name}, "a spec cannot be its own fallback"),
    "fallback-also-dependency": Field(
        det, lambda _: {"depends": ["EXT-x-1"], "fallback": "EXT-x-1"}, "cannot also be a dependency"
    ),
    "wiki-malformed": Field(det, lambda _: {"wiki": ["Net Amount"]}, "at `$.wiki[0]`"),
    "wiki-repeated": Field(sem, lambda _: {"wiki": ["net-amount", "net-amount"]}, "wiki repeats a term"),
    "bound-unknown": Field(det, lambda _: {"bound": "gpu"}, "at `$.bound`"),
    "tier-unknown": Field(sem, lambda _: {"tier": "ultra"}, "at `$.tier`"),
    "version-zero": Field(det, lambda _: {"version": 0}, "Expected `int` >= 1 - at `$.version`"),
    "version-text": Field(sem, lambda _: {"version": "two"}, "at `$.version`"),
    "timeout-zero": Field(det, lambda _: {"timeout": "PT0S"}, "timeout must be positive"),
    "timeout-negative": Field(sem, lambda _: {"timeout": "-PT5S"}, "timeout must be positive"),
    "timeout-malformed": Field(det, lambda _: {"timeout": "soon"}, "at `$.timeout`"),
    "field-unknown": Field(det, lambda _: {"owner": "ana"}, "unknown field `owner`"),
    "kind-unknown": Field(det, lambda _: {"kind": "magic"}, "Invalid value 'magic' - at `$.kind`"),
    "kind-missing": Field(sem, lambda _: {"kind": ...}, "missing required field `kind`"),
    "instructions-missing": Field(sem, lambda _: {"instructions": ...}, "missing required field `instructions`"),
    "instructions-on-deterministic": Field(det, lambda _: {"instructions": "Read."}, "unknown field `instructions`"),
    "examples-off-schema": Field(
        sem,
        lambda _: {
            "output": {"type": "object", "properties": {"total": {"type": "number"}}},
            "examples": [{"total": "x"}],
        },
        "examples [0] do not match output",
    ),
    "examples-on-deterministic": Field(det, lambda _: {"examples": [{}]}, "unknown field `examples`"),
}


@pytest.mark.parametrize("case", FIELDS.values(), ids=FIELDS.keys())
async def test_a_broken_field_is_one_decode_breach(crafter: SpecCrafter, blueprint: Blueprint, case: Field) -> None:
    name = case.pick(blueprint)
    crafter.patch(SECTION, name, **case.change(name))
    error = await breaches(crafter)
    ### no cascade: its runner is no orphan, its dependents miss nothing — the one breach is the decode.
    assert found(error) == {(Rule.DECODE, name)}
    assert case.detail in error.breaches[0].detail


async def test_every_broken_field_reported_in_one_pass(crafter: SpecCrafter, blueprint: Blueprint) -> None:
    names = random.Random(len(blueprint.specs)).sample(sorted(set(blueprint.specs) - targets(blueprint)), k=5)
    cases = random.Random(7).sample([case for case in FIELDS.values() if case.pick is det], k=5)
    _ = [
        crafter.patch(
            SECTION, name, **{**case.change(name), "kind": "deterministic", "instructions": ..., "examples": ...}
        )
        for name, case in zip(names, cases, strict=True)
    ]
    assert found(await breaches(crafter)) == {(Rule.DECODE, name) for name in names}


##### SOURCE BREACHES — the text, before it is decoded #####
@pytest.mark.parametrize(
    ("text", "rule", "detail"),
    [
        ("kind: deterministic\nbase: &b {x: 1}\nother:\n  <<: *b\n", Rule.MERGE, "line 4: merge keys (<<) are banned"),
        ("kind: [unclosed\n", Rule.DECODE, "yaml decode failed"),
        ("", Rule.DECODE, "expected exactly one YAML document, found 0"),
        ("- just\n- a list\n", Rule.DECODE, "Expected `object`"),
    ],
    ids=["merge-key", "yaml-syntax", "empty-file", "not-a-mapping"],
)
async def test_a_broken_source_is_named_before_decoding(
    crafter: SpecCrafter, blueprint: Blueprint, text: str, rule: Rule, detail: str
) -> None:
    name = det(blueprint)
    crafter.write_raw(SECTION, name, text)
    error = await breaches(crafter)
    assert found(error) == {(rule, name)}
    assert detail in error.breaches[0].detail


##### SECTION BREACHES — what only the whole section can tell #####
def rename(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    crafter.patch(SECTION, name, name="EXT-renamed-99")
    return {(Rule.FILENAME, name)}


def ghost_dependency(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = sem(bp)
    crafter.patch(SECTION, name, depends=[*bp.specs[name].depends, "EXT-ghost-1"])
    return {(Rule.DEPENDS, name)}


def ghost_fallback(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = next(name for name in bp.specs if name not in targets(bp) and name not in bp.fallbacks)
    crafter.patch(SECTION, name, fallback="EXT-ghost-2")
    return {(Rule.FALLBACK, name)}


def fallback_chain(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    first, second = sorted(targets(bp))
    crafter.patch(SECTION, first, fallback=second)
    return {(Rule.FALLBACK, first)}


def fallback_with_depends(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    target = min(targets(bp))
    crafter.patch(SECTION, target, depends=[det(bp)])
    return {(Rule.FALLBACK, target)}


def fallback_depended_on(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    target = min(targets(bp))
    name = next(name for name in bp.specs if name not in targets(bp) and bp.fallbacks.get(name) != target)
    crafter.patch(SECTION, name, depends=[*bp.specs[name].depends, target])
    return {(Rule.FALLBACK, name)}


def cycle(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    dependency, dependent = min(bp.edges)
    crafter.patch(SECTION, dependency, depends=[*bp.specs[dependency].depends, dependent])
    return {(Rule.CYCLE, str(SECTION))}


def runner_deleted(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    crafter.runner_file(SECTION, name).unlink()
    return {(Rule.RUNNER, name)}


def runner_without_run(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    crafter.write_runner(SECTION, name, {Hook.CHECK})
    return {(Rule.RUNNER, name)}


def runner_orphaned(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    crafter.write_runner(SECTION, "EXT-retired-1", {Hook.RUN})
    return {(Rule.ORPHAN, "EXT-retired-1")}


def hook_helper(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    helper = 'async def helper(state: RunState) -> None:\n    """Help."""\n'
    crafter.write_runner(SECTION, name, bp.hooks[name], functions=helper)
    return {(Rule.HOOK, f"{name}.helper")}


def hook_run_on_semantic(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = sem(bp)
    crafter.write_runner(SECTION, name, {Hook.RUN})
    return {(Rule.HOOK, f"{name}.run")}


def hook_pre_on_deterministic(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    crafter.write_runner(SECTION, name, bp.hooks[name] | {Hook.PRE})
    return {(Rule.HOOK, f"{name}.pre_run")}


def signature_sync(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    sync = crafter.render(Hook.RUN, signature="def run(state: RunState) -> dict[str, Any]")
    crafter.write_runner(SECTION, name, bp.hooks[name] - {Hook.RUN}, functions=sync)
    return {(Rule.SIGNATURE, f"{name}.run")}


def signature_params(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = sem(bp)
    short = crafter.render(Hook.POST, signature="async def post_run(state: RunState) -> dict[str, Any]").replace(
        "output", "{}"
    )
    crafter.write_runner(SECTION, name, bp.hooks[name] - {Hook.POST}, functions=short)
    return {(Rule.SIGNATURE, f"{name}.post_run")}


def signature_return(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    check = crafter.render(Hook.CHECK, signature="async def check(state: RunState) -> str")
    crafter.write_runner(SECTION, name, bp.hooks[name] - {Hook.CHECK}, functions=check)
    return {(Rule.SIGNATURE, f"{name}.check")}


def doc_missing(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    crafter.write_runner(SECTION, name, bp.hooks[name] - {Hook.RUN}, functions=crafter.render(Hook.RUN, doc=None))
    return {(Rule.DOC, f"{name}.run")}


def wiki_ghost(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = sem(bp)
    crafter.patch(SECTION, name, wiki=["ghost-term"])
    return {(Rule.WIKI, name)}


def wiki_page_removed(crafter: SpecCrafter, bp: Blueprint) -> Breaches:
    name = det(bp)
    crafter.patch(SECTION, name, wiki=["net-amount"])
    (crafter.specs / "wiki" / "net-amount.md").unlink()
    return {(Rule.WIKI, spec) for spec, value in bp.specs.items() if "net-amount" in value.wiki} | {(Rule.WIKI, name)}


SECTION_BREACHES: dict[str, Callable[[SpecCrafter, Blueprint], Breaches]] = {
    "filename": rename,
    "depends-ghost": ghost_dependency,
    "fallback-ghost": ghost_fallback,
    "fallback-chain": fallback_chain,
    "fallback-with-depends": fallback_with_depends,
    "fallback-depended-on": fallback_depended_on,
    "cycle": cycle,
    "runner-deleted": runner_deleted,
    "runner-without-run": runner_without_run,
    "runner-orphaned": runner_orphaned,
    "hook-helper": hook_helper,
    "hook-run-on-semantic": hook_run_on_semantic,
    "hook-pre-on-deterministic": hook_pre_on_deterministic,
    "signature-sync": signature_sync,
    "signature-params": signature_params,
    "signature-return": signature_return,
    "doc-missing": doc_missing,
    "wiki-ghost": wiki_ghost,
    "wiki-page-removed": wiki_page_removed,
}


@pytest.mark.parametrize("breach", SECTION_BREACHES.values(), ids=SECTION_BREACHES.keys())
async def test_a_section_law_names_exactly_its_breach(
    crafter: SpecCrafter, blueprint: Blueprint, breach: Callable[[SpecCrafter, Blueprint], Breaches]
) -> None:
    expected = breach(crafter, blueprint)
    assert found(await breaches(crafter)) == expected


async def test_independent_breaches_reported_together(crafter: SpecCrafter, blueprint: Blueprint) -> None:
    expected = (
        runner_orphaned(crafter, blueprint) | wiki_ghost(crafter, blueprint) | signature_return(crafter, blueprint)
    )
    name = next(
        name
        for name in blueprint.specs
        if name not in targets(blueprint) and name not in {det(blueprint), sem(blueprint)}
    )
    crafter.patch(SECTION, name, version=0)
    error = await breaches(crafter)
    assert found(error) == expected | {(Rule.DECODE, name)}
    assert str(error).startswith(f"doc/extract: {len(expected) + 1} broken laws")


##### TREE BREACHES — the pipeline's folders, judged by the audit #####
async def test_audit_judges_the_tree_beside_the_sections(crafter: SpecCrafter, blueprint: Blueprint) -> None:
    (crafter.specs / "doc" / "misc").mkdir()
    (crafter.specs / "doc" / "extract" / "nested").mkdir()
    crafter.spec_file(SECTION, det(blueprint)).with_suffix(".yml").write_text("kind: deterministic\n")
    (crafter.runners / "doc" / "extract" / "notes.txt").write_text("")
    with pytest.raises(AuditError) as caught:
        await crafter.discover().audit()
    (tree,) = caught.value.catalogs
    assert {subject(breach.subject) for breach in tree.breaches} == {
        "misc",
        "nested",
        f"{det(blueprint)}.yml",
        "notes.txt",
    }
    assert {breach.rule for breach in tree.breaches} == {Rule.TREE}


##### LAZINESS — read only what is consumed, once; import nothing #####
@pytest.fixture
def wide(crafter: SpecCrafter) -> dict[Section, Blueprint]:
    """Every section crafted: the pipeline a lazy discovery must not read whole."""
    return {section: crafter.craft(section, n=10, fallbacks=1) for section in (*ORDER, Section.CUSTOM)}


async def test_walk_reads_a_section_only_when_reached(
    crafter: SpecCrafter, wide: dict[Section, Blueprint], mocker: MockerFixture
) -> None:
    decode = mocker.spy(SpecDiscover, "_catalog_decode")
    walk = crafter.discover().walk()
    assert decode.call_count == 0
    first = await anext(walk)
    assert (first.section, decode.call_count) == (Section.INGEST, len(wide[Section.INGEST].specs))
    assert [catalog.section async for catalog in walk] == [*ORDER[1:], Section.CUSTOM]
    assert decode.call_count == sum(len(bp.specs) for bp in wide.values())


async def test_a_read_section_is_never_read_again(
    crafter: SpecCrafter, wide: dict[Section, Blueprint], mocker: MockerFixture
) -> None:
    discover = crafter.discover()
    decode = mocker.spy(SpecDiscover, "_catalog_decode")
    first = await discover.audit()
    reads = decode.call_count
    second = await asyncio.gather(*(discover.catalog(section) for section in discover.sections() for _ in range(5)))
    assert decode.call_count == reads
    assert {id(catalog) for catalog in first} == {id(catalog) for catalog in second}


async def test_a_broken_section_stops_the_walk_where_it_stands(
    crafter: SpecCrafter, wide: dict[Section, Blueprint], mocker: MockerFixture
) -> None:
    crafter.patch(Section.CLASSIFY, next(iter(wide[Section.CLASSIFY].specs)), version=0)
    decode = mocker.spy(SpecDiscover, "_catalog_decode")
    walk = crafter.discover().walk()
    assert [(await anext(walk)).section for _ in range(2)] == [Section.INGEST, Section.NORMALIZE]
    with pytest.raises(CatalogError, match="doc/classify: 1 broken laws"):
        await anext(walk)
    read = {Section.INGEST, Section.NORMALIZE, Section.CLASSIFY}
    assert decode.call_count == sum(len(wide[section].specs) for section in read)


async def test_discovering_imports_no_runner(crafter: SpecCrafter, wide: dict[Section, Blueprint]) -> None:
    ### every runner module explodes on import: discovering the pipeline must never set one off.
    files = sorted((crafter.runners / "doc").rglob("*.py"))
    _ = [file.write_text(file.read_text() + '\nraise RuntimeError("imported")\n') for file in files]
    catalogs = await crafter.discover().audit()
    assert sum(len(node.hooks) for catalog in catalogs for node in catalog.nodes.values()) > 0
    runner = next(runner for catalog in catalogs for node in catalog.nodes.values() for runner in node.hooks.values())
    with pytest.raises(RuntimeError, match="imported"):
        await crafter.discover().load(runner)


async def test_a_runner_loads_alone_once_and_leaves_no_module_behind(
    crafter: SpecCrafter, blueprint: Blueprint, mocker: MockerFixture
) -> None:
    discover = crafter.discover()
    catalog = await discover.catalog(SECTION)
    load = mocker.spy(SpecDiscover, "_load_hook")
    runner = catalog.nodes[det(blueprint)].hooks[Hook.RUN]
    hooks = await asyncio.gather(*(discover.load(runner) for _ in range(8)))
    await discover.load(runner)
    assert len({id(hook) for hook in hooks}) == 1
    assert load.call_count == 1
    assert not [module for module in sys.modules if module.startswith("e_graph.runners.")]


def test_crafted_specs_are_validated_at_birth(crafter: SpecCrafter) -> None:
    ### the crafter builds specs in code: a structure it pins wrong fails there, before any file exists.
    with pytest.raises(Exception, match="a spec cannot depend on itself"):
        crafter._craft_spec(
            DeterministicSpec, "EXT-self-1", depends=("EXT-self-1",), fallback=None, wiki=(), output={"type": "object"}
        )
    assert not Path(crafter.specs).exists()
