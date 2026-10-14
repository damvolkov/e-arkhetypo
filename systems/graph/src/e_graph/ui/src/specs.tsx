import { Background, Panel, ReactFlow, useEdgesState, useNodesState } from "@xyflow/react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  type CallNode,
  fetchSectionMap,
  type LinkEdge,
  type SectionInfo,
  type SectionMap,
  type Simulation,
  type SpecNode,
  simulate,
  svgUrl,
  type UiView,
} from "./api";
import { specLayout } from "./layout";
import { CallCard, SpecCard } from "./payload";
import { SPEC_TYPES } from "./spec";

type Open = { kind: "spec"; id: string } | { kind: "call"; index: number } | null;

const remembered = (pipeline: string) => window.localStorage.getItem(`e-graph:data:${pipeline}`) ?? "{}";

export interface SpecsProps {
  ui: UiView;
  sections: SectionInfo[];
  pipeline: string;
  section: string;
  onPick: (pipeline: string, section: string) => void;
  levels: ReactNode;
}

export function SpecsView({ ui, sections, pipeline, section, onPick, levels }: SpecsProps) {
  const [map, setMap] = useState<SectionMap | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<SpecNode | CallNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<LinkEdge>([]);
  const [data, setData] = useState(() => remembered(pipeline));
  const [live, setLive] = useState(false);
  const [running, setRunning] = useState(false);
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Open>(null);

  useEffect(() => {
    if (pipeline === "" || section === "") return;
    setSimulation(null);
    setOpen(null);
    setError("");
    setData(remembered(pipeline));
    fetchSectionMap(pipeline, section)
      .then((found) => {
        const flow = specLayout(found, ui);
        setMap(found);
        setNodes(flow.nodes);
        setEdges(flow.edges);
      })
      .catch((failure: Error) => setError(failure.message));
  }, [pipeline, section, ui, setNodes, setEdges]);

  const rehearse = useCallback(() => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(data);
    } catch (failure) {
      setError(`data is no JSON: ${(failure as Error).message}`);
      return;
    }
    window.localStorage.setItem(`e-graph:data:${pipeline}`, data);
    setRunning(true);
    setError("");
    setOpen(null);
    simulate(pipeline, section, parsed, live)
      .then((found) => {
        setSimulation(found);
        const outcomes = new Map((found.runs.at(-1)?.outcomes ?? []).map((outcome) => [outcome.spec, outcome]));
        setNodes((current) =>
          current.map((node) => {
            const outcome = outcomes.get(node.id);
            return node.type === "spec" && outcome
              ? { ...node, data: { ...node.data, status: outcome.status, latency_ms: outcome.latency_ms } }
              : node;
          }),
        );
      })
      .catch((failure: Error) => setError(failure.message))
      .finally(() => setRunning(false));
  }, [data, live, pipeline, section, setNodes]);

  const target = simulation?.runs.at(-1);
  const point = open?.kind === "spec" ? map?.nodes.find((found) => found.id === open.id) : undefined;
  const call = open?.kind === "call" ? simulation?.calls.find((found) => found.index === open.index) : undefined;
  const pipelines = [...new Set(sections.map((found) => found.pipeline))];
  const mounted = sections.filter((found) => found.pipeline === pipeline);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={SPEC_TYPES}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, node) =>
        setOpen(
          node.type === "spec" ? { kind: "spec", id: node.id } : { kind: "call", index: Number(node.id.slice(5)) },
        )
      }
      nodesConnectable={false}
      nodeOrigin={[0.5, 0.5]}
      colorMode="dark"
      fitView
      fitViewOptions={{ padding: 0.3 }}
      key={`${pipeline}/${section}/${map?.nodes.length ?? 0}`}
    >
      <Background gap={24} size={1} />
      <Panel position="top-left" className="panel">
        {levels}
        <label className="field">
          pipeline
          <select
            value={pipeline}
            onChange={(event) => onPick(event.target.value, "")}
            disabled={running}
            aria-label="spec pipeline"
          >
            {pipelines.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          section
          <select value={section} onChange={(event) => onPick(pipeline, event.target.value)} disabled={running}>
            {mounted.map((found) => (
              <option key={found.section} value={found.section}>
                {found.section} · {found.specs}
              </option>
            ))}
          </select>
        </label>
        <div className="pipeline-summary">
          {map && `${map.nodes.length} specs · ${map.ranks} steps · ${map.calls.length} agent calls planned`}{" "}
          <a href={svgUrl(pipeline, section)} target="_blank" rel="noreferrer">
            svg
          </a>
        </div>
        <label className="data">
          data
          <textarea value={data} onChange={(event) => setData(event.target.value)} rows={3} spellCheck={false} />
        </label>
        <button type="button" onClick={rehearse} disabled={running || section === ""}>
          {running ? "simulating…" : "simulate"}
        </button>
        <label>
          <input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} /> live model
        </label>
        {error && <div className="panel-error">{error}</div>}
        {simulation && (
          <div className="runs">
            {simulation.runs.map((run) => (
              <div key={run.section} className="stage-meta">
                {run.section}: {run.outcomes.length} specs · {run.latency_ms.toFixed(0)} ms
              </div>
            ))}
            {simulation.calls.map((found) => (
              <button
                type="button"
                key={found.index}
                className="call-chip"
                onClick={() => setOpen({ kind: "call", index: found.index })}
              >
                call-{found.index} · {found.tier} · {found.prompt.length} chars
              </button>
            ))}
          </div>
        )}
      </Panel>
      {point && (
        <SpecCard
          point={point}
          outcome={target?.outcomes.find((outcome) => outcome.spec === point.id)}
          written={simulation?.written[point.id]}
          onClose={() => setOpen(null)}
        />
      )}
      {open?.kind === "call" && call && (
        <CallCard call={call} route={simulation?.routes[call.tier]} onClose={() => setOpen(null)} />
      )}
      {open?.kind === "call" && !call && (
        <div className="card" role="dialog" aria-label="planned call">
          <p className="card-text">
            Simulate to read this call's payload: the material its specs' pre runners prepare.
          </p>
        </div>
      )}
    </ReactFlow>
  );
}
