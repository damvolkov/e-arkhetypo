# gate — actor: null, then actor: coder

Run the gates in order, deterministic first:

```
make dartsops-gate PIPELINE=<pipeline>
uv run e-graph darts evaluate <pipeline> --data <seed> --expect "<each expectation>" --out signal-next.json
```

The first command owes: laws clean (`darts check`, no errors, no new warnings), the section's plan pinned,
the pipeline's unit tests, the taxonomy check. The second owes a **readout with no signals**. Two readouts
with the same failing signal mean the loop cannot close this cause: stop the loop and hand over —
`{stall: true, why, to: "human: <command or file to look at>"}`.

Return `{green: bool, failing: [signal…], evidence: "signal-next.json"}`.
