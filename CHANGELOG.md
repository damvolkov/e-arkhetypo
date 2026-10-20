# Changelog

Maintenance record of this repository: every sync, bump and repair, filed under the area it
touches — `stack`, `systems`, `infra`. Lines under `[Unreleased]` are written by the bots
(`tools/changelog.py`) and by humans alike; cutting a release moves them under a version heading.

## [Unreleased]

### stack

- floating tags resolved to current digests (`stack/resolve-2026-10-20`)
- `storage/minio` parked: `stack.parked: "true"` — the image died upstream with MinIO's OSS, the service is off on the host and the version bots stop probing it until removal

### systems

- core: wall-clock benchmarks marked `slow` and out of `test`/`cov` by default (`TESTARGS`) — a cold runner hiccup is not a correctness gate
- graph: visual goldens leave `test`/`cov` (`TESTARGS` default `-m 'not ui'`) — they are runner-canonical now

### infra

- new feature `snap-refresh`: a dispatch regenerates one system's goldens on the runner and PRs the pixels; `gh pr create --head` fixed in the bot PR openers
- setup-uv step in `sync-stack`, `health-areas` and `upstream-context-repo`: bare `uv run --no-project` died 127 on runners without it
- setup docs for dummies: `selfmaintain.md` and `repo-maintain.md` rewritten as click-by-click GitHub installs (App, keys, Renovate, labels, branch protection, verification), same shape as anytomd's `docs/maintenance.md`
- fix(tools): `Request(url, headers)` pasaba el dict como *data* — todo sondeo de `health.py`/`upstream.py` moría antes de preguntar; orden de versiones por enteros, no lexicográfico; `zizmor` al grupo lint de management; las ensambladuras de `systems/*` entran en `drops` de los templates
- Self-maintenance for wide repos born: `repo-ci` and `repo-maintain` in `infra/` — the repo

