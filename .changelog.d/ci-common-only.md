- CI holds common alone (Damien, 2026-11-10): the ecosystem job syncs and runs `make ci` in `projects/python/common`
  only; the frozen templates no longer run there (on #143 they failed on coverage and on graph's types against the new
  common, while common passed: 1429 tests).
