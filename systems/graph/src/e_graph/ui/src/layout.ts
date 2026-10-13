import type { CableEdge, StageNode, Topology, UiView } from "./api";

export function layout(topology: Topology, ui: UiView): { nodes: StageNode[]; edges: CableEdge[] } {
  const widths = new Map<number, number>();
  for (const node of topology.nodes) widths.set(node.rank, (widths.get(node.rank) ?? 0) + 1);
  const nodes: StageNode[] = topology.nodes.map((node) => ({
    id: node.id,
    type: "stage",
    position: {
      x: (node.lane - ((widths.get(node.rank) ?? 1) - 1) / 2) * ui.lane_gap,
      y: node.rank * ui.rank_gap,
    },
    data: { label: node.id, role: node.role, category: node.category, summary: node.summary, status: "pending" },
  }));
  const edges: CableEdge[] = topology.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label || undefined,
    animated: true,
    data: { kind: edge.kind, loop: edge.loop },
    ...(edge.loop
      ? { type: "smoothstep", sourceHandle: "loop-out", targetHandle: "loop-in" }
      : { sourceHandle: "out", targetHandle: "in" }),
  }));
  return { nodes, edges };
}
