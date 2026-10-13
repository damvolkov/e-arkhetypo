"""tests/unit: logic.discover — a pipeline tree on disk, cataloged lazily, judged whole, its hooks loaded on demand."""

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.instrument.state import RunState
from e_graph.logic.discover import SpecDiscover
from e_graph.logic.errors import AuditError, CatalogError, Rule
from e_graph.logic.models import DeterministicSpec, Hook, Runner, SemanticSpec
from e_graph.models.section import Section

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

    from core.state import State

SPEC_SUM = """\
kind: deterministic
name: EXT-line-sum
description: Sum of the invoice lines.
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
"""EXT-line-sum: add the lines up."""

from typing import Any

from e_graph.instrument.state import RunState


async def run(state: RunState) -> dict[str, Any]:
    """Add every line amount."""
    return {"total": sum(state.context.lines)}


async def check(state: RunState) -> bool:
    """Only when lines were found."""
    return bool(state.context.lines)
'''
RUNNER_TOTAL = '''\
"""EXT-total-amount: the page the total sits on."""

from e_graph.instrument.state import RunState


async def pre_run(state: RunState) -> str:
    """The last page, where totals live."""
    return state.context.pages[-1]
'''


class Tree:
    """A pipeline's specs and runners written under a temporary root."""

    def __init__(self, root: Path) -> None:
        self.specs, self.runners = root / "specs", root / "runners"

    def spec(self, section: str, name: str, text: str, pipeline: str = "doc") -> Path:
        return self._write(self.specs / pipeline / section / f"{name}.yaml", text)

    def runner(self, section: str, name: str, text: str, pipeline: str = "doc") -> Path:
        return self._write(self.runners / pipeline / section / f"{name}.py", text)

    def wiki(self, term: str, pipeline: str | None = None) -> Path:
        folder = self.specs / pipeline / "wiki" if pipeline else self.specs / "wiki"
        return self._write(folder / f"{term}.md", f"# {term}\n")

    def discover(self, pipeline: str = "doc", **options: Any) -> SpecDiscover:
        return SpecDiscover(pipeline, specs=self.specs, runners=self.runners, **options)

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    """A coherent `doc` pipeline: extract (one deterministic, one semantic) and classify, wiki shared."""
    built = Tree(tmp_path)
    built.spec("extract", "EXT-line-sum", SPEC_SUM)
    built.spec("extract", "EXT-total-amount", SPEC_TOTAL)
    built.spec("classify", "CLS-kind", SPEC_KIND)
    built.runner("extract", "EXT-line-sum", RUNNER_SUM)
    built.runner("extract", "EXT-total-amount", RUNNER_TOTAL)
    built.wiki("net-amount")
    return built


##### INDEX #####
def test_sections_in_walking_order_custom_last(tree: Tree) -> None:
    tree.spec("custom", "CUS-stamp", SPEC_KIND.replace("CLS-kind", "CUS-stamp"))
    (tree.runners / "doc" / "report").mkdir(parents=True)
    assert tree.discover().sections() == (Section.CLASSIFY, Section.EXTRACT, Section.REPORT, Section.CUSTOM)
    assert tree.discover().pipeline == "doc"


def test_an_unknown_pipeline_has_no_sections(tree: Tree) -> None:
    assert tree.discover("ghost").sections() == ()


##### CATALOG #####
async def test_catalog_pairs_each_spec_with_its_hooks(tree: Tree) -> None:
    catalog = await tree.discover().catalog(Section.EXTRACT)
    assert (catalog.pipeline, catalog.section, sorted(catalog.nodes)) == (
        "doc",
        Section.EXTRACT,
        ["EXT-line-sum", "EXT-total-amount"],
    )
    summed, total = catalog.nodes["EXT-line-sum"], catalog.nodes["EXT-total-amount"]
    assert isinstance(summed.spec, DeterministicSpec)
    assert isinstance(total.spec, SemanticSpec)
    assert {hook: runner.doc for hook, runner in summed.hooks.items()} == {
        Hook.RUN: "Add every line amount.",
        Hook.CHECK: "Only when lines were found.",
    }
    assert total.hooks[Hook.PRE].name == "EXT-total-amount.pre_run"
    assert summed.file.endswith("specs/doc/extract/EXT-line-sum.yaml")


async def test_a_semantic_section_needs_no_runners(tree: Tree) -> None:
    catalog = await tree.discover().catalog(Section.CLASSIFY)
    assert catalog.nodes["CLS-kind"].hooks == {}


async def test_pipeline_wiki_counts_like_the_shared_one(tree: Tree) -> None:
    (tree.specs / "wiki" / "net-amount.md").unlink()
    tree.wiki("net-amount", pipeline="doc")
    assert "EXT-total-amount" in (await tree.discover().catalog(Section.EXTRACT)).nodes


async def test_catalog_built_once_and_kept(tree: Tree, mocker: MockerFixture) -> None:
    discover = tree.discover()
    build = mocker.spy(SpecDiscover, "_catalog_build")
    first, second = await asyncio.gather(discover.catalog(Section.EXTRACT), discover.catalog(Section.EXTRACT))
    assert first is second is await discover.catalog(Section.EXTRACT)
    assert build.call_count == 1


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
    tree.spec("extract", "EXT-wrong-name", SPEC_SUM.replace("EXT-line-sum", "EXT-other"))
    tree.runner("extract", "EXT-retired", RUNNER_SUM)
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    found = {(error.rule, error.subject.rpartition("/")[2]) for error in caught.value.breaches}
    assert found == {
        (Rule.DECODE, "EXT-broken.yaml"),
        (Rule.DECODE, "EXT-bad-yaml.yaml"),
        (Rule.MERGE, "EXT-merged.yaml"),
        (Rule.FILENAME, "EXT-wrong-name"),
        (Rule.RUNNER, "EXT-wrong-name"),
        (Rule.ORPHAN, "EXT-retired"),
    }
    assert str(caught.value).startswith("doc/extract: 6 broken laws")


async def test_a_name_from_another_section_fails_decoding(tree: Tree) -> None:
    tree.spec("extract", "CLS-kind", SPEC_KIND)
    with pytest.raises(CatalogError) as caught:
        await tree.discover().catalog(Section.EXTRACT)
    (error,) = caught.value.breaches
    assert error.rule is Rule.DECODE
    assert "matching regex '^EXT-" in error.detail


async def test_a_failed_section_is_never_kept(tree: Tree) -> None:
    tree.runner("classify", "CLS-retired", RUNNER_SUM)
    discover = tree.discover()
    with pytest.raises(CatalogError):
        await discover.catalog(Section.CLASSIFY)
    (tree.runners / "doc" / "classify" / "CLS-retired.py").unlink()
    assert "CLS-kind" in (await discover.catalog(Section.CLASSIFY)).nodes


##### AUDIT #####
async def test_audit_returns_every_catalog(tree: Tree) -> None:
    assert [catalog.section for catalog in await tree.discover().audit()] == [Section.CLASSIFY, Section.EXTRACT]


async def test_audit_reports_tree_and_sections_at_once(tree: Tree) -> None:
    tree.runner("classify", "CLS-retired", RUNNER_SUM)
    (tree.specs / "doc" / "misc").mkdir()
    (tree.runners / "doc" / "extract" / "notes.txt").write_text("")
    with pytest.raises(AuditError) as caught:
        await tree.discover().audit()
    groups = {group.message.split(":")[0]: group for group in caught.value.catalogs}
    assert set(groups) == {"doc", "doc/classify"}
    assert {error.rule for error in groups["doc"].breaches} == {Rule.TREE}
    assert len(groups["doc"].breaches) == 2
    assert [error.rule for error in groups["doc/classify"].breaches] == [Rule.ORPHAN]


async def test_audit_lets_an_unexpected_failure_through(tree: Tree, mocker: MockerFixture) -> None:
    discover = tree.discover()
    mocker.patch.object(SpecDiscover, "_catalog_build", side_effect=RuntimeError("disk gone"))
    with pytest.raises(RuntimeError, match="disk gone"):
        await discover.audit()


##### LOAD #####
async def test_load_imports_a_hook_once(tree: Tree, system: State) -> None:
    discover = tree.discover()
    catalog = await discover.catalog(Section.EXTRACT)
    runner = catalog.nodes["EXT-line-sum"].hooks[Hook.RUN]
    run = await discover.load(runner)
    assert run is await discover.load(runner)
    state = RunState(system)
    state.context.lines = [1.5, 2.5]
    assert await run(state) == {"total": 4.0}
    pre = await discover.load(catalog.nodes["EXT-total-amount"].hooks[Hook.PRE])
    state.context.pages = ["cover", "totals"]
    assert await pre(state) == "totals"


async def test_load_refuses_a_file_that_is_no_source(tree: Tree, tmp_path: Path) -> None:
    runner = Runner(spec="EXT-x", hook=Hook.RUN, file=str(tmp_path / "EXT-x.txt"), doc="x")
    with pytest.raises(ImportError, match="is no Python source"):
        await tree.discover().load(runner)
