# Installing this project's CI

Generated from `infra/` — one section per feature installed, in pipeline order.
Gates ship inert: until a variable is set, the job exists and does nothing.

## ci-basics

`quality` and `test` run on every push to `main` and every PR. No secrets, no variables, no gates:
they are the floor. The coverage floor lives in `pyproject.toml` (`[tool.coverage.report] fail_under`),
the OS and Python matrix in `.github/ci.defaults.yml` → `tokens`.

Required checks if you protect `main`: `lint · types · arch`, `test (…)`.
## docs

Once, in the repository:

1. **Settings → Pages → Source: GitHub Actions** (the `pages` job deploys through Actions, not a branch).
2. Enable: `gh variable set DOCS_DEPLOY --body true` — until then the build runs strict but nothing deploys.
3. The repository must be **public** for Pages to serve it; a private repo keeps the deploy inert.

The docs job fails the PR on a broken link or a missing asset (`--strict`), gate or no gate.
## pypi

Once, in the repository and on PyPI:

1. **pypi.org → your project → Publishing → Add trusted publisher**: owner `<you-or-org>`,
   repository `<repo>`, workflow `release.yml`, environment `pypi`. Same for every project name you own.
2. In GitHub, the `pypi` environment may hold approver protection; the OIDC job only needs the
   environment to **exist** with that name (`environment: pypi` in the publish job).
3. Enable: `gh variable set PUBLISH_PYPI --body true`.

Release by hand afterwards: Actions → Release → *Run workflow* → bump `patch|minor|major`, or republish
an existing `v*` tag verbatim. The tag IS the version (`uv-dynamic-versioning`); nothing publishes on a merge.
## image

The `image` job logs into ghcr with the built-in `GITHUB_TOKEN`; there is no secret to create. Once:

1. Enable: `gh variable set PUBLISH_IMAGE --body true` (the feature also needs the `stack.docker` choice:
   the repo must carry a `Dockerfile`).
2. **First push of a new package**: GitHub asks who may let Actions write it — approve once in
   the package settings, or pre-approve the repository. Subsequent runs are silent.
3. The package inherits the repository's visibility; make it public if consumers should pull without auth.

Tags: `ghcr.io/<owner>/<brand>:<version>` and `:latest`. Multiple images per repo (e-voice style):
keep one Release workflow per image with its own `<name>-v*` tag scheme.
## frontend

`ui` needs nothing: pnpm and node come from the pinned actions and the lockfile decides the rest.
The `snapshots` job installs a browser and runs `pytest -m ui` against the bundled site — enable it
where you want the visual gate:

    gh variable set UI_SNAPSHOTS --body true

Accepted snapshot images live in `tests/acceptance/snapshots`; regenerate them on a workstation
(`make snap`) and commit — the CI never rewrites its own ground truth.
