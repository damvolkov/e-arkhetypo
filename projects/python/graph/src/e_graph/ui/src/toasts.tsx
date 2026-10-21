import type { NodeOutput } from "./api";

export interface Toast {
  key: string;
  output: NodeOutput;
}

export function Toasts({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toasts">
      {toasts.map(({ key, output }) => (
        <div key={key} className={`toast status-${output.status}`}>
          <div className="toast-head">
            <span className="stage-label">{output.name}</span>
            <span className="stage-meta">{output.latency_ms.toFixed(1)} ms</span>
          </div>
          <div className="toast-body">{output.error || output.summary}</div>
        </div>
      ))}
    </div>
  );
}
