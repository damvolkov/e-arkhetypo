# repo-maintain — Renovate + the App + the agent, for a wide repo

The same loop as `selfmaintain.md`, but pointed at three areas that change on their own clock:
`systems/` (uv templates), `stack/` (compose images) and `infra/` (the CI library). Deterministic
bots move every version; the agent fills only what a rule cannot; a human merges.

```mermaid
flowchart LR
  R[Renovate] -->|PR renovate/*| S1[sync-systems: uv locks]
  R -->|PR renovate/* action pins| S3[sync-infra: re-assemble .github]
  X[sync-stack, weekly] -->|PR stack/resolve-*| C[CI: ecosystem · repo gates]
  S1 -->|push| C
  S3 -->|push| C
  C -->|red, or new surface| A[ai-fix.yml: Qwen agent]
  A -->|commit [ai-fix]| C
  C -->|green| H[Human review and merge]
  M[health-areas.yml, monthly] --> I[issue deps-health: stack · systems · infra]
```

## 1 · The GitHub App (the one machine identity)

As in `selfmaintain.md`, with **one difference**: this repo lets the deterministic sync re-assemble
workflows, so the App needs **Workflows: Read and write** — the agent still cannot: the `ai-fix`
allowlist and `QWEN.md` keep `.github/` and `infra/` out of its reach, and only the assembler writes
them, from `infra/` sources.

    gh secret set APP_PRIVATE_KEY < <file>.pem
    gh variable set APP_CLIENT_ID --body <Iv... client id>

## 2 · Renovate (the plugin)

Install **https://github.com/apps/renovate** on this repository. It reads `.github/renovate.json`,
materialized from `infra/files/renovate.repo.json`: `pep621`/`uv` for every `systems/*`, `docker` for
`stack/*/*/compose.yml`, and a `regex` manager for the action digests pinned in `infra/jobs/**` —
which the stock `github-actions` manager cannot see. Floating `:latest` tags get no PRs by design:
sync-stack records them weekly into `stack/stack.versions.yml` instead.

## 3 · The Qwen endpoint (the agent's mind)

    gh secret set QWEN_API_KEY --body <key>
    gh variable set QWEN_MODEL --body qwen3.8-max          # optional, this is the default
    gh variable set QWEN_BASE_URL --body <openai-compatible endpoint>   # optional, baked default
    gh variable set QWEN_CLI_VERSION --body latest          # optional, pin for reproducibility

The agent contract lives in `QWEN.md` at the repo root — human territory; the bots may read it,
never write it.

## 4 · Labels and protection

The five labels of `selfmaintain` (`upstream-update`, `binding-update`, `tooling`, `ai-modified`,
`needs-human`) plus the three areas — `area:stack`, `area:systems`, `area:infra` — and `deps-health`.
Protect `main`: one approving review, required checks from the ecosystem and repo gates, no bypass
for the App.

## 5 · Variables, secrets, the whole list

| Kind | Name | Value |
|---|---|---|
| secret | `APP_PRIVATE_KEY` | the App's `.pem` |
| secret | `QWEN_API_KEY` | Qwen endpoint key |
| var | `APP_CLIENT_ID` | the App's client id |
| var | `QWEN_MODEL` · `QWEN_BASE_URL` · `QWEN_CLI_VERSION` | optional, sensible defaults |

No gate variable arms these workflows: they fire on `renovate/*` and `stack/resolve-*` branches and
on schedules. The area labels arm nothing — they route.

## Running the pieces by hand

    uv run --no-project python tools/stack_resolve.py --output stack/stack.versions.yml   # the ledger
    uv run --no-project python tools/repo_health.py --root . --output report.md           # the 3-area report
    make maintain && make maintain-check   # assemble and gate this repo's own .github/

`health-areas.yml` and `sync-stack.yml` both accept a manual run (*Run workflow*).
