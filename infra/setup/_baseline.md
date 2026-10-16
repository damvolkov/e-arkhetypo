# CI baseline — nothing to install

`quality` and `test` run on every push to `main` and every PR. No secrets, no variables, no gates:
they are the floor. The coverage floor lives in `pyproject.toml` (`[tool.coverage.report] fail_under`),
the OS and Python matrix in `.github/ci.defaults.yml` → `tokens`.

Required checks if you protect `main`: `lint · types · arch`, `test (…)`.
