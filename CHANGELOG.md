# Changelog

Maintenance record of this repository: every sync, bump and repair, filed under the area it
touches — `stack`, `systems`, `infra`. Lines under `[Unreleased]` are written by the bots
(`tools/changelog.py`) and by humans alike; cutting a release moves them under a version heading.

## [Unreleased]

### stack

- floating tags resolved to current digests (`stack/resolve-2026-10-20`)
- `storage/minio` parked: `stack.parked: "true"` — the image died upstream with MinIO's OSS, the service is off on the host and the version bots stop probing it until removal

### projects

- core: wall-clock benchmarks marked `slow` and out of `test`/`cov` by default (`TESTARGS`) — a cold runner hiccup is not a correctness gate
- graph: visual goldens leave `test`/`cov` (`TESTARGS` default `-m 'not ui'`) — they are runner-canonical now

### infra

- **e-templates → e-arkhetypo**: a data-only repo — project blueprints, stacks, CI sources. `systems/` → `projects/python/` (`projects/rust/` reserved), area `systems` → `projects` (`area:projects`, `sync-projects`, `### projects`); `management/` leaves for e-taxis, its registry stays as `projects/templates.yml`. `repo-gates` now materializes every project and runs each one's `core-check`/`common-check` plus pinned zizmor; the repo's own `sync-infra` is retired (its fragment waits for e-taxis) and Renovate's `github-actions` manager bumps every committed `.github/` with `infra/` in one PR
- `maintenance` discards a compose file whose `image:` line moved; the agent CLI pinned to `@qwen-code/qwen-code` 0.25.3, tracked by Renovate (npm); dead labels `upstream-update`/`binding-update` dropped from the contract
- one shared GitHub App, `self-maintenance`, for every repo: `selfmaintain.md` and `repo-maintain.md` cut to the user's five steps (`bootstrap-repos {{repo}}`, Renovate, merge, Free-plan protection note), the per-repo App guides moved to `infra/setup/deprecated/`; the app's contract (names, permissions, rotation) in `infra/README.md`. Setup docs now take project tokens (`{{repo}}` = `damvolkov/<brand>`); `e_management gen` prints what a credential-holding feature needs by hand; `image` no longer lists the built-in `GITHUB_TOKEN` as a secret
- new feature `snap-refresh`: a dispatch regenerates one system's goldens on the runner and PRs the pixels; `gh pr create --head` fixed in the bot PR openers
- setup-uv step in `sync-stack`, `health-areas` and `upstream-context-repo`: bare `uv run --no-project` died 127 on runners without it
- setup docs for dummies: `selfmaintain.md` and `repo-maintain.md` rewritten as click-by-click GitHub installs (App, keys, Renovate, labels, branch protection, verification), same shape as anytomd's `docs/maintenance.md`
- fix(tools): `Request(url, headers)` pasaba el dict como *data* — todo sondeo de `health.py`/`upstream.py` moría antes de preguntar; orden de versiones por enteros, no lexicográfico; `zizmor` al grupo lint de management; las ensambladuras de `systems/*` entran en `drops` de los templates
- Self-maintenance for wide repos born: `repo-ci` and `repo-maintain` in `infra/` — the repo

