"""tests/unit: pipelines.base — the builder's contract and the registry's sweep: drop a pipeline folder, it is served."""

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from e_graph.instrument.graph import InstrumentGraph
from e_graph.models.section import Section
from e_graph.pipelines.base import PipelineBuilder, PipelineRegistry
from e_graph.pipelines.doc.graph import DocGraph
from e_graph.pipelines.note.graph import NoteGraph

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

LONE: dict[str, str] = {
    "lone/graph.py": '''
        """A one-node pipeline that nobody imported."""

        from langgraph.graph import END, START

        from dropped.pipelines.lone.nodes.ingest.node import node_ingest
        from e_graph.pipelines.base import PipelineBuilder


        class LoneGraph(PipelineBuilder):
            """Lone intake: ingest only."""

            def compose(self, graph):
                return graph.add_node(node_ingest).add_edge(START, "ingest").add_edge("ingest", END)
    ''',
    "lone/nodes/ingest/node.py": '''
        from e_graph.instrument.state import RunState


        async def node_ingest(state: RunState) -> None:
            """Take the document in."""
    ''',
    ### a graph class outside `graph.py` declares no pipeline: the sweep reads each folder's graph only.
    "lone/helpers.py": """
        from e_graph.pipelines.base import PipelineBuilder


        class StrayGraph(PipelineBuilder):
            def compose(self, graph):
                return graph
    """,
    "notes/readme.py": "",
}

TWINS: dict[str, str] = {
    "twins/graph.py": """
        from e_graph.pipelines.base import PipelineBuilder


        class OneGraph(PipelineBuilder):
            def compose(self, graph):
                return graph


        class TwoGraph(PipelineBuilder):
            def compose(self, graph):
                return graph
    """,
}


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, dict[str, str]], str]:
    """A throwaway importable `<name>.pipelines` package: `{path: source}` in, its dotted name out."""

    def make(name: str, files: dict[str, str]) -> str:
        root = tmp_path / name / "pipelines"
        for path, source in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(dedent(source))
        monkeypatch.syspath_prepend(tmp_path)
        return f"{name}.pipelines"

    return make


##### BUILDER #####
def test_builder_is_abstract() -> None:
    with pytest.raises(TypeError, match="compose"):
        PipelineBuilder()  # ty: ignore[call-non-callable] — instantiating the abstract base is the point


def test_builder_names_itself_after_its_folder() -> None:
    builder = DocGraph()
    assert builder.name == "doc"
    assert (
        builder.summary == "Document intake: ingest → (normalize ∥ classify) → extract ⇄ validate → transform → report."
    )


def test_build_returns_a_fresh_compiled_graph() -> None:
    first, second = DocGraph().build(), DocGraph().build()
    assert isinstance(first, InstrumentGraph)
    assert (first.name, first.summary) == ("doc", DocGraph().summary)
    assert first._compiled is not None
    assert first is not second


##### REGISTRY #####
async def test_registry_finds_the_concrete_builders() -> None:
    builders = await PipelineRegistry().discover()
    assert list(builders) == ["doc", "filing", "note"]
    assert type(builders["doc"]) is DocGraph


async def test_registry_builds_every_graph_by_name() -> None:
    graphs = await PipelineRegistry().build()
    assert {name: graph.name for name, graph in graphs.items()} == {"doc": "doc", "filing": "filing", "note": "note"}
    with pytest.raises(TypeError):
        graphs["other"] = graphs["doc"]  # ty: ignore[invalid-assignment]


def test_a_builder_seeds_its_graph() -> None:
    """The default seed is empty and the built graph carries what the builder declares: the canvas reads
    its run data from the listing, so the stamp at `build` is the contract."""

    class Bare(PipelineBuilder):
        def compose(self, graph):
            return graph

    class Given(PipelineBuilder):
        @property
        def seed(self):
            return {"source": "somewhere.pdf"}

        def compose(self, graph):
            return graph

    assert Bare().seed == {}
    assert Given().seed == {"source": "somewhere.pdf"}
    assert NoteGraph().build().seed == {"source": "tests/resources/documents/notes/bofa-autocall-2027.pdf"}


async def test_registry_mounts_each_pipelines_sections() -> None:
    mounts = await PipelineRegistry().mounts()
    assert mounts["filing"] == {Section.INGEST, Section.EXTRACT, Section.AUDIT, Section.REPORT}
    assert len(mounts["doc"]) == 7


async def test_a_dropped_folder_is_served_without_any_import(package: Callable[[str, dict[str, str]], str]) -> None:
    """The registry's promise: a new pipeline folder in the package is found, built and named on its own."""
    graphs = await PipelineRegistry(package("dropped", LONE)).build()
    assert list(graphs) == ["lone"]
    assert (graphs["lone"].summary, [node.id for node in graphs["lone"].topology().nodes]) == (
        "Lone intake: ingest only.",
        ["ingest"],
    )


async def test_two_graphs_in_one_pipeline_fail_naming_it(package: Callable[[str, dict[str, str]], str]) -> None:
    with pytest.raises(ValueError, match=r"\['twins'\] declare several"):
        await PipelineRegistry(package("clashing", TWINS)).discover()
