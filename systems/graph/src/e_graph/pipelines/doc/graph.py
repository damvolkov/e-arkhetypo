"""pipelines.doc.graph: the demo document pipeline — every shape the instrument draws, in one declaration.

ingest fans out to normalize ∥ classify, both join into extract, validate routes back to extract
once (the loop) and then forward through transform to report. Every node runs its section's specs
(`specs/doc/<section>/`) through the orchestrator; the work lives in the runners they plug
(`runners/owned/doc/<section>/`, `runners/agnostic/`). Copy it as the template of a real pipeline."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START

from e_graph.pipelines.base import PipelineBuilder
from e_graph.pipelines.doc.nodes.classify.node import node_classify
from e_graph.pipelines.doc.nodes.extract.node import node_extract
from e_graph.pipelines.doc.nodes.ingest.node import node_ingest
from e_graph.pipelines.doc.nodes.normalize.node import node_normalize
from e_graph.pipelines.doc.nodes.report.node import node_report
from e_graph.pipelines.doc.nodes.transform.node import node_transform
from e_graph.pipelines.doc.nodes.validate.node import node_validate, route_validate

if TYPE_CHECKING:
    from e_graph.instrument.graph import InstrumentGraph


class DocGraph(PipelineBuilder):
    """Document intake: ingest → (normalize ∥ classify) → extract ⇄ validate → transform → report."""

    __slots__ = ()

    def compose(self, graph: InstrumentGraph) -> InstrumentGraph:
        return (
            graph.add_node(node_ingest)
            .add_node(node_normalize)
            .add_node(node_classify)
            .add_sequence([node_extract, node_validate])
            .add_sequence([node_transform, node_report])
            .add_edge(START, "ingest")
            .add_edge("ingest", "normalize")
            .add_edge("ingest", "classify")
            .add_edge(["normalize", "classify"], "extract")
            .add_conditional_edges("validate", route_validate)
            .add_edge("report", END)
        )
