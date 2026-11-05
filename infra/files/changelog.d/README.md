# changelog.d

One fragment per branch: `changelog.d/<branch, with / as ->.md` (`feat/base-root` -> `feat-base-root.md`), a list of
bullets. Record your change there, never in `CHANGELOG.md`: two branches never touch the same file, so the changelog
never conflicts.

```
- what the change does, and the evidence behind it
```

Under `### stack`, `### projects` or `### infra` headings when `CHANGELOG.md` is split by area.

After every merge to main, the `changelog-fold` workflow folds every fragment into `## [Unreleased]` (oldest first),
deletes it, and opens one PR. `CHANGELOG.md` is written only by that fold and by a release; the `changelog` hook
blocks any other commit that touches it. A fragment folds by hand with
`CHANGELOG_FOLD=1 python .github/tools/changelog.py fold`.
