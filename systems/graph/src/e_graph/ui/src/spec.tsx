import { Handle, type NodeProps, type NodeTypes, Position } from "@xyflow/react";
import type { CallNode, SpecNode } from "./api";

function Spec({ data }: NodeProps<SpecNode>) {
  const { point, status, latency_ms } = data;
  const tier = point.tier ? ` · ${point.tier}` : "";
  return (
    <div
      className={`spec kind-${point.kind} status-${status}${point.rescues ? " spec-fallback" : ""}`}
      title={point.description}
    >
      <Handle id="in" type="target" position={Position.Top} />
      <Handle id="side-in" type="target" position={Position.Left} />
      <div className="stage-label">{point.id}</div>
      <div className="spec-kind">
        {point.kind}
        {tier}
        {point.rescues && ` · fallback of ${point.rescues}`}
      </div>
      <ul className="spec-runners">
        {Object.entries(point.runners).map(([slot, ref]) => (
          <li key={slot}>
            <span className="spec-slot">{slot}</span> {ref}
          </li>
        ))}
      </ul>
      {latency_ms !== undefined && <div className="stage-meta">{latency_ms.toFixed(1)} ms</div>}
      <Handle id="side-out" type="source" position={Position.Right} />
      <Handle id="out" type="source" position={Position.Bottom} />
    </div>
  );
}

function Call({ data }: NodeProps<CallNode>) {
  const { group, width, height } = data;
  return (
    <div className="call" style={{ width, height }}>
      <span className="call-label">
        call-{group.index} · {group.tier} · ~{group.weight}/{group.budget} tokens
      </span>
    </div>
  );
}

export const SPEC_TYPES: NodeTypes = { spec: Spec, call: Call };
