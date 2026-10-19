# self-maintaining — Renovate + the App + the agent

Deterministic bots detect and prepare every dependency change; the agent fills only what a rule
cannot; a human merges. Nothing in this loop merges itself.

```mermaid
flowchart LR
  R[Renovate] -->|PR renovate/*| S[sync.yml: lockfiles]
  S -->|push| C[CI: tests · upstream-context]
  C -->|red, or new surface| A[ai-fix.yml: Qwen agent]
  A -->|commit [ai-fix]| C
  C -->|green| H[Human review and merge]
  A -->|3 attempts used| N[label needs-human]
  M[health.yml, monthly] --> I[issue deps-health]
```

## What the bots touch

| Target | Files | Who | When |
|---|---|---|---|
| Dependency pins | `pyproject.toml`, `.github/workflows/*` action digests | Renovate | a new release upstream |
| Lockfile | `uv.lock` | `sync.yml` (uv) | with every pin change |
| Package code, tests, docs | `src/<package>/`, `tests/`, `docs/` | `ai-fix.yml` agent | CI red, or the dependency gained surface |
| Changelog | `CHANGELOG.md` → `## [Unreleased]` | `ai-fix.yml` agent | every user-visible change |
| Health issue | GitHub issue labelled `deps-health` | `health.yml` | monthly |
| PR comments and labels | the Renovate PR | `sync.yml`, `ai-fix.yml` | after each run |

**Human-only:** merging, the package version, release tags (`v*`), `.github/`, `QWEN.md`,
`pyproject.toml`, `prek.toml`. The agent's limits are enforced by code, not trust: the workflow
commits only files inside the allowlist and discards everything else, naming it in the PR comment.

## Setup — one time, in the browser

Follow the paths literally; every step is one screen. If you prefer the CLI, each section also
shows the `gh` equivalent.

### 1 · Create the GitHub App

1. Go to **github.com**, click your **avatar (top right) → Settings**.
2. In the left sidebar, scroll to the very bottom: **Developer settings**.
3. Click **GitHub Apps → New GitHub App** (top right of the Apps list).
4. Fill in: **GitHub App name** — anything (e.g. `<repo>-maintainer`);
   **Homepage URL** — the repository URL; **Contact email** — yours.
5. **Expand "Webhook"**: uncheck **Active**. Nothing is pushed anywhere; the App only acts when
   workflows ask it to.
6. Under **Permissions → Repository permissions**, set exactly:

   | Permission | Access |
   |---|---|
   | Contents | **Read and write** |
   | Pull requests | **Read and write** |
   | Issues | **Read and write** |
   | Metadata | **Read-only** (added automatically) |
   | Workflows | **No access** (read-only is fine too — never write) |

   Workflows must stay off: nothing the bots do may rewrite `.github/` — the allowlist in
   `ai-fix.yml` and `QWEN.md` enforce the same wall from the other side.
7. Click **Create GitHub App**.
8. On the App's page, copy the **Client ID** (looks like `Iv1.xxxxxxxx`) — you need it in step 3.
9. Scroll to **Private keys** → **Generate a private key**. A `.pem` file downloads (one per
   click; older ones keep working). Keep the file.
10. Go to **Install App** (top tab) → **Only select repositories** → pick **this repository** →
    **Install**. That is all the App ever sees.

### 2 · Hand the key and the ID to the repository

1. Open the **repository** → **Settings** (repo Settings, not account Settings).
2. Left sidebar → **Secrets and variables → Actions**.
3. Tab **Secrets** → **New repository secret** → Name `APP_PRIVATE_KEY`, Content: open the `.pem`
   in a text editor and paste **the whole file, both ----- lines included** → Add secret.
4. Tab **Variables** → **New repository variable** → Name `APP_CLIENT_ID`, Value: the `Iv1.…`
   client ID from step 1.8 → Save.

CLI equivalent (from the repo clone):

    gh secret set APP_PRIVATE_KEY < /path/to/file.pem
    gh variable set APP_CLIENT_ID --body Iv1.xxxxxxxx

### 3 · Install Renovate

1. Go to **https://github.com/apps/renovate** → click **Configure** (or *Add to account*).
2. Choose **Only select repositories** → pick **this repository** → **Install**.
3. Nothing else to configure: Renovate reads `.github/renovate.json`, which `infra/` materializes.
   It opens its first PRs on its own schedule (Mondays); the first morning it only explores.
4. Watch the issue titled **Dependency Dashboard** — it lists every pending update; tick the
   box (or comment the listed number) to force one now.

### 4 · The Qwen endpoint (the agent's mind)

Repo **Settings → Secrets and variables → Actions**, same screens as step 2:

| Name | Kind | Value |
|---|---|---|
| `QWEN_API_KEY` | Secret | your Alibaba Model Studio key |
| `QWEN_MODEL` | Variable, optional | default `qwen3.8-max` |
| `QWEN_BASE_URL` | Variable, optional | OpenAI-compatible endpoint, baked default |
| `QWEN_CLI_VERSION` | Variable, optional | pin `@qwen-code/qwen-code`, default `latest` |

The agent's contract lives in `QWEN.md` at the repo root — human territory; bots read it, never
write it.

### 5 · Create the labels the bots speak

**Issues → Labels → New label**, one per row (colour of your taste):
`upstream-update` · `binding-update` · `tooling` · `ai-modified` · `needs-human` · `deps-health`.

CLI, all six at once:

    for l in upstream-update binding-update tooling ai-modified needs-human deps-health; do gh label create "$l" || true; done

### 6 · Protect `main` (the wall that makes the loop safe)

1. Repo **Settings → Branches → Add branch protection rule**.
2. **Branch name pattern**: `main`.
3. Check **Require a pull request before merging** → **Require approvals: 1**.
4. Check **Require status checks to pass** and search-add the CI jobs: `lint · types · arch` and
   the `test (…)` matrix entries. Without them the bot branches can never merge anyway.
5. Check **Do not allow bypassing the above settings** — and do not add the App to the
   *allow* list. Only humans merge.
6. **Create**.

## Verify the loop is alive

1. **Issues → open the Dependency Dashboard**: if it exists, Renovate read the config fine.
   Tick *Run Renovate now* there and watch a `renovate/…` branch appear.
2. Open the dashboard's PR → the **`sync`** job must push a lockfile commit; CI must then run.
3. Actions tab → **CI** → on any `renovate/*` PR you should see `upstream-context`; break a test
   on purpose and `ai-fix` comments on the PR within its three attempts.
4. Actions → **health** → **Run workflow** → the `deps-health` issue opens or closes.

## Running the pieces by hand

    uv run python tools/health.py --output report.md --token "$(gh auth token)"
    make infra && make infra-check

`health.yml` and the Renovate dashboard both accept a manual run (*Run workflow* / the dashboard
box).
