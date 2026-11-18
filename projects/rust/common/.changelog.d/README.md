# .changelog.d

One fragment per branch: `.changelog.d/<branch, with / as ->.md` (`feat/detail` -> `feat-detail.md`), a list of
bullets. Record your change there, never in `CHANGELOG.md`: two branches never touch the same file, so the changelog
never conflicts.

```
- what the change does, and the evidence behind it
```

A release folds every fragment into the new version's section and deletes it (`make release`); the `changelog` hook
blocks any other commit that touches `CHANGELOG.md` (`CHANGELOG_FOLD=1` for the fold).
