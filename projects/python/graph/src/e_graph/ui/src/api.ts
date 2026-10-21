import type { Edge, Node } from "@xyflow/react";

export type NodeStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";
export type RunStatus = "succeeded" | "failed";
export type NodeRole = "start" | "end" | "mid";
export type EdgeKind = "direct" | "conditional" | "join";

export interface PipelineInfo {
  id: string;
  summary: string;
  nodes: number;
  seed: Record<string, unknown>;
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

export type Slot = "runner" | "check" | "pre" | "post";
export type LinkKind = "depends" | "fallback";
export type SpecStatus = "pending" | "succeeded" | "rescued" | "failed" | "blocked" | "skipped";

export interface SectionInfo {
  pipeline: string;
  section: string;
  specs: number;
  steps: number;
  calls: number;
}

export interface SpecPoint {
  id: string;
  kind: "deterministic" | "semantic";
  description: string;
  rank: number;
  lane: number;
  tier: string;
  call: number;
  rescues: string;
  runners: Partial<Record<Slot, string>>;
  wiki: string[];
  output: Record<string, unknown>;
}

export interface SpecLink {
  id: string;
  source: string;
  target: string;
  kind: LinkKind;
}

export interface CallGroup {
  index: number;
  rank: number;
  tier: string;
  specs: string[];
  weight: number;
  budget: number;
}

export interface SectionMap {
  pipeline: string;
  section: string;
  nodes: SpecPoint[];
  edges: SpecLink[];
  calls: CallGroup[];
  ranks: number;
  lanes: number;
}

export interface AgentCall {
  index: number;
  step: number;
  tier: string;
  specs: string[];
  instructions: string;
  prompt: string;
  schema: Record<string, unknown>;
  weights: Record<string, number>;
  budget: number;
}

export interface SpecOutcome {
  spec: string;
  kind: string;
  step: number;
  status: Exclude<SpecStatus, "pending">;
  latency_ms: number;
  reason: string;
  error: string;
  rescuer: string;
  call: number;
}

export interface SectionRun {
  pipeline: string;
  section: string;
  outcomes: SpecOutcome[];
  latency_ms: number;
  calls: AgentCall[];
}

export interface Route {
  provider: string;
  model: string;
  api_base: string;
  error: string;
}

export interface Simulation {
  pipeline: string;
  section: string;
  live: boolean;
  runs: SectionRun[];
  calls: AgentCall[];
  routes: Record<string, Route>;
  written: Record<string, unknown>;
  latency_ms: number;
}

export interface SpecData extends Record<string, unknown> {
  point: SpecPoint;
  status: SpecStatus;
  latency_ms?: number;
}

export interface CallData extends Record<string, unknown> {
  group: CallGroup;
  width: number;
  height: number;
}

export type SpecNode = Node<SpecData, "spec">;
export type CallNode = Node<CallData, "call">;
export type LinkEdge = Edge<{ kind: LinkKind }>;

async function send<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
  return response.json();
}

const at = (pipeline: string, section: string) => `${encodeURIComponent(pipeline)}/${encodeURIComponent(section)}`;

export const listSections = () => read<SectionInfo[]>("/specs/list");
export const fetchSectionMap = (pipeline: string, section: string) =>
  read<SectionMap>(`/specs/topology/${at(pipeline, section)}`);
export const svgUrl = (pipeline: string, section: string) => `${API}/specs/svg/${at(pipeline, section)}`;
export const simulate = (pipeline: string, section: string, data: Record<string, unknown>, live: boolean) =>
  send<Simulation>(`/specs/simulate/${at(pipeline, section)}`, { data, live });
