# Releasing

How this project is published, documented and kept alive. The system is
**semi-automated**: every mechanical step runs from one dispatch or a
`make` target; only the per-repo switches are set by hand, once.

## Versions

The git tag **is** the version — `uv-dynamic-versioning` resolves it at build
time from `git describe`. There is no version string anywhere in the tree to
bump, and therefore no release commit: a release is a tag.

## Cutting a release

```bash
make release minor       # or: patch | major (default patch)
```

Equivalent to `gh workflow run release.yml -f bump=minor`. The workflow then:

1. computes the next `vX.Y.Z` from the latest tag (first release → `v0.1.0`),
2. pushes the tag and opens the GitHub release with generated notes,
3. builds `sdist + wheel` from the tag and smoke-tests the wheel in a clean env,
4. publishes — each job only if its gate is on (below).

Republish an existing tag verbatim (e.g. after fixing the release notes):
dispatch `release.yml` with the `tag` input set.

## Optional gates

Every publishing surface is **inert by default**: CI quality, tests and the
strict docs build always run; deployment and publication require explicitly
declaring what this repo is. The single manifest of gates is
[`.github/ci.vars.example`](https://github.com/damvolkov/e-api/blob/main/.github/ci.vars.example);
`make ci-vars` lists it, and
`tests/unit/test_ci_contract.py` fails CI if a workflow uses an undocumented
gate or a gate ships enabled.

| Gate | Enables | One-time setup beyond the gate |
|---|---|---|
| `DOCS_DEPLOY` | Pages deploy from main | Settings → Pages → Source: **GitHub Actions** |
| `PUBLISH_PYPI` | PyPI publish (OIDC, no token) | PyPI → project → Trusted Publisher: owner/repo + workflow `release.yml` + environment `pypi` |
| `PUBLISH_IMAGE` | ghcr image `:vX.Y.Z` and `:latest` | none — uses the workflow's own `GITHUB_TOKEN` |

```bash
gh variable set DOCS_DEPLOY --body true
gh variable set PUBLISH_PYPI --body true
gh variable set PUBLISH_IMAGE --body true
```

A library enables `PUBLISH_PYPI`; a service typically enables `PUBLISH_IMAGE`
and `DOCS_DEPLOY`. Nothing else to configure — there are no long-lived
secrets in the release path.

## Maintenance loop

- **CI** (`ci.yml`): ruff · ty · tach · validate-pyproject · zizmor ·
  pytest × {ubuntu, macos, windows} with a 100% coverage gate · strict docs
  build on every PR (broken links fail).
- **Dependabot** (`.github/dependabot.yml`): weekly grouped PRs for actions
  and pip — every bump passes the same gates.
- **Docs**: reference pages are generated from the sources (mkdocstrings);
  never hand-write a table the code can derive. Where a project promises
  behaviour (a contract), model it like `e-serde`'s `STANDARDS`: claims in
  code, a test executing every claim against live behaviour, pages generated
  from the contract.
- **Reproducibility**: `exclude-newer` pins the dependency supply chain;
  actions are pinned by full commit SHA, verified against their tag.

## First release checklist

1. `make init <name>` done, repo pushed, CI green.
2. Decide the gates; set the variables above; do the per-gate one-time setup.
3. `make release minor` → tag `v0.1.0`, GitHub release, artifacts live.
4. Verify: `pip install <name>` (PyPI gate) or `docker pull ghcr.io/...`.
