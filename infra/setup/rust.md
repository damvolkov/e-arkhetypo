# rust — binding releases and the llvm-cov floor

The release runs on the `v*` tag instead of a dispatch: `git tag v1.2.3 && git push origin v1.2.3`
publishes wheels for the five house targets, the sdist, provenance attestation and the PyPI upload
(trusted publishing — see pypi.md). Once in the repo:

1. `tools/coverage.py` must exist (the rust feature installs it).
2. The floor is the `coverage_floor` token in `.github/ci.defaults.yml` (house default: 90).

The `selfmaintain` feature pairs well here: `sync.yml` re-versions the package on engine bumps and
`upstream-context` feeds the public-API diff to the agent.
