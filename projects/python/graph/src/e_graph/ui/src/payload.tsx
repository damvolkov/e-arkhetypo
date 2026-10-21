import { useState } from "react";
import type { AgentCall, Route, SpecOutcome, SpecPoint } from "./api";

const PARTS = ["instructions", "prompt", "schema"] as const;
type Part = (typeof PARTS)[number];

function json(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function Card({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="card" role="dialog" aria-label={title}>
      <div className="outcome-head">
        <span>{title}</span>
        <button type="button" className="outcome-close" onClick={onClose} aria-label="close">
          ×
        </button>
      </div>
      {children}
    </div>
  );
}

export function SpecCard({
  point,
  outcome,
  written,
  onClose,
}: {
  point: SpecPoint;
  outcome?: SpecOutcome;
  written?: unknown;
  onClose: () => void;
}) {
  return (
    <Card title={point.id} onClose={onClose}>
      <p className="card-text">{point.description}</p>
      <dl className="outcome-output">
        <dt>kind</dt>
        <dd>
          {point.kind}
          {point.tier && ` · ${point.tier} · call-${point.call}`}
        </dd>
        {Object.entries(point.runners).map(([slot, ref]) => [
          <dt key={`${slot}-t`}>{slot}</dt>,
          <dd key={`${slot}-d`}>{ref}</dd>,
        ])}
        {point.wiki.length > 0 && (
          <>
            <dt>wiki</dt>
            <dd>{point.wiki.join(", ")}</dd>
          </>
        )}
        {outcome && (
          <>
            <dt>status</dt>
            <dd className={`status-text-${outcome.status}`}>
              {outcome.status}
              {outcome.rescuer && ` by ${outcome.rescuer}`}
            </dd>
            {(outcome.error || outcome.reason) && (
              <>
                <dt>why</dt>
                <dd>{outcome.error || outcome.reason}</dd>
              </>
            )}
          </>
        )}
      </dl>
      <div className="card-title">{written === undefined ? "output schema" : "written"}</div>
      <pre className="card-pre">{json(written === undefined ? point.output : written)}</pre>
    </Card>
  );
}

export function CallCard({ call, route, onClose }: { call: AgentCall; route?: Route; onClose: () => void }) {
  const [part, setPart] = useState<Part>("prompt");
  const text = { instructions: call.instructions, prompt: call.prompt, schema: json(call.schema) }[part];
  const target = route === undefined ? "" : route.error || `${route.provider}/${route.model} ${route.api_base}`;
  return (
    <Card title={`call-${call.index}`} onClose={onClose}>
      <dl className="outcome-output">
        <dt>tier</dt>
        <dd>
          {call.tier} · step {call.step}
        </dd>
        <dt>route</dt>
        <dd>{target}</dd>
        <dt>specs</dt>
        <dd>
          {Object.entries(call.weights)
            .map(([name, weight]) => `${name} ~${weight}`)
            .join(" · ")}{" "}
          <span className="stage-meta">of {call.budget}</span>
        </dd>
      </dl>
      <div className="tabs" role="tablist">
        {PARTS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={part === name}
            className={part === name ? "tab tab-on" : "tab"}
            onClick={() => setPart(name)}
          >
            {name}
          </button>
        ))}
        <span className="stage-meta">{text.length} chars</span>
      </div>
      <pre className="card-pre card-payload">{text}</pre>
    </Card>
  );
}
