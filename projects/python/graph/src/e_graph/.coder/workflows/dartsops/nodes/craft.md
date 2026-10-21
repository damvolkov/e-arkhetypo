# craft — actor: coder

Apply the diagnose plan on a fresh branch `dartsops/<pipeline>-<n>`:

```
git switch -c dartsops/<pipeline>-<n>
```

Allowed to change: `src/e_graph/specs/<pipeline>/**`, `runners/owned/<pipeline>/**`,
`runners/agnostic/**` and their mirror tests. The whole taxonomy law applies (`docs/darts.md`,
`e-graph darts contract`): one function per runner with its role signature and docstring, args only
for plugged slots, one-word module names, no relative imports, fallbacks stay leaves.

Forbidden, absolutely: editing a spec's `output` toward looseness (dropping `required`, `additionalProperties`,
`min`/`max`, `maxLength`, `maxItems`) to make a signal shut up; editing tests or expectations that were green;
touching the engine (`logic/`, `instrument/`, `api/`, `models/`); `--snapshot-update` on canvas PNGs;
force-push; merging. A semantic string field may only grow bounds through a new `infra`-clean gate run.

If the fix is a runner an `agnostic` tool deserves, promote it with its unit tests mirroring its path.
Commit once per logical change, message: `fix(graph)[dartsops]: <signal> — <what and why>`.

Return `{branch, diff: [files], committed: true}`.
