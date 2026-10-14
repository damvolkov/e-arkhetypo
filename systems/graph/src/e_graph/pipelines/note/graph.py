"""pipelines.note.graph: a structured note read into one term sheet — ingest → extract → inference → audit → report.

The pricing supplement of an autocallable is read hybrid (liteparse everywhere, docling on its table
pages): identifiers, money, fees and the date schedule come out of the text by regex and table parsing —
with a semantic rescue when a regex misses — while the terms, the payoff, the classification and the
plain-language brief come from the agent, fused per tier. Derived numbers (term, coupon, drag, ladder,
scenarios) are computed, not read; every fact is then held to its own standard — check digits, calendar
order, the levels' order — and the prose to the term sheet."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START

from e_graph.pipelines.base import PipelineBuilder
from e_graph.pipelines.note.nodes.audit.node import node_audit
from e_graph.pipelines.note.nodes.extract.node import node_extract
from e_graph.pipelines.note.nodes.inference.node import node_inference
from e_graph.pipelines.note.nodes.ingest.node import node_ingest
from e_graph.pipelines.note.nodes.report.node import node_report

if TYPE_CHECKING:
    from e_graph.instrument.graph import InstrumentGraph


class NoteGraph(PipelineBuilder):
    """A 424B2 read into its term sheet: ingest → extract → inference → audit → report."""

    __slots__ = ()

    def compose(self, graph: InstrumentGraph) -> InstrumentGraph:
        return (
            graph.add_sequence([node_ingest, node_extract, node_inference, node_audit, node_report])
            .add_edge(START, "ingest")
            .add_edge("report", END)
        )
