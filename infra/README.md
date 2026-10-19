# infra

Source of truth for every e-stack CI/CD workflow, as it is `systems/core/common/` for the shared project
files. Nothing here is a running thing: the fragments are **materialized and assembled** into a project's
`.github/` — by `management` (`make infra` / the wizard's CI section), and drift-gated (`make infra-check`),
exactly like `core` and `common`.

```
infra/
  features.yml       # THE MAP: feature -> atomic jobs, gate var, requires, secrets, setup doc
  workflows/         # whole-workflow shells: the header every generated workflow shares
    ci.yml           #   {{ci_jobs}} is replaced by the assembled ci jobs
    release.yml      #   {{release_trigger}} {{release_inputs}} {{release_jobs}} — git-first, inert gates
  jobs/              # one file = one atomic job, already indented for its workflow
    ci/              #   quality · test · docs · pages · ui · snapshots · coverage · upstream-context{,-repo} · ecosystem · repo-gates
    release/         #   bump · build · publish · image
    workflow/        #   sync · ai-fix · health (libraries) · sync-systems · sync-stack · sync-infra · health-areas (wide repos)
  files/             # config and tools copied verbatim (or through the same token pass): renovate{,.repo}.json ·
                     #   qwen{,.repo}.md · tools/{health,upstream,repo_health,stack_resolve,changelog}.py
  setup/             # one file = one feature: the one-time GitHub install instructions
    _baseline.md docs.md pypi.md image.md frontend.md rust.md selfmaintain.md repo-maintain.md
  contract.py.j2     # the generated tests/unit/test_ci_contract.py — manifest vs workflows, both ways
```

##### RULES #####

- **Tokens** are `{{lowercase_words}}` only — never a space. `${{ github.* }}` is GitHub's, untouched.
  A fragment left with an unknown token fails the assembly: determinism is the contract.
- **Every gate ships inert.** A feature's job is installed but does nothing until the repo sets its
  variable (`gh variable set NAME --body true`). `.github/ci.vars.example` and the install docs are
  generated from the map, so manifest, workflows and docs can never drift apart — the contract test
  enforces it in every generated project.
- **Pins are digests with the version in a comment**, never floating tags. Renovate refreshes them.
- A feature whose `requires` is not selected cannot be assembled: `management` refuses it, the CLI
  refuses it, and the CI section of the wizard never lights it.

##### THE MAP AT A GLANCE #####

| feature | jobs | gate | requires |
|---|---|---|---|
| `ci-basics` | quality · test | — (always on) | — |
| `docs` | docs · pages | `DOCS_DEPLOY` | — |
| `pypi` | bump · build · publish | `PUBLISH_PYPI` | — |
| `image` | image | `PUBLISH_IMAGE` | `stack.docker` |
| `frontend` | ui (+ snapshots) | `UI_SNAPSHOTS` | — |
| `rust` | coverage · wheels · sdist | release on `v*` tag | `pypi` |
| `selfmaintain` | sync · ai-fix · health | branch `renovate/*` | `ci-basics` |
| `repo-ci` | ecosystem · repo-gates | — (always on) | — |
| `repo-maintain` | sync-systems · sync-stack · sync-infra · ai-fix · health-areas | branch `renovate/*`, `stack/resolve-*`, schedules | `repo-ci` (replaces `selfmaintain`) |

Assembled per project by `management`; read `features.yml` for the machine version of that table.
