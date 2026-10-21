import type {
  CableEdge,
  CallNode,
  LinkEdge,
  SectionMap,
  SpecNode,
  SpecPoint,
  StageNode,
  Topology,
  UiView,
} from "./api";

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

const SPEC_W = 230;
const SPEC_H = 112;
const CALL_PAD = 24;
const CALL_HEAD = 30;

export function specLayout(map: SectionMap, ui: UiView): { nodes: (SpecNode | CallNode)[]; edges: LinkEdge[] } {
  const laneGap = Math.max(ui.lane_gap, SPEC_W + 50);
  const rankGap = Math.max(ui.rank_gap, SPEC_H + CALL_HEAD + 80);
  const widths = new Map<number, number>();
  for (const point of map.nodes) widths.set(point.rank, (widths.get(point.rank) ?? 0) + 1);
  const x = (point: SpecPoint) => (point.lane - ((widths.get(point.rank) ?? 1) - 1) / 2) * laneGap;
  const specs: SpecNode[] = map.nodes.map((point) => ({
    id: point.id,
    type: "spec",
    position: { x: x(point), y: point.rank * rankGap },
    data: { point, status: "pending" },
  }));
  const placed = new Map(map.nodes.map((point) => [point.id, point]));
  const calls: CallNode[] = map.calls.map((group) => {
    const xs = group.specs.map((name) => x(placed.get(name) as SpecPoint));
    const left = Math.min(...xs);
    const right = Math.max(...xs);
    const width = right - left + SPEC_W + 2 * CALL_PAD;
    const height = SPEC_H + CALL_HEAD + 2 * CALL_PAD;
    return {
      id: `call-${group.index}`,
      type: "call",
      position: { x: (left + right) / 2, y: group.rank * rankGap - CALL_HEAD / 2 },
      data: { group, width, height },
      zIndex: -1,
      draggable: false,
    };
  });
  const edges: LinkEdge[] = map.edges.map((link) => ({
    id: link.id,
    source: link.source,
    target: link.target,
    data: { kind: link.kind },
    className: `link link-${link.kind}`,
    animated: link.kind === "depends",
    ...(link.kind === "fallback"
      ? { type: "smoothstep", sourceHandle: "side-out", targetHandle: "side-in", label: "fallback" }
      : { sourceHandle: "out", targetHandle: "in" }),
  }));
  return { nodes: [...calls, ...specs], edges };
}
