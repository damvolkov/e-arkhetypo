# infra

Source of truth for every e-stack CI/CD workflow, as it is `projects/python/core/common/` for the shared project
files. Nothing here is a running thing: the fragments are **materialized and assembled** into a project's
`.github/` — by [e-taxis](https://github.com/damvolkov/e-taxis), and drift-gated there, exactly like
`core` and `common`.

```
infra/
  features.yml       # THE MAP: feature -> atomic jobs, gate var, requires, secrets, setup doc
  workflows/         # whole-workflow shells: the header every generated workflow shares
    ci.yml           #   {{ci_jobs}} is replaced by the assembled ci jobs
    release.yml      #   {{release_trigger}} {{release_inputs}} {{release_jobs}} — git-first, inert gates
  jobs/              # one file = one atomic job, already indented for its workflow
    ci/              #   quality · test · docs · pages · ui · snapshots · coverage · upstream-context{,-repo} · ecosystem · repo-gates
    release/         #   bump · build · publish · image
    workflow/        #   sync · maintenance · health (libraries) · sync-projects · sync-stack · sync-infra · health-areas (wide repos)
  files/             # config and tools copied verbatim (or through the same token pass): renovate{,.repo}.json ·
                     #   qwen{,.repo}.md · tools/{health,upstream,repo_health,stack_resolve,changelog}.py
  setup/             # one file = one feature: the one-time GitHub install instructions
    _baseline.md docs.md pypi.md image.md frontend.md rust.md selfmaintain.md repo-maintain.md
    deprecated/      #   the per-repo App guides, superseded by the shared app — never assembled
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
- A feature whose `requires` is not selected cannot be assembled: e-taxis refuses it.

##### THE MAP AT A GLANCE #####

| feature | jobs | gate | requires |
|---|---|---|---|
| `ci-basics` | quality · test | — (always on) | — |
| `docs` | docs · pages | `DOCS_DEPLOY` | — |
| `pypi` | bump · build · publish | `PUBLISH_PYPI` | — |
| `image` | image | `PUBLISH_IMAGE` | `stack.docker` |
| `frontend` | ui (+ snapshots) | `UI_SNAPSHOTS` | — |
| `rust` | coverage · wheels · sdist | release on `v*` tag | `pypi` |
| `selfmaintain` | sync · maintenance · health | branch `renovate/*` | `ci-basics` |
| `repo-ci` | ecosystem · repo-gates | — (always on) | — |
| `repo-maintain` | sync-projects · sync-stack · sync-infra · maintenance · health-areas | branch `renovate/*`, `stack/resolve-*`, schedules | `repo-ci` (replaces `selfmaintain`) |

Assembled per project by e-taxis; read `features.yml` for the machine version of that table.

##### SELF-MAINTENANCE APP #####

One GitHub App, `self-maintenance`, serves every repository: owned by `damvolkov`, installed on
*All repositories*, webhook off. Its repository permissions are the union every loop needs —
Contents, Pull requests, Issues and Workflows *read and write*, Metadata read. Each job narrows its
own token with `permission-*` inputs: only `sync-infra` asks for `workflows`, so the agent's token
can never push `.github/`; the `maintenance` allowlist is the second wall.

Credentials live once, outside git, in `~/.config/smbot/` (`app.pem`, `client_id`, `qwen_api_key`,
`vars.env`, `repos.txt`); `bootstrap-repos [owner/repo …]` writes them to each repository,
idempotently. Every job blueprint consumes exactly these names and nothing else:

| Name | Kind | Consumed as |
|---|---|---|
| `APP_CLIENT_ID` | variable | `client-id:` of `create-github-app-token` (v3 accepts it; `app-id` is deprecated) |
| `APP_PRIVATE_KEY` | secret | `private-key:` — the whole `.pem` |
| `QWEN_API_KEY` | secret | the agent's key |
| `QWEN_MODEL` · `QWEN_BASE_URL` · `QWEN_CLI_VERSION` | variables, optional | always with a `\|\|` default in the blueprint |

Labels the jobs may use are the ones `bootstrap-repos` creates — a blueprint that adds one adds it
to the script's `LABELS` too. No `owner` or `repositories` input: the installation of the running
repository is the token's scope. Never validate, truncate or store a token by length.

Rotation: generate a new key (app) or a new Model Studio key, overwrite the file in
`~/.config/smbot/`, rerun `bootstrap-repos`, then delete the old key — the app holds several at once.
