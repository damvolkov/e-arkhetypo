"""tests/unit: pipelines.base — the builder's contract and the registry's sweep: drop a module, it is served."""

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from e_graph.instrument.graph import InstrumentGraph
from e_graph.pipelines.base import PipelineBuilder, PipelineRegistry
from e_graph.pipelines.doc import DocBuilder

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

LONE: str = '''
    """A one-node pipeline that nobody imported."""

    from langgraph.graph import END, START

    from e_graph.nodes.ingest.node import node_ingest
    from e_graph.pipelines.base import PipelineBuilder


    class LoneBuilder(PipelineBuilder):
        """Lone intake: ingest only."""

        def compose(self, graph):
            return graph.add_node(node_ingest).add_edge(START, "ingest").add_edge("ingest", END)
'''

TWINS: str = """
    from e_graph.pipelines.base import PipelineBuilder


    class OneBuilder(PipelineBuilder):
        def compose(self, graph):
            return graph


    class TwoBuilder(PipelineBuilder):
        def compose(self, graph):
            return graph
"""


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, dict[str, str]], str]:
    """A throwaway importable package of builder modules: `{module: source}` in, its dotted name out."""

    def make(name: str, modules: dict[str, str]) -> str:
        root = tmp_path / name
        root.mkdir()
        for module, source in modules.items():
            (root / f"{module}.py").write_text(dedent(source))
        monkeypatch.syspath_prepend(tmp_path)
        return name

    return make


##### BUILDER #####
def test_builder_is_abstract() -> None:
    with pytest.raises(TypeError, match="compose"):
        PipelineBuilder()  # ty: ignore[call-non-callable] — instantiating the abstract base is the point


def test_builder_names_itself_after_its_module() -> None:
    builder = DocBuilder()
    assert builder.name == "doc"
    assert (
        builder.summary == "Document intake: ingest → (normalize ∥ classify) → extract ⇄ validate → transform → report."
    )


def test_build_returns_a_fresh_compiled_graph() -> None:
    first, second = DocBuilder().build(), DocBuilder().build()
    assert isinstance(first, InstrumentGraph)
    assert (first.name, first.summary) == ("doc", DocBuilder().summary)
    assert first._compiled is not None
    assert first is not second


##### REGISTRY #####
async def test_registry_finds_the_concrete_builders() -> None:
    builders = await PipelineRegistry().discover()
    assert list(builders) == ["doc"]
    assert type(builders["doc"]) is DocBuilder


async def test_registry_builds_every_graph_by_name() -> None:
    graphs = await PipelineRegistry().build()
    assert {name: graph.name for name, graph in graphs.items()} == {"doc": "doc"}
    with pytest.raises(TypeError):
        graphs["other"] = graphs["doc"]  # ty: ignore[invalid-assignment]


async def test_a_dropped_module_is_served_without_any_import(package: Callable[[str, dict[str, str]], str]) -> None:
    """The registry's promise: a new builder module in the package is found, built and named on its own."""
    graphs = await PipelineRegistry(package("dropped", {"lone": LONE})).build()
    assert list(graphs) == ["lone"]
    assert (graphs["lone"].summary, [node.id for node in graphs["lone"].topology().nodes]) == (
        "Lone intake: ingest only.",
        ["ingest"],
    )


async def test_two_builders_in_one_module_fail_naming_it(package: Callable[[str, dict[str, str]], str]) -> None:
    with pytest.raises(ValueError, match=r"\['twins'\] declare several"):
        await PipelineRegistry(package("clashing", {"twins": TWINS})).discover()
