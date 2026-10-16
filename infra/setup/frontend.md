# frontend — pnpm checks and visual snapshots

`ui` needs nothing: pnpm and node come from the pinned actions and the lockfile decides the rest.
The `snapshots` job installs a browser and runs `pytest -m ui` against the bundled site — enable it
where you want the visual gate:

    gh variable set UI_SNAPSHOTS --body true

Accepted snapshot images live in `tests/acceptance/snapshots`; regenerate them on a workstation
(`make snap`) and commit — the CI never rewrites its own ground truth.
