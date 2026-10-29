# TODO_OPS — `ops/` as a closed set of categories, `infra/` instead of `core/`

> **Status 2026-10-26 — branch `refactor/ops-infra`:** the e-arkhetypo work below is DONE (commit 1: ops +
> registry + gate; commit 2: core/ → infra/ everywhere, common/ absorbed). Remaining: e-taxis (review
> section at the bottom), the other projects, e-nous. Delete this file when those are done too.

> Handover from e-gnosis (2026-10-26). Worked examples: e-gnosis PR #37 (`ops/`, entry "ops: seven categories of
> agnostic tools") and PR #38 (`infra/`, entry "core/ is infra/"), both in its `docs/decisions.md`.
> **Everything here applies to every archetype and every project** — not only the archetypes: e-taxis (and its
> `e-taxis-split` worktree), e-metaxy, e-jev, e-llm, e-rag, et-mlapi, and any other that carries `src/<pkg>/core/`.
> e-gnosis is done and is the reference.
> **Delete this file when every item below is done.**

## Premises (non-negotiable)

1. **`ops/` is a closed set of categories of agnostic tools, never more than 20.** A module in `ops/` names a
   category (what kind of tool), never a particular (one use of it). `file.py` is the reference: everything that tells
   and reads what a file is. Functions are `<category>_<scope>[_<detail>]`; classes carry the category as surname.
   Something new joins an existing category; a new category is a decision, recorded, and only while the count stays
   ≤ 20.
2. **`infra/` replaces `core/` and `common/` inside projects.** A project's internal infrastructure — settings, logger,
   errors, background, state, lifespans, the shared kernel of models — is `src/<pkg>/infra/`. No project keeps a
   `core/` or a `common/`. Not to be confused with e-arkhetypo's own top-level `infra/` (the CI/CD sources it
   assembles into projects): that one is infrastructure *of* projects; this one is infrastructure *inside* a project.
3. **Everything applies to all projects**, through the archetypes and e-taxis, and by hand where a project is not yet
   materialized from them.
4. **This file is deleted when the work is done.**

## The categories so far

| Category | Holds | Seen in |
|---|---|---|
| `file` | what a file is: detection, discovery over a package | archetypes, e-gnosis |
| `parser` | structured formats read into values: Markdown events, records across versions, the bearer header | e-gnosis |
| `pattern` | typed tokens in text, validated and normalized: dates, amounts, identifiers, URLs | e-gnosis |
| `lexical` | text read and rewritten by rule: name keys, secret redaction, language identification | e-gnosis |
| `algorithm` | algorithms no domain owns: MinHash/LSH, later statistics and numeric normalization | e-gnosis |
| `hash` | hashing without a key or secret: content addresses, every id a project mints | e-gnosis |
| `crypto` | everything that needs a key or entropy: keyed ids, bearer tokens, password hashing, JWS/JWE, signatures, AES-256-GCM | e-gnosis (moved from `core/crypto`) |
| `wrappers` | measuring wrappers (latency) | archetypes (removed from e-gnosis: unused there) |
| `image`, `registry`, `compose`, `snap`, `tui` | — | archetypes: **audit** whether each is a category or a particular, and fold the particulars into a category |

**`hash` and `crypto` never overlap:** `hash` takes no key and no secret (it names things); `crypto` needs a key or
entropy (it protects things). Cryptography is an agnostic tool: it lives in `ops/crypto.py`, **not** `core/crypto.py`.

## `infra/` instead of `core/` — what the e-gnosis rename taught

- `src/<pkg>/core/` → `src/<pkg>/infra/` with `git mv`, tests mirrored (`tests/unit/<pkg>/core` → `.../infra`).
- `infra/lifespan/core.py` → `infra/lifespan/infra.py`; `core_lifespan` → `infra_lifespan` where `main` imports it.
- **The state graph collides:** `system.infra` already holds the adapters, processors and annotators sealed at start,
  so the settings-and-logger section is **not** `system.infra`: e-gnosis named it `system.shared` (`SharedState`,
  startup event `shared ready`). Pick that name everywhere.
- **Never touch the HKDF info labels** in `ops/crypto` (`b"e-core/token"`, `e-core/jwe`, `e-core/encrypt`,
  `e-core/sign`): changing them changes every derived key. A blind `core/` → `infra/` replace hits them.
- Never touch paths that are not this package: e-nous paths (`core/tekton`, `core/nomos`, `core/base`), data in test
  goldens and resources, past entries of `docs/decisions.md`.
- Follow the rename into: `pyproject.toml` (ruff per-file-ignores, coverage omit, beartype/ty paths), `tach.toml`
  (module paths; relabel the layers to what they hold — e-gnosis: `base` → `infra`, the old `infra` (ops) → `ops`),
  README, docs index, CHANGELOG, docstrings that name `core.` or `core/`.
- The archetype project `projects/python/core` (e-core: "the common core every system imports, materialized with
  `make core`") and its `common/` folder (CODEOWNERS, dependabot, prek, python-version) follow the same law: decide and
  record their new names (`infra`, `make infra`), keeping them distinct from the top-level `infra/` of this repo.

## Work in e-arkhetypo — DONE (branch `refactor/ops-infra`)

- [x] Write the closed registry of `ops` categories (the table above, audited) — it lives in
      `projects/python/infra/docs/index.md`, the blueprint's inventory document ("un documento dentro que
      detalle todo lo que hay"): every module of every section with its purpose verbatim, the opt-in table
      (who materializes what), and the registry — 13 categories, one line each: holds / never holds.
- [x] Audit every archetype's `ops/` against it (`image`, `registry`, `compose`, `snap`, `tui`, `wrappers`):
      verdict — all six stay categories (each names a kind of tool, its class already carries the surname:
      LogoGenerator aside, flagged below); nothing folds, nothing renames. Only moves: crypto in, and the
      module set is now file, crypto, wrappers, image, registry, compose, snap, tui.
- [x] **Move `core/crypto.py` to `ops/crypto.py`** in the blueprint (the single source every archetype
      materializes): `CryptoError` (a root of its own), `TokenError`, `TokenFailure` out of `core/errors`;
      enums `TokenAlg`, `TokenEnc`, `PasswordHasher` + `BCRYPT_ROUNDS` into `ops/crypto`;
      `settings/crypto` keeps only `CryptoSettings`, importing the enums from `ops.crypto`; the engine reads
      the `CryptoConfig` Protocol (`CryptoSettings` satisfies it structurally); `generate_keys` returns the
      `CryptoKeys` dataclass; `Crypto.load()` retired. Tests at `tests/unit/e_infra/ops/test_crypto.py`
      (then `e_core`, commit 1). HKDF info labels untouched.
- [x] Port the two additions: `Crypto.identify(key, identifier, *, width=IDENT_SIZE)` and
      `Crypto.token(size=SECRET_SIZE)`, with the `##### IDENTIFIERS #####` tests and pinned vectors from
      e-gnosis.
- [x] RSA out of the slow marker: `test_sign_rsa` monkeypatches `RSA_SIZE` to 2048; the fast suite covers
      every branch.
- [x] The gate: `projects/python/infra/tests/unit/test_ops_contract.py` — parses the registry table from
      `docs/index.md` and fails on an `ops/` module outside it, on a 21st category, and on a public
      module-level function without its `<category>_` prefix. Runs in the blueprint's CI and in the
      ecosystem job. (The e-taxis validator for generated projects: see the review below.)
- [x] Rename `core/` → `infra/` in every archetype (api, cli, graph, mcp, tui) and in the blueprint itself
      (`projects/python/core` → `projects/python/infra`, package `e_core` → `e_infra`); `common/`
      disappeared into the blueprint: its five root files are now the blueprint's own tracked root files,
      `make infra` materializes sections + root files into every system, `make infra-check` gates both.
      `system.core` → `system.shared` (`SharedState`, `shared ready`) everywhere, `lifespan/core.py` →
      `lifespan/infra.py`, tach layers relabelled. `templates.yml`, both Makefiles of the repo root, README,
      QWEN, TODO, `infra/README`, `infra/jobs/` sources and the assembled `.github/` all speak infra.
- [ ] Release the archetypes so e-taxis materializes the change into projects — blocked on the e-taxis work
      below (its vendored `templates.yml`, its manifest defaults and its own materializer still speak
      `core`/`e_core`).

## Work in every project

- [ ] For each project in the list at the top: `ops/` audited into the closed categories (only moves and renames),
      `core/crypto` → `ops/crypto` (errors, enums and config protocol with it), `core/` → `infra/`, `common/` gone,
      `wrappers` removed where unused. Gates green with CI's own marker selection (`-m "not slow and not live"`).
- [ ] e-taxis: its materialization (`make core`, the drift gates, the generators) speaks `infra/`, so no project is
      generated with `core/` again.

## Work in e-nous (the brain: skills must teach it)

- [ ] `tax-py-naming`: rule 4 ("atomic module-level functions exist only in utility modules…") points to the closed
      category set; `references/functions.md` and `references/tree.md` gain the `ops` law (category, never particular;
      ≤ 20; `<category>_<scope>`), with the e-gnosis before/after as the sample.
- [ ] `proj-py-layout`: the `ops` layer described as the closed set; cryptography is `ops/crypto`, `infra` keeps
      only its configuration (`infra/config/crypto`, composed by `infra/settings`); `infra/` is the project's internal infrastructure, `core/` and
      `common/` are banned names — every scaffold and sample tree updated.
- [ ] Every other skill, reference and agent that names `core/` (settings, lifespan, logger, background…) says
      `infra/`.
- [ ] Through `flow-gen-lifecycle` (update op, gates, export), so new instances in every harness know the limit.

## Done when

The registry exists; every archetype's and every project's `ops/` passes the gate; `ops/crypto` (no `core/crypto`
left) carries `identify` and `token` with pinned tests; no project has a `core/` or `common/` package — `infra/`
everywhere, e-taxis generating it; the two skills teach the law and are exported; this file is deleted.

## Review: what e-taxis must change (2026-10-26, deferred — nothing here is done yet)

e-taxis is the consumer of the blueprint: its wizard must read what is there — the tree and the inventory
document (`projects/python/infra/docs/index.md`: modules, purposes, the opt-in table, the ops registry) — and
offer the user which optional infra parts a new project takes, instead of hard-coded skip lists. Inventory of
what the rename touches in e-taxis (counts from `git grep` on its main, 69f41fc):

1. `scripts/materialize.py` (13 refs): e-taxis materializes the blueprint into **itself** —
   `E_CORE_SRC` env → `E_INFRA_SRC`, default path `../e-arkhetypo/projects/python/infra/src/e_infra`,
   `_reroot_e_core` → `e_infra.<section> → e_taxis.<section>`, SECTIONS `core` → `infra`, messages; and its
   own EXCLUDES vocabulary (`ops/tui.py` …) unchanged.
2. `Makefile` (3 refs): `CORE_SRC`/`CORE_HEAD`, targets `core`/`common`/`core-check`/`common-check` →
   `infra`/`infra-check`, `taxis repo extract … projects/python/core` → `…/infra`, help text.
3. `src/e_taxis/project/data/templates.yml` (12 refs): the **vendored copy is stale** (predates the Zensical
   migration and the compose-word prune) — re-sync from arkhetypo: common root/package `e_infra`, materials
   at the blueprint root, the finalize/docker prune vocabulary (`infra`), and re-vendor on every arkhetypo
   change (or read the registry from the checkout — decide).
4. `src/e_taxis/project/models/manifest.py`: `Common.package` default `"e_core"` → `"e_infra"`; consider
   renaming the `common:` schema key itself (arkhetypo kept the key name so today's e-taxis keeps parsing).
5. Management (`project/core/{blueprint,plan,session,infra}.py`, `project/adapters/*`, `project/cli/commands.py`):
   the wizard's choices currently come from templates.yml `choices` + `common.skip`; the new source of
   optionality is the blueprint's inventory doc. Note `project/core/` is e-taxis's **own domain package named
   `core`** — the house law (no `core/` in any project) reaches it too: rename (its `infra.py` module already
   collides conceptually with the new vocabulary) or record why it stays.
6. e-taxis's own materialized sections `src/e_taxis/{core,ops,adapters,processors}` follow the same law as
   every project: `core/` → `infra/`, `core/crypto` → `ops/crypto` (errors, enums, config protocol with it),
   `system.core` → `system.shared`, tach/pyproject/Makefile/README/tests mirror; its `tests/unit/…/test_brain.py`
   (2 refs), `cli.py` help (`make core`), `ops/repo.py` docstring, `.github/workflows/{ci,release}.yml` (6 refs),
   `README.md`, `.gitignore`.
7. The `e-taxis-split` worktree (transpile branch) rebases onto the renamed main; it carries the same vendored
   templates copy.
8. **Graph locks**: every project's `graph.lock.yml` (areas list `core`, unit keys, `inputs_hash`) goes stale
   with the rename — regenerate all with e-taxis `GraphStore.write` (precedent: arkhetypo d10357e) after the
   e-taxis rename lands, and release the archetypes so the change materializes into projects.
9. The other projects, by hand or through taxis: e-metaxy, e-jev, e-llm, e-rag, et-mlapi (each: ops audited
   into the closed categories, `core/crypto` → `ops/crypto`, `core/` → `infra/`, `common/` gone, `wrappers`
   removed where unused, gates green with CI's own marker selection). e-gnosis is done and is the reference.
10. e-nous skills: `tax-py-naming` (rule 4 points to the closed category set; `references/functions.md` and
    `references/tree.md` gain the ops law with the e-gnosis before/after as the sample), `proj-py-layout`
    (ops the closed set; crypto is `ops/crypto`; `infra/` internal; `core/` and `common/` banned names;
    every scaffold and sample tree), every other skill/reference/agent that names `core/` for settings,
    lifespan, logger, background; exported through `flow-gen-lifecycle`.

### Smaller follow-ups noticed on the way (flagged, not touched)

- The standalone `damvolkov/e-core` repo (mirror of the blueprint; its Pages host the docs at
  `damvolkov.github.io/e-core`, and the blueprint's `zensical.toml` `site_url`/`repo_url` plus `docs/release.md`
  still point there): decide its fate — rename to e-infra, redirect Pages, or retire the mirror; the URLs
  follow that decision.
- e-gnosis `infra/lifespan/infra.py`: the module docstring still says `system.infra` while the code deposits
  `system.shared` (stale line from PR #38) — one-line fix the next time e-gnosis is touched.
- mcp archetype quirks: its Makefile lacks the `# — common —`/`# — gates —` section headers, so the generator's
  finalize strip never removed the materialize machinery from generated mcp projects (dormant broken targets);
  its clean list never matched the finalize pattern; it materializes `ops/snap` + `ops/compose` (the only
  service that does) — audit whether it should exclude them; it **tracks** `prek.toml` while its siblings
  ignore the materialized copy, and its `.gitignore` carried a dead `.pre-commit-config.yaml` entry (replaced
  by `prek.toml` in this pass to match what `make infra` writes).
- `ops/image.py`'s `LogoGenerator` is the one class not carrying its category surname (`ImageLogo`/`LogoImage`
  would); left as-is ("only moves and renames" — a class rename was not asked for). The gate checks function
  prefixes, not class surnames.
- mcp's materialized `ops/crypto` pulled the crypto deps (joserfc, cryptography, argon2-cffi, bcrypt) into
  `projects/python/mcp/pyproject.toml` (commit 1): the `settings/crypto → ops/crypto` chain imports them
  wherever the settings composer loads; before the move nothing in mcp imported the engine.
