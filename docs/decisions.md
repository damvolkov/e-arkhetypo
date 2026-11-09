# Decisions

Every architectural decision: date, the decision, the evidence, what was rejected and why.

## 2026-11-05 — The changelog is a fragment per branch, folded after every merge; the tool is ours, stdlib

**Decision.** A change is recorded in `changelog.d/<branch, / as ->.md`, never in `CHANGELOG.md`: two branches never
touch the same file. After every merge to main the `changelog-fold` workflow runs `changelog.py fold` on the fixed
branch `chore/changelog-fold` (rebuilt from main), opens or updates one PR with the self-maintenance App token and
auto-merges it. `CHANGELOG.md` is written only by that fold and by a release; the prek hook `changelog` blocks any
other commit that stages it, unless `CHANGELOG_FOLD=1`. The tool stays `infra/files/tools/changelog.py` (stdlib,
`record` and `fold`), shipped to every repo with the `selfmaintain` and `repo-maintain` features.
**Evidence.** Nearly every merge conflicted on `CHANGELOG.md`: each branch inserted its entry on the same line under
`## [Unreleased]` and the resolution was always "keep both". A fragment per branch removes the shared line. Tests
(`tests/unit/tools`, `tests/unit/hooks`): fold order by first-commit date, areas kept where the file uses them, plain
bullets otherwise, idempotent, no fragments is a no-op; the hook blocks a staged `CHANGELOG.md` and passes with
`CHANGELOG_FOLD=1` or nothing staged (also run through `prek` in a scratch repo). zizmor: no findings on the
workflow. Not run: the workflow end to end, which needs the App installed on the repo.
**Rejected.** towncrier, scriv and changie do the same, but towncrier types a fragment by file name
(`<id>.<type>.md`), scriv wants its own config and categories, changie is a Go binary: a toolchain a runner does not
have and a taxonomy our changelogs do not use, against a stdlib tool that already runs anywhere and that the bots'
`record` already uses. Folding only on release (findr-ground has no tags, the file would never move) and a generated
view of the fragments (the file people read would not exist in the tree). A `GITHUB_TOKEN` PR for the fold (it does
not trigger the required CI, so the PR would never merge).

## 2026-11-09 — The fragments folder is hidden: `.changelog.d/`

**Decision.** The per-branch fragments live in `.changelog.d/<branch, / as ->.md` (and the shipped guide in
`infra/files/.changelog.d/README.md`); the fold tool, the workflows that stage fragments, the features' file lists and
the prek hook's message name it. Fragments stay tracked, never ignored: they are the record a PR carries and the fold
reads from `origin/main`. The Triad moves with it: e-nous's `changelog` and `plans` checks, e-taxis's allowlist.
**Evidence.** Damien (2026-11-09): the folder is plumbing, not a page of the repo. findr-ground had dropped fragments
(TODO_layout 11) and, behind a merge queue, met four `CHANGELOG.md` conflicts in one day (#62 twice, #64, #65); it
returns to fragments under this name.
**Rejected.** Renaming in one piece only: the checks would see no fragments and demand `CHANGELOG.md`, which the hook
forbids — no commit passes. Gitignoring the folder: the record would never reach the PR.
