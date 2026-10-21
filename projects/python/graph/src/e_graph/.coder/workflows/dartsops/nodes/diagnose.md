# diagnose — actor: coder

For each reproduced signal, name the broken layer before touching it, in this escalation order —
the cheapest explanation first:

1. **infra**: a tier timed out or refused. Not yours: return `{stall: true, to: "human", why}` and end the run.
2. **pages/material**: the `pre` args (titles, words, first, most) selected no page or the wrong one.
3. **pattern**: a deterministic `run` (match/table) missed what the document now prints.
4. **schema**: the output was too loose (a wrong answer passed) or too tight (a right one failed).
5. **instructions**: the semantic brief does not say what the document says.
6. **the spec's shape**: depends/fallback/tier mis-set — consult `e-graph darts contract`.
7. **the truth**: only after 1–6 are clean, and only with the document page cited; truth edits are a
   separate commit, never mixed with a patch.

Open the evidence, not guesses: the failing spec YAML, its runner, the readout, and `e-graph lab graph`
for the section. Return `{cause: [signal→layer…], plan: [file→change…], smallest: true}` — the plan must
touch the smallest surface that makes every signal speak no more.
