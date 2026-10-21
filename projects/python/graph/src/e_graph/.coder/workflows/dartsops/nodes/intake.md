# intake — actor: null (deterministic)

Validate the signal before believing it: it must be a `Readout` JSON (mode, summaries, signals) or
a query written to one with `e-graph darts evaluate … --out signal.json`. Refuse a signal whose
`mode` is `infra` — an unanswered tier is not a misread spec, it is the machine: stop and return
`{skipped: true, why: "infra"}` so nobody patches a healthy system for a hung server.

Return `{accepted: true, signals: [kind, where, detail…], pipeline}` — one entry per signal, in order.
