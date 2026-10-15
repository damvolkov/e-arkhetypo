import { Background, Panel, ReactFlow, useEdgesState, useNodesState } from "@xyflow/react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  type CableEdge,
  fetchTopology,
  type NodeOutput,
  type PipelineInfo,
  type RunFrame,
  type StageData,
  type StageNode,
  streamRun,
  type UiView,
} from "./api";
import { layout } from "./layout";
import { type Outcome, OutcomeModal } from "./outcome";
import { NODE_TYPES } from "./stage";
import { type Toast, Toasts } from "./toasts";

const TERMINAL = new Set(["succeeded", "failed"]);

function patch(node: StageNode, data: Partial<StageData>): StageNode {
  return { ...node, data: { ...node.data, ...data } };
}

export interface PipelineProps {
  ui: UiView;
  pipelines: PipelineInfo[];
  selected: string;
  setSelected: (id: string) => void;
  levels: ReactNode;
  onOpen: (pipeline: string, section: string) => void;
}

export function PipelineView({ ui, pipelines, selected, setSelected, levels, onOpen }: PipelineProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<StageNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CableEdge>([]);
  const [running, setRunning] = useState(false);
  const [fail, setFail] = useState(false);
  const [data, setData] = useState("{}");
  const [error, setError] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const close = useRef<() => void>(() => {});
  const timers = useRef(new Set<number>());
  const finals = useRef<NodeOutput[]>([]);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      close.current();
      for (const timer of pending) window.clearTimeout(timer);
    };
  }, []);

  const seedOf = useCallback(
    (id: string) => JSON.stringify(pipelines.find((pipeline) => pipeline.id === id)?.seed ?? {}),
    [pipelines],
  );

  useEffect(() => {
    if (selected === "") return;
    const stored = window.localStorage.getItem(`e-graph:data:${selected}`);
    setData(stored && stored !== "{}" ? stored : seedOf(selected));
    setError("");
    close.current();
    setOutcome(null);
    setRunning(false);
    fetchTopology(selected).then((topology) => {
      const flow = layout(topology, ui);
      setNodes(flow.nodes);
      setEdges(flow.edges);
    });
  }, [selected, ui, seedOf, setNodes, setEdges]);

  const toast = useCallback(
    (output: NodeOutput) => {
      const key = `${output.run_id}:${output.name}:${finals.current.length}`;
      setToasts((current) => [...current, { key, output }]);
      const timer = window.setTimeout(() => {
        setToasts((current) => current.filter((item) => item.key !== key));
        timers.current.delete(timer);
      }, ui.toast_ms);
      timers.current.add(timer);
    },
    [ui],
  );

  const onFrame = useCallback(
    (frame: RunFrame) => {
      if (frame.type === "node") {
        const latency = TERMINAL.has(frame.status) ? frame.latency_ms : undefined;
        setNodes((current) =>
          current.map((node) =>
            node.id === frame.name ? patch(node, { status: frame.status, latency_ms: latency }) : node,
          ),
        );
        if (TERMINAL.has(frame.status)) {
          finals.current.push(frame);
          toast(frame);
        }
        return;
      }
      const skipped = new Set(frame.skipped);
      setNodes((current) => current.map((node) => (skipped.has(node.id) ? patch(node, { status: "skipped" }) : node)));
      const closing = finals.current.findLast((output) => output.role === "end") ?? finals.current.at(-1) ?? null;
      setOutcome({ end: frame, output: closing });
      setRunning(false);
    },
    [setNodes, toast],
  );

  const seed = useCallback(
    (text: string) => {
      setData(text);
      if (selected) window.localStorage.setItem(`e-graph:data:${selected}`, text);
    },
    [selected],
  );

  const run = useCallback(() => {
    let seeded: Record<string, unknown>;
    try {
      seeded = JSON.parse(data);
    } catch (failure) {
      setError(`data is no JSON: ${(failure as Error).message}`);
      return;
    }
    const expected = pipelines.find((pipeline) => pipeline.id === selected)?.seed ?? {};
    const missing = Object.keys(expected).filter((key) => !(key in seeded));
    if (missing.length) {
      setError(`data lacks ${missing.join(", ")}: this pipeline runs on ${JSON.stringify(expected)}`);
      return;
    }
    window.localStorage.setItem(`e-graph:data:${selected}`, data);
    setError("");
    close.current();
    finals.current = [];
    setOutcome(null);
    setToasts([]);
    setRunning(true);
    setNodes((current) => current.map((node) => patch(node, { status: "pending", latency_ms: undefined })));
    close.current = streamRun(selected, { pace: ui.pace, ...seeded, fail }, onFrame);
  }, [selected, ui, fail, data, pipelines, onFrame, setNodes]);

  const status = new Map(nodes.map((node) => [node.id, node.data.status]));
  const lit = edges.map((edge) => ({ ...edge, className: `cable cable-${status.get(edge.source) ?? "pending"}` }));
  const summary = pipelines.find((pipeline) => pipeline.id === selected)?.summary ?? "";

  return (
    <ReactFlow
      nodes={nodes}
      edges={lit}
      nodeTypes={NODE_TYPES}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeDoubleClick={(_, node) => node.data.category && onOpen(selected, node.data.category)}
      nodesConnectable={false}
      nodeOrigin={[0.5, 0.5]}
      colorMode="dark"
      fitView
      fitViewOptions={{ padding: 0.3 }}
      key={selected}
    >
      <Background gap={24} size={1} />
      <Panel position="top-left" className="panel">
        {levels}
        <label className="field">
          pipeline
          <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={running}>
            {pipelines.map((pipeline) => (
              <option key={pipeline.id} value={pipeline.id}>
                {pipeline.id}
              </option>
            ))}
          </select>
        </label>
        <div className="pipeline-summary">{summary}</div>
        <label className="data">
          data
          <textarea
            value={data}
            onChange={(event) => seed(event.target.value)}
            rows={2}
            spellCheck={false}
            placeholder={seedOf(selected)}
          />
        </label>
        <button type="button" onClick={run} disabled={running || selected === ""}>
          {running ? "running…" : "run"}
        </button>
        <label>
          <input type="checkbox" checked={fail} onChange={(event) => setFail(event.target.checked)} /> inject failure
        </label>
        {error && <div className="panel-error">{error}</div>}
      </Panel>
      <Toasts toasts={toasts} />
      {outcome && <OutcomeModal outcome={outcome} onClose={() => setOutcome(null)} />}
    </ReactFlow>
  );
}
