import type { NodeOutput, RunEnd } from "./api";

export interface Outcome {
  end: RunEnd;
  output: NodeOutput | null;
}

export function OutcomeModal({ outcome, onClose }: { outcome: Outcome; onClose: () => void }) {
  const { end, output } = outcome;
  return (
    <div className={`outcome status-${end.status}`} role="dialog" aria-label="run outcome">
      <div className="outcome-head">
        <span>
          <span className={`verdict status-text-${end.status}`}>{end.status}</span>{" "}
          <span className="stage-meta">{end.latency_ms.toFixed(0)} ms</span>
        </span>
        <button type="button" className="outcome-close" onClick={onClose} aria-label="close">
          ×
        </button>
      </div>
      {output && (
        <dl className="outcome-output">
          <dt>node</dt>
          <dd>
            {output.name} <span className="role-chip">{output.role}</span>
          </dd>
          <dt>status</dt>
          <dd className={`status-text-${output.status}`}>{output.status}</dd>
          <dt>{output.error ? "error" : "summary"}</dt>
          <dd>{output.error || output.summary}</dd>
          <dt>latency</dt>
          <dd className="stage-meta">{output.latency_ms.toFixed(1)} ms</dd>
          <dt>trace</dt>
          <dd className="stage-meta">{output.trace_id}</dd>
        </dl>
      )}
      {end.skipped.length > 0 && <div className="outcome-foot">skipped: {end.skipped.join(", ")}</div>}
    </div>
  );
}
