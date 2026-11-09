- The fragments folder is `.changelog.d/` (was `changelog.d/`): `git mv` of the repo's own and of the shipped guide
  (`infra/files/.changelog.d/README.md`); `FRAGMENTS` in `tools/changelog.py` (infra and `.github`), the
  `changelog-fold` trigger path and its `git add`, the `sync-*` and `snap-refresh` workflows, the `selfmaintain` and
  `repo-maintain` file lists, the prek `changelog` hook's message. `test_changelog.py` asks for `.changelog.d/` (2 red,
  then 21/21). Decision in `docs/decisions.md`; e-nous and e-taxis move with it (TODO_fragments).
