# report — actor: coder

Close the run with evidence, never with prose alone. Open a PR from the craft branch:

```
git push -u origin dartsops/<pipeline>-<n> && gh pr create -t "fix(graph)[dartsops]: <pipeline> — <signals>" -b "<before/after readouts, the diagnose chain, the gate output>"
```

Body: the intake signals, which reproduced, the cause per layer, what changed and why it is the
smallest fix, the gate's green tail, and the final clean readout. If the loop stalled, no PR: the report
is the handover note naming the command that continues the run.

Return `{green, signals_left, branch, pr}`.
