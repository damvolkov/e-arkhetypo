import { Handle, type NodeProps, type NodeTypes, Position } from "@xyflow/react";
import type { StageNode } from "./api";

const MARKS = { start: "▶ ", end: "■ ", mid: "" } as const;

function Stage({ data }: NodeProps<StageNode>) {
  const latency = data.latency_ms === undefined ? "" : `${data.latency_ms.toFixed(1)} ms`;
  return (
    <div className={`stage role-${data.role} status-${data.status}`} title={data.summary}>
      <Handle id="in" type="target" position={Position.Top} />
      <Handle id="loop-in" type="target" position={Position.Right} />
      <div className="stage-label">
        {MARKS[data.role]}
        {data.label}
      </div>
      {data.category !== data.label && <div className="stage-meta">{data.category}</div>}
      {latency && <div className="stage-meta">{latency}</div>}
      <Handle id="loop-out" type="source" position={Position.Right} />
      <Handle id="out" type="source" position={Position.Bottom} />
    </div>
  );
}

export const NODE_TYPES: NodeTypes = { stage: Stage };
