# Installing this project's CI

Generated from `infra/` — one section per feature installed, in pipeline order.
Gates ship inert: until a variable is set, the job exists and does nothing.

## repo-maintain

The same loop as `selfmaintain`, aimed at the three areas that change on their own clock:
`systems/` (uv project templates), `stack/` (compose services) and `infra/` (the CI library every
`.github/` is assembled from). Deterministic bots move every version; the agent fills only what a
rule cannot; a human merges.

```mermaid
flowchart LR
  R[Renovate] -->|PR renovate/* deps| S1[sync-systems: uv locks]
  R -->|PR renovate/* action pins| S3[sync-infra: re-assemble .github]
  X[sync-stack, weekly] -->|PR stack/resolve-*| C[CI: ecosystem · repo-gates]
  S1 -->|push| C
  S3 -->|push| C
  C -->|red, or new surface| A[maintenance.yml: Qwen agent]
  A -->|commit [maintenance]| C
  C -->|green| H[Human review and merge]
  M[health-areas.yml, monthly] --> I[issue deps-health: stack · systems · infra]
```

## What the bots touch

| Target | Files | Who | When |
|---|---|---|---|
| System dependency pins | `systems/*/pyproject.toml` | Renovate (`pep621`/`uv`) | a new release upstream |
| System lockfiles | `systems/*/uv.lock`, `management/uv.lock` | `sync-systems` (uv) | with every pin change |
| Pinned image tags | `stack/*/*/compose.yml` (only real pins like `pg17`, `v0.10.4`) | Renovate (`docker`) | a new image version — floating `:latest` never gets a PR |
| Image version ledger | `stack/stack.versions.yml` | `sync-stack` (`tools/stack_resolve.py`) | weekly: the digest every tag points at today |
| Action pins in CI sources | `infra/jobs/**`, `infra/workflows/*` digests | Renovate (`regex` manager) + `sync-infra` | monthly PR, then every assembly follows |
| Assembled workflows | every `.github/` | `sync-infra` (`e_management infra` + `repo-infra`) | after every pin change in `infra/` |
| Code, tests, docs, service configs | `systems/*/src\|tests\|docs`, `stack/*/*/` | `maintenance.yml` agent | CI red, or the dependency gained surface |
| Changelog | `CHANGELOG.md` → `## [Unreleased]` (sections `### stack / ### systems / ### infra`) | the bots, `tools/changelog.py` | every sync; the agent on user-visible changes |
| Health issue | GitHub issue labelled `deps-health` | `health-areas.yml` | monthly, split by area |
| Visual goldens | `systems/<s>/tests/acceptance/` | `snap-refresh.yml` (dispatch) | only when the runner's pixels moved — the runner is the canonical renderer |

**Human-only:** merging, release tags, `infra/` (the agent may never touch CI sources),
`pyproject.toml`, `uv.lock`, compose `image:` lines, `QWEN.md`. The agent's limits are enforced by
code, not trust: the workflow commits only allowlisted files and names every discarded one.

## Setup — one time, in the browser

Follow the paths literally; each step is one screen.

### 1 · Create the GitHub App

1. **github.com** → your **avatar (top right) → Settings**.
2. Left sidebar, at the very bottom: **Developer settings**.
3. **GitHub Apps → New GitHub App** (top right).
4. **GitHub App name** — anything (e.g. `e-templates-maintainer`); **Homepage URL** — the
   repository URL; **Contact email** — yours.
5. **Expand "Webhook"** → uncheck **Active**.
6. Under **Permissions → Repository permissions**, set exactly:

   | Permission | Access |
   |---|---|
   | Contents | **Read and write** |
   | Pull requests | **Read and write** |
   | Issues | **Read and write** |
   | Metadata | **Read-only** (automatic) |
   | **Workflows** | **Read and write** — the one difference vs a library repo |

   Workflows write is granted so `sync-infra` can *deterministically re-assemble* every `.github/`
   from `infra/` sources. The agent still cannot touch it: `maintenance` filters its commits against
   the allowlist, which excludes `.github/` and `infra/`, and `QWEN.md` repeats the wall.
7. **Create GitHub App**.
8. Copy the **Client ID** (`Iv1.xxxxxxxx`).
9. **Private keys → Generate a private key** → a `.pem` downloads; keep the file.
10. **Install App → Only select repositories →** pick this repository → **Install**.

### 2 · Hand the key and the ID to the repository

Repository → **Settings → Secrets and variables → Actions**:

1. Tab **Secrets → New repository secret**: name `APP_PRIVATE_KEY`, content = the **whole `.pem`
   file, both `-----` lines included**.
2. Tab **Variables → New repository variable**: name `APP_CLIENT_ID`, value `Iv1.xxxxxxxx`.

CLI equivalent:

    gh secret set APP_PRIVATE_KEY < /path/to/file.pem
    gh variable set APP_CLIENT_ID --body Iv1.xxxxxxxx

### 3 · Install Renovate

1. Go to **https://github.com/apps/renovate** → **Configure**.
2. **Only select repositories** → this repository → **Install**.
3. It reads `.github/renovate.json` (materialized from `infra/files/renovate.repo.json`) with
   four managers: `pep621` + `uv` for every `systems/*`, `docker` for `stack/**/compose.yml`, and
   a `regex` manager that reaches the action digests pinned in `infra/jobs/**` — where the stock
   `github-actions` manager cannot see. PRs carry the labels below.
4. The **Dependency Dashboard** issue lists everything pending; tick a box to run one now.

### 4 · The Qwen endpoint (the agent's mind)

Same screens as step 2:

| Name | Kind | Value |
|---|---|---|
| `QWEN_API_KEY` | Secret | your Alibaba Model Studio key |
| `QWEN_MODEL` | Variable, optional | default `qwen3.8-max` |
| `QWEN_BASE_URL` | Variable, optional | OpenAI-compatible endpoint, baked default |
| `QWEN_CLI_VERSION` | Variable, optional | pin `@qwen-code/qwen-code`, default `latest` |

### 5 · Create the labels the bots speak

**Issues → Labels → New label**, one per row:
`upstream-update` · `binding-update` · `tooling` · `ai-modified` · `needs-human` · `deps-health`
— plus the three areas: `area:stack` · `area:systems` · `area:infra`.

CLI, all nine at once:

    for l in upstream-update binding-update tooling ai-modified needs-human deps-health area:stack area:systems area:infra; do gh label create "$l" || true; done

### 6 · Protect `main`

Repo **Settings → Branches → Add branch protection rule** → pattern `main` → check
**Require a pull request before merging** (1 approval), **Require status checks to pass**
(add `every system's CI`, `repo drift gates` and the `test (…)` entries), **Do not allow
bypassing** — and keep the App off the allow list. **Create**.

## Verify the loop is alive

1. The **Dependency Dashboard** issue exists → Renovate read the config. Tick *Run Renovate now*.
2. A `renovate/*` PR touching a system → the **sync-systems** job pushes a lockfile commit; CI
   (`ecosystem`, `repo-gates`) then runs; if red, **maintenance** comments within three attempts.
3. A `renovate/action pins` PR touching `infra/` → **sync-infra** re-assembles every `.github/`
   and pushes it to the same branch.
4. Actions → **sync-stack → Run workflow** → a `stack/resolve-…` PR with the digest table, or the
   log "no movement".
5. Actions → **snap-refresh → Run workflow** (input: the system) → a `snap/<system>-…` PR only if
   the runner's pixels moved; the graph `cov`/`test` keep visual goldens out (`TESTARGS`) so both
   local and CI run without them.
5. Actions → **health-areas → Run workflow** → the `deps-health` issue opens with the three
   sections `## stack · ## systems · ## infra` (or stays absent if clean).

## Versioning

- `systems/*` carry their own semver in their own repos when exported; here they are templates.
- `stack/` versions live **only** in the ledger `stack/stack.versions.yml` (weekly, by bot).
  Compose files keep their floating tags; parked services say `stack.parked: "true"`.
- `infra/` pins are the single source; every `.github/` is generated from it — `make maintain`
  locally, `sync-infra` on Renovate branches.
- The repo itself is versioned by git tags + `CHANGELOG.md`: the bots write the `## [Unreleased]`
  area sections; cutting a release moves them under a dated heading.

## Running the pieces by hand

    make maintain && make maintain-check   # assemble every .github from infra/ and gate it
    make stack-versions                    # refresh the image ledger now
    make health                            # the three-area report, locally

`sync-stack` and `health-areas` accept a manual *Run workflow*; so does Renovate via its dashboard.
