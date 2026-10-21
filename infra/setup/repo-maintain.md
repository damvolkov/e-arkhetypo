# repo-maintain — the self-maintenance loop for a wide repo

The `selfmaintain` loop aimed at three areas: `systems/` (uv locks, `sync-systems`), `stack/` (the image
ledger, weekly `sync-stack`) and `infra/` (action pins, `sync-infra` re-assembles every `.github/`).
`health-areas` reports monthly by area. Nothing merges itself; the agent commits only inside its
allowlist — `infra/`, `.github/`, `pyproject.toml`, `uv.lock` and `QWEN.md` stay human.

### Enable — once

1. **GitHub App `self-maintenance`** — shared, installed on *All repositories*: nothing to do.
2. **Credentials and labels** — on the machine that holds `~/.config/smbot/`:

       echo {{repo}} >> ~/.config/smbot/repos.txt
       bootstrap-repos {{repo}}

3. **Renovate** — <https://github.com/apps/renovate> → *Configure*: *All repositories*, or add `{{repo}}`.
   Close its onboarding PR unmerged: `.github/renovate.json` already carries the config.
4. **Merge** the generated `.github/` and `QWEN.md` into `main` (`make maintain && make maintain-check`).
5. **Protect `main`** — public repositories only on GitHub Free: require a PR and the checks
   `every system's CI` and `repo drift gates`, and never let the app bypass them.

### Verify

    gh secret list -R {{repo}}       # APP_PRIVATE_KEY · QWEN_API_KEY
    gh variable list -R {{repo}}     # APP_CLIENT_ID (+ QWEN_MODEL)
    gh workflow run sync-stack -R {{repo}}
    gh workflow run health-areas -R {{repo}}

The *Dependency Dashboard* issue appears once Renovate has read the config; tick *Run Renovate now*
there. A `renovate/*` PR gets its locks (`sync-systems`) or its `.github/` (`sync-infra`) pushed, CI
runs, and if it fails `maintenance` comments within three attempts — then labels `needs-human`.
