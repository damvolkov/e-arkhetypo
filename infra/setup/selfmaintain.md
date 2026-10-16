# self-maintaining — Renovate + the App + the agent

Deterministic bots detect and prepare every dependency change; the agent fills only what a rule cannot;
a human merges. Nothing in this loop merges itself.

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

## 1 · The GitHub App (the one machine identity)

*Settings → Developer settings → GitHub Apps → New GitHub App.* Homepage/description anything,
**webhook OFF**, Object permissions per the matrix below, then *Install* it on this repository only.

| Permission | Access |
|---|---|
| Contents | Read and write |
| Pull requests | Read and write |
| Issues | Read and write |
| Metadata | Read |
| **Workflows** | **No access** |

Workflows must stay off: nothing the bots do may rewrite `.github/` — the allowlist in `ai-fix.yml`
and `QWEN.md` enforce the same wall from the other side.

Generate a **private key** (`.pem`) under the App, and note its **Client ID**. In the repository:

    gh secret set APP_PRIVATE_KEY < <file>.pem
    gh variable set APP_CLIENT_ID --body <Iv... client id>

## 2 · Renovate (the plugin)

Install the public app: **https://github.com/apps/renovate** → this repository only. It reads
`.github/renovate.json`, which `make infra` materializes from `infra/`. The Dependency-Dashboard issue
lists every update; mark one obsolete to silence a package, check the box to run it now.

## 3 · The Qwen endpoint (the agent's mind)

    gh secret set QWEN_API_KEY --body <key>
    gh variable set QWEN_MODEL --body qwen3.8-max          # optional, this is the default
    gh variable set QWEN_BASE_URL --body <openai-compatible endpoint>   # optional, baked default
    gh variable set QWEN_CLI_VERSION --body latest          # optional, pin for reproducibility

The agent contract lives in `QWEN.md` at the repo root — human territory; the bots may read it, never
write it.

## 4 · Labels and protection

Create the five labels the bots speak: `upstream-update`, `binding-update`, `tooling`, `ai-modified`,
`needs-human`, plus `deps-health` for the monthly probe. Protect `main`: one approving review, required
status checks from the baseline, no bypass for the App.

## 5 · Guard rails (already in the workflows, enforced by code not trust)

- The agent never commits: the workflow commits, after filtering staged files against the allowlist;
  anything outside is discarded and named in the PR comment.
- At most **three** `[ai-fix]` commits per branch — then `needs-human`.
- `expose` runs once per PR; runs triggered by a stale head are skipped.
- `workflow_run` fires only for same-repository `renovate/*` branches — forks never reach the secrets.

## Running the pieces by hand

    uv run python tools/health.py --output report.md --token "$(gh token)"   # the monthly report, locally
    make infra && make infra-check                                            # what the bots see in CI

`health.yml` and the Renovate dashboard both accept a manual run (*Run workflow* / the dashboard box).
