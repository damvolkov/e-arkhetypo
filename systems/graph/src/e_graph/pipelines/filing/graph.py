"""pipelines.filing.graph: a 10-K read into its facts — ingest → extract → audit → report.

The filing is read hybrid (liteparse on every page, docling on the pages that need it); the agent reads
the cover and both statements in one fused call, each spec fed only the pages its titles point to; the
figures are brought to dollars, held to the statements' identities, and gathered in one record."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START

from e_graph.pipelines.base import PipelineBuilder
from e_graph.pipelines.filing.nodes.audit.node import node_audit
from e_graph.pipelines.filing.nodes.extract.node import node_extract
from e_graph.pipelines.filing.nodes.ingest.node import node_ingest
from e_graph.pipelines.filing.nodes.report.node import node_report

if TYPE_CHECKING:
    from e_graph.instrument.graph import InstrumentGraph


class FilingGraph(PipelineBuilder):
    """A 10-K read into its facts: ingest → extract → audit → report."""

    __slots__ = ()

    def compose(self, graph: InstrumentGraph) -> InstrumentGraph:
        return (
            graph.add_sequence([node_ingest, node_extract, node_audit, node_report])
            .add_edge(START, "ingest")
            .add_edge("report", END)
        )
