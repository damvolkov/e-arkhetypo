# Changelog

Maintenance record of this repository: every sync, bump and repair, filed under the area it
touches — `stack`, `systems`, `infra`. Lines under `[Unreleased]` are written by the bots
(`tools/changelog.py`) and by humans alike; cutting a release moves them under a version heading.

## [Unreleased]

### stack



### systems



### infra

- fix(tools): `Request(url, headers)` pasaba el dict como *data* — todo sondeo de `health.py`/`upstream.py` moría antes de preguntar; orden de versiones por enteros, no lexicográfico; `zizmor` al grupo lint de management; las ensambladuras de `systems/*` entran en `drops` de los templates
- Self-maintenance for wide repos born: `repo-ci` and `repo-maintain` in `infra/` — the repo

