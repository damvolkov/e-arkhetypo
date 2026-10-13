import type { Edge, Node } from "@xyflow/react";

export type NodeStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";
export type RunStatus = "succeeded" | "failed";
export type NodeRole = "start" | "end" | "mid";
export type EdgeKind = "direct" | "conditional" | "join";

export interface PipelineInfo {
  id: string;
  summary: string;
  nodes: number;
}

export interface UiView {
  toast_ms: number;
  pace: number;
  lane_gap: number;
  rank_gap: number;
}

export interface TopologyNode {
  id: string;
  role: NodeRole;
  category: string;
  summary: string;
  rank: number;
  lane: number;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  label: string;
  loop: boolean;
}

export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  ranks: number;
  lanes: number;
}

export interface NodeOutput {
  type: "node";
  run_id: string;
  name: string;
  category: string;
  role: NodeRole;
  status: NodeStatus;
  summary: string;
  latency_ms: number;
  error: string;
  trace_id: string;
}

export interface RunEnd {
  type: "run";
  run_id: string;
  status: RunStatus;
  latency_ms: number;
  skipped: string[];
  error: string;
}

export type RunFrame = NodeOutput | RunEnd;

export interface StageData extends Record<string, unknown> {
  label: string;
  role: NodeRole;
  category: string;
  summary: string;
  status: NodeStatus;
  latency_ms?: number;
}

export interface CableData extends Record<string, unknown> {
  kind: EdgeKind;
  loop: boolean;
}

export type StageNode = Node<StageData, "stage">;
export type CableEdge = Edge<CableData>;

const API = "/api";

async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

export const listPipelines = () => read<PipelineInfo[]>("/pipelines/list");
export const fetchTopology = (id: string) => read<Topology>(`/pipelines/topology/${encodeURIComponent(id)}`);
export const fetchUi = () => read<UiView>("/ui");

export function streamRun(id: string, data: Record<string, unknown>, onFrame: (frame: RunFrame) => void): () => void {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${scheme}://${window.location.host}${API}/pipelines/stream/${encodeURIComponent(id)}`;
  const socket = new WebSocket(url);
  socket.onopen = () => socket.send(JSON.stringify({ data }));
  socket.onmessage = (event: MessageEvent<string>) => onFrame(JSON.parse(event.data));
  return () => socket.close();
}
