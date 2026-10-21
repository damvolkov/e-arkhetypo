# Installing this project's CI

Generated from `infra/` — one section per feature installed, in pipeline order.
Gates ship inert: until a variable is set, the job exists and does nothing.

## repo-maintain

The `selfmaintain` loop aimed at three areas: `projects/python/` (uv locks, `sync-projects`), `stack/` (the image
ledger, weekly `sync-stack`) and `infra/` (action pins, bumped by Renovate together with every committed `.github/`).
`health-areas` reports monthly by area. Nothing merges itself; the agent commits only inside its
allowlist — `infra/`, `.github/`, `pyproject.toml`, `uv.lock` and `QWEN.md` stay human.

### Enable — once

1. **GitHub App `self-maintenance`** — shared, installed on *All repositories*: nothing to do.
2. **Credentials and labels** — on the machine that holds `~/.config/smbot/`:

       echo damvolkov/e-arkhetypo >> ~/.config/smbot/repos.txt
       bootstrap-repos damvolkov/e-arkhetypo

3. **Renovate** — <https://github.com/apps/renovate> → *Configure*: *All repositories*, or add `damvolkov/e-arkhetypo`.
   Close its onboarding PR unmerged: `.github/renovate.json` already carries the config.
4. **Merge** the generated `.github/` and `QWEN.md` into `main` (e-taxis assembles them).
5. **Protect `main`** — public repositories only on GitHub Free: require a PR and the checks
   `every system's CI` and `repo drift gates`, and never let the app bypass them.

### Verify

    gh secret list -R damvolkov/e-arkhetypo       # APP_PRIVATE_KEY · QWEN_API_KEY
    gh variable list -R damvolkov/e-arkhetypo     # APP_CLIENT_ID (+ QWEN_MODEL)
    gh workflow run sync-stack -R damvolkov/e-arkhetypo
    gh workflow run health-areas -R damvolkov/e-arkhetypo

The *Dependency Dashboard* issue appears once Renovate has read the config; tick *Run Renovate now*
there. A `renovate/*` PR gets its locks pushed by `sync-projects`; CI
runs, and if it fails `maintenance` comments within three attempts — then labels `needs-human`.
