# self-maintenance — Renovate opens, the bots sync, the agent mends, a human merges

Renovate proposes every dependency change, `sync` refreshes the lockfile, the Qwen agent repairs what
the update broke, `health` reports monthly. Nothing merges itself; the agent commits only inside its
allowlist — `.github/`, `QWEN.md`, `pyproject.toml` and `uv.lock` stay human.

### Enable — once

1. **GitHub App `self-maintenance`** — shared, installed on *All repositories*: nothing to do.
2. **Credentials and labels** — on the machine that holds `~/.config/smbot/`:

       echo {{repo}} >> ~/.config/smbot/repos.txt
       bootstrap-repos {{repo}}

3. **Renovate** — <https://github.com/apps/renovate> → *Configure*: *All repositories*, or add `{{repo}}`.
   Close its onboarding PR unmerged: `.github/renovate.json` already carries the config.
4. **Merge** the generated `.github/` and `QWEN.md` into `main`.
5. **Protect `main`** — public repositories only on GitHub Free: require a PR and the CI checks, and
   never let the app bypass them.

### Verify

    gh secret list -R {{repo}}       # APP_PRIVATE_KEY · QWEN_API_KEY
    gh variable list -R {{repo}}     # APP_CLIENT_ID (+ QWEN_MODEL)
    gh workflow run health -R {{repo}}

The *Dependency Dashboard* issue appears once Renovate has read the config; tick *Run Renovate now*
there. On the `renovate/*` PR, `sync` pushes the lockfile, CI runs, and if it fails `maintenance`
comments within three attempts — then labels `needs-human`.
