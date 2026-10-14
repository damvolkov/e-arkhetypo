"""tests/unit: logic.discover — a system's tree on disk, cataloged lazily, judged whole, its runners loaded on demand."""

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.instrument.state import RunState
from e_graph.logic.discover import SpecDiscover, SystemDiscover
from e_graph.logic.errors import AuditError, CatalogError, Rule, Severity
from e_graph.logic.models import Call, DeterministicSpec, Role, Runner, SemanticSpec, Slot
from e_graph.models.section import Section

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

    from core.state import State

SPEC_SUM = """\
kind: deterministic
name: EXT-line-sum
description: Sum of the invoice lines.
runner: owned/linesum
check: agnostic/context/filled
args:
  runner: {scale: 2}
  check: {key: lines}
output:
  type: object
  properties: {total: {type: number}}
  required: [total]
"""
SPEC_TOTAL = """\
kind: semantic
name: EXT-total-amount
description: The total the invoice states.
instructions: Read the total amount.
pre: owned/lastpage
depends: [EXT-line-sum]
wiki: [net-amount]
output: {type: object, properties: {total: {type: number}}}
"""
SPEC_KIND = """\
kind: semantic
name: CLS-kind
description: The document kind.
instructions: Classify.
output: {type: object}
"""
RUNNER_SUM = '''\
"""linesum: add the lines up."""

from typing import Any

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    scale: int = 1


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Add every line amount."""
    return {"total": sum(state.context.lines) * call.args.scale}
'''
RUNNER_LAST = '''\
"""lastpage: the page the total sits on."""

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def pre_run(state: RunState, call: Call) -> str:
    """The last page, where totals live."""
    return state.context.pages[-1]
'''
TOOL_FILLED = '''\
"""filled: a context key holds something."""

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True):
    key: str


async def check(state: RunState, call: Call) -> bool:
    """Only when the key holds something."""
    return bool(state.context.get(call.args.key))
'''
EXPLODES = 'raise RuntimeError("imported")\n'


class Tree:
    """A system's specs and runners written under a temporary root."""

    def __init__(self, root: Path) -> None:
        self.specs, self.runners = root / "specs", root / "runners"

    def spec(self, section: str, name: str, text: str, pipeline: str = "doc") -> Path:
        return self._write(self.specs / pipeline / section / f"{name}.yaml", text)

    def owned(self, section: str, name: str, text: str, pipeline: str = "doc") -> Path:
        return self._write(self.runners / "owned" / pipeline / section / f"{name}.py", text)

    def tool(self, capability: str, name: str, text: str) -> Path:
        return self._write(self.runners / "agnostic" / capability / f"{name}.py", text)

    def wiki(self, term: str, pipeline: str | None = None) -> Path:
        folder = self.specs / pipeline / "wiki" if pipeline else self.specs / "wiki"
        return self._write(folder / f"{term}.md", f"# {term}\n")

    def discover(self, pipeline: str = "doc", **options: Any) -> SpecDiscover:
        return SpecDiscover(pipeline, specs=self.specs, runners=self.runners, **options)

    def system(self, **mounts: frozenset[Section]) -> SystemDiscover:
        return SystemDiscover(mounts, specs=self.specs, runners=self.runners)

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    """A coherent `doc` pipeline: extract (one deterministic, one semantic) and classify, one tool, wiki shared."""
    built = Tree(tmp_path)
    built.spec("extract", "EXT-line-sum", SPEC_SUM)
    built.spec("extract", "EXT-total-amount", SPEC_TOTAL)
    built.spec("classify", "CLS-kind", SPEC_KIND)
    built.owned("extract", "linesum", RUNNER_SUM)
    built.owned("extract", "lastpage", RUNNER_LAST)
    built.tool("context", "filled", TOOL_FILLED)
    built.wiki("net-amount")
    return built


DOC = frozenset({Section.CLASSIFY, Section.EXTRACT})


def found(error: CatalogError) -> set[tuple[Rule, str]]:
    return {(breach.rule, breach.subject.rpartition("/")[2]) for breach in error.breaches}


##### INDEX #####
def test_sections_in_walking_order_custom_last(tree: Tree) -> None:
    tree.spec("custom", "CUS-stamp", SPEC_KIND.replace("CLS-kind", "CUS-stamp"))
    (tree.specs / "doc" / "report").mkdir(parents=True)
    (tree.runners / "owned" / "doc" / "inference").mkdir(parents=True)
    assert tree.discover().sections() == (Section.CLASSIFY, Section.EXTRACT, Section.REPORT, Section.CUSTOM)
    assert tree.discover().pipeline == "doc"


def test_an_unknown_pipeline_has_no_sections(tree: Tree) -> None:
    assert tree.discover("ghost").sections() == ()


##### CATALOG #####
async def test_catalog_resolves_every_plugged_runner(tree: Tree) -> None:
    catalog = await tree.discover().catalog(Section.EXTRACT)
    assert (catalog.pipeline, catalog.section, sorted(catalog.nodes)) == (
        "doc",
        Section.EXTRACT,
        ["EXT-line-sum", "EXT-total-amount"],
    )
    summed, total = catalog.nodes["EXT-line-sum"], catalog.nodes["EXT-total-amount"]
    assert isinstance(summed.spec, DeterministicSpec)
    assert isinstance(total.spec, SemanticSpec)
    assert {slot: (runner.ref, runner.role, runner.doc) for slot, runner in summed.runners.items()} == {
        Slot.RUNNER: ("owned/linesum", Role.RUN, "Add every line amount."),
        Slot.CHECK: ("agnostic/context/filled", Role.CHECK, "Only when the key holds something."),
    }
    assert summed.runners[Slot.RUNNER].file.endswith("runners/owned/doc/extract/linesum.py")
    assert summed.runners[Slot.CHECK].file.endswith("runners/agnostic/context/filled.py")
    assert [runner.scope for runner in summed.runners.values()] == ["owned", "agnostic"]
    assert total.runners[Slot.PRE].role is Role.PRE
    assert summed.file.endswith("specs/doc/extract/EXT-line-sum.yaml")
    assert catalog.wiki == {"net-amount": "# net-amount\n"}


async def test_catalog_validates_each_slots_args(tree: Tree) -> None:
    nodes = (await tree.discover().catalog(Section.EXTRACT)).nodes
    summed = nodes["EXT-line-sum"].args
    assert (summed[Slot.RUNNER].scale, summed[Slot.CHECK].key) == (2, "lines")
    ### a runner that declares no `Args` takes none: `{}`.
    assert nodes["EXT-total-amount"].args == {Slot.PRE: {}}


async def test_a_semantic_section_needs_no_runners(tree: Tree) -> None:
    catalog = await tree.discover().catalog(Section.CLASSIFY)
    assert (catalog.nodes["CLS-kind"].runners, catalog.nodes["CLS-kind"].args) == ({}, {})


async def test_pipeline_wiki_counts_like_the_shared_one(tree: Tree) -> None:
    (tree.specs / "wiki" / "net-amount.md").unlink()
    tree.wiki("net-amount", pipeline="doc")
    assert "EXT-total-amount" in (await tree.discover().catalog(Section.EXTRACT)).nodes


async def test_owned_runners_resolve_in_their_own_pipeline_only(tree: Tree) -> None:
    tree.spec("extract", "EXT-line-sum", SPEC_SUM, pipeline="filing")
    tree.owned("extract", "linesum", RUNNER_SUM, pipeline="filing")
    catalog = await tree.discover("filing").catalog(Section.EXTRACT)
    assert catalog.nodes["EXT-line-sum"].runners[Slot.RUNNER].file.endswith("owned/filing/extract/linesum.py")
    assert catalog.nodes["EXT-line-sum"].runners[Slot.CHECK].file.endswith("agnostic/context/filled.py")


async def test_catalog_built_once_and_kept(tree: Tree, mocker: MockerFixture) -> None:
    discover = tree.discover()
    build = mocker.spy(SpecDiscover, "_catalog_build")
    first, second = await asyncio.gather(discover.catalog(Section.EXTRACT), discover.catalog(Section.EXTRACT))
    assert first is second is await discover.catalog(Section.EXTRACT)
    assert build.call_count == 1
    assert discover.built == (first,)


async def test_walk_builds_only_what_is_consumed(tree: Tree, mocker: MockerFixture) -> None:
    discover = tree.discover()
    build = mocker.spy(SpecDiscover, "_catalog_build")
    walk = discover.walk()
    assert build.call_count == 0
    first = await anext(walk)
    assert (first.section, build.call_count) == (Section.CLASSIFY, 1)
    assert [catalog.section async for catalog in walk] == [Section.EXTRACT]


##### BREACHES #####
async def test_every_breach_of_a_section_reported_together(tree: Tree) -> None:
    tree.spec("extract", "EXT-broken", "kind: deterministic\nname: EXT-broken\n")
    tree.spec("extract", "EXT-bad-yaml", "kind: [unclosed\n")
    tree.spec("extract", "EXT-merged", "base: &b {x: 1}\nother:\n  <<: *b\n")
    tree.spec("extract", "EXT-wrong-name", SPEC_KIND.replace("CLS-kind", "EXT-other"))
    tree.spec(
        "classify", "CLS-ghost", SPEC_KIND.replace("CLS-kind", "CLS-ghost").replace("Classify.", "x\npre: owned/gone")
    )
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    assert found(caught.value) == {
        (Rule.DECODE, "EXT-broken.yaml"),
        (Rule.DECODE, "EXT-bad-yaml.yaml"),
        (Rule.MERGE, "EXT-merged.yaml"),
        (Rule.FILENAME, "EXT-wrong-name"),
    }
    assert str(caught.value).startswith("doc/extract: 4 broken laws")
    with pytest.raises(CatalogError) as ghost:
        await tree.discover().catalog(Section.CLASSIFY)
    assert found(ghost.value) == {(Rule.RUNNER, "CLS-ghost.pre")}


async def test_an_unplugged_owned_runner_is_an_orphan(tree: Tree) -> None:
    tree.owned("extract", "retired", RUNNER_SUM)
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    assert found(caught.value) == {(Rule.ORPHAN, "retired")}


@pytest.mark.parametrize(
    ("args", "detail"),
    [
        (
            {"runner": {"scale": "two"}, "check": {"key": "x"}},
            "owned/linesum: Expected `int`, got `str` - at `$.scale`",
        ),
        ({"runner": {"scale": 2, "extra": 1}, "check": {"key": "x"}}, "Object contains unknown field `extra`"),
        ({"check": {}}, "agnostic/context/filled: Object missing required field `key`"),
    ],
    ids=["wrong-type", "unknown-field", "missing-field"],
)
async def test_args_breaking_the_runners_contract_are_named(tree: Tree, args: dict[str, Any], detail: str) -> None:
    text = SPEC_SUM.replace("args:\n  runner: {scale: 2}\n  check: {key: lines}\n", "")
    tree.spec("extract", "EXT-line-sum", text.replace("output:", f"args: {args}\noutput:".replace("'", '"')))
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    ((rule, subject),) = found(caught.value)
    assert (rule, subject.partition(".")[0]) == (Rule.ARGS, "EXT-line-sum")
    assert detail in caught.value.breaches[0].detail


async def test_args_for_a_runner_that_declares_none_are_refused(tree: Tree) -> None:
    tree.spec("extract", "EXT-total-amount", SPEC_TOTAL + "args:\n  pre: {page: 3}\n")
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    assert found(caught.value) == {(Rule.ARGS, "EXT-total-amount.pre")}
    assert caught.value.breaches[0].detail == "owned/lastpage declares no Args, given ['page']"


async def test_no_runner_executes_while_a_law_is_broken(tree: Tree) -> None:
    tree.owned("extract", "linesum", RUNNER_SUM + EXPLODES)
    tree.spec("extract", "EXT-wrong-name", SPEC_KIND.replace("CLS-kind", "EXT-other"))
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    assert found(caught.value) == {(Rule.FILENAME, "EXT-wrong-name")}


async def test_a_name_from_another_section_fails_decoding(tree: Tree) -> None:
    tree.spec("extract", "CLS-kind", SPEC_KIND)
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    (error,) = caught.value.breaches
    assert error.rule is Rule.DECODE
    assert "matching regex '^EXT-" in error.detail


async def test_a_failed_section_is_never_kept(tree: Tree) -> None:
    tree.owned("classify", "retired", RUNNER_SUM)
    discover = tree.discover()
    with pytest.raises(CatalogError):
        await discover.catalog(Section.CLASSIFY)
    (tree.runners / "owned" / "doc" / "classify" / "retired.py").unlink()
    assert "CLS-kind" in (await discover.catalog(Section.CLASSIFY)).nodes


##### AUDIT #####
async def test_audit_returns_every_catalog(tree: Tree) -> None:
    assert [catalog.section for catalog in await tree.discover().audit()] == [Section.CLASSIFY, Section.EXTRACT]


async def test_audit_reports_tree_and_sections_at_once(tree: Tree) -> None:
    tree.owned("classify", "retired", RUNNER_SUM)
    (tree.specs / "doc" / "misc").mkdir()
    (tree.runners / "owned" / "doc" / "extract" / "notes.txt").write_text("")
    (tree.specs / "doc" / "wiki" / "glossary.md").parent.mkdir(parents=True)
    (tree.specs / "doc" / "wiki" / "glossary.md").write_text("")
    with pytest.raises(AuditError) as caught:
        await tree.discover().audit()
    groups = {group.message.split(":")[0]: group for group in caught.value.catalogs}
    assert set(groups) == {"doc", "doc/classify"}
    assert {(error.rule, error.subject.rpartition("/")[2]) for error in groups["doc"].breaches} == {
        (Rule.TREE, "misc"),
        (Rule.TREE, "notes.txt"),
    }
    assert [error.rule for error in groups["doc/classify"].breaches] == [Rule.ORPHAN]


async def test_audit_lets_an_unexpected_failure_through(tree: Tree, mocker: MockerFixture) -> None:
    discover = tree.discover()
    mocker.patch.object(SpecDiscover, "_catalog_build", side_effect=RuntimeError("disk gone"))
    with pytest.raises(RuntimeError, match="disk gone"):
        await discover.audit()


##### LOAD #####
async def test_load_hands_the_role_function_from_one_execution(tree: Tree, system: State) -> None:
    discover = tree.discover()
    catalog = await discover.catalog(Section.EXTRACT)
    node = catalog.nodes["EXT-line-sum"]
    run = await discover.load(node.runners[Slot.RUNNER])
    assert run is await discover.load(node.runners[Slot.RUNNER])
    state = RunState(system)
    state.context.lines = [1.5, 2.5]
    call = Call(
        pipeline="doc", section=Section.EXTRACT, spec="EXT-line-sum", slot=Slot.RUNNER, args=node.args[Slot.RUNNER]
    )
    assert await run(state, call) == {"total": 8.0}
    pre = await discover.load(catalog.nodes["EXT-total-amount"].runners[Slot.PRE])
    state.context.pages = ["cover", "totals"]
    assert await pre(state, call) == "totals"


async def test_load_executes_a_module_never_seen_on_first_use(tree: Tree) -> None:
    runner = Runner(
        ref="owned/linesum", role=Role.RUN, file=str(tree.runners / "owned/doc/extract/linesum.py"), doc="x"
    )
    assert getattr(await tree.discover().load(runner), "__name__", "") == "run"


async def test_load_refuses_a_file_that_is_no_source(tree: Tree, tmp_path: Path) -> None:
    runner = Runner(ref="owned/x", role=Role.RUN, file=str(tree.runners / "x.txt"), doc="x")
    with pytest.raises(ImportError, match="is no Python source"):
        await tree.discover().load(runner)


##### SYSTEM #####
async def test_a_coherent_system_reports_clean(tree: Tree) -> None:
    report = await tree.system(doc=DOC).check()
    assert (report.ok, report.pipelines, report.sections, report.specs, report.breaches) == (True, ("doc",), 2, 3, ())


async def test_system_laws_name_what_no_pipeline_owns(tree: Tree) -> None:
    tree.spec("extract", "EXT-line-sum", SPEC_SUM, pipeline="legacy")
    tree.owned("extract", "linesum", RUNNER_SUM, pipeline="retired")
    tree.spec("report", "REP-out", SPEC_KIND.replace("CLS-kind", "REP-out"))
    (tree.runners / "stray").mkdir()
    (tree.runners / "agnostic" / "loose.py").write_text("")
    (tree.runners / "agnostic" / "Bad_Name").mkdir()
    tree.tool("table", "figure", TOOL_FILLED)
    report = await tree.system(doc=DOC).check()
    assert {(breach.rule, breach.subject.rpartition("/")[2], breach.severity) for breach in report.breaches} == {
        (Rule.PIPELINE, "legacy", Severity.ERROR),
        (Rule.PIPELINE, "retired", Severity.ERROR),
        (Rule.UNMOUNTED, "report", Severity.ERROR),
        (Rule.TREE, "stray", Severity.ERROR),
        (Rule.TREE, "loose.py", Severity.ERROR),
        (Rule.TREE, "Bad_Name", Severity.ERROR),
        (Rule.IDLE, "figure", Severity.WARNING),
    }
    assert (report.ok, len(report.errors), len(report.warnings)) == (False, 6, 1)


async def test_an_idle_tool_alone_lets_the_check_pass(tree: Tree) -> None:
    tree.tool("table", "figure", TOOL_FILLED)
    report = await tree.system(doc=DOC).check()
    assert (report.ok, [breach.subject for breach in report.warnings]) == (True, ["agnostic/table/figure"])


async def test_a_broken_pipeline_never_hides_its_sound_sections(tree: Tree) -> None:
    tree.owned("classify", "retired", RUNNER_SUM)
    report = await tree.system(doc=DOC).check()
    assert (report.ok, report.sections, report.specs) == (False, 1, 2)
    assert [(breach.rule, breach.subject.rpartition("/")[2]) for breach in report.breaches] == [
        (Rule.ORPHAN, "retired")
    ]


async def test_a_check_of_some_pipelines_judges_no_idleness(tree: Tree) -> None:
    tree.tool("table", "figure", TOOL_FILLED)
    report = await tree.system(doc=DOC).check(frozenset({"doc", "ghost"}))
    assert report.pipelines == ("doc", "ghost")
    assert [(breach.rule, breach.subject) for breach in report.breaches] == [(Rule.PIPELINE, "ghost")]


async def test_an_empty_system_reports_nothing(tmp_path: Path) -> None:
    report = await Tree(tmp_path).system().check()
    assert (report.ok, report.pipelines, report.sections, report.breaches) == (True, (), 0, ())


async def test_the_check_lets_an_unexpected_failure_through(tree: Tree, mocker: MockerFixture) -> None:
    mocker.patch.object(SpecDiscover, "_catalog_build", side_effect=RuntimeError("disk gone"))
    with pytest.raises(RuntimeError, match="disk gone"):
        await tree.system(doc=DOC).check()
