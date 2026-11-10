- A red is never hidden (e-nous `test-py-tdd` rule 2; plan `TODO_ghosts` in e-nous). Every Python blueprint (api, cli,
  common, graph, tui) bans `pytest.mark.xfail`, `pytest.xfail`, `pytest.mark.skip`, `pytest.mark.skipif`,
  `pytest.skip`, `pytest.importorskip` and `unittest.skip` through ruff `TID251`, and sets
  `empty_parameter_set_mark = "fail_at_collect"`, so an empty parametrize fails instead of skipping. Evidence: a probe
  test with `xfail` + `skip` gets 2 × `TID251` in common (2026-11-10).
- common: the blanket `TID251` ignore over `tests/**` narrowed to the 7 files that reach a vendor or the environment
  on purpose; otherwise the gate would have been off exactly where it matters.
- common: the 9 skips when a service was missing (Postgres ×3, vLLM, TEI, GCS emulator ×2, Gemini key, vision key)
  become errors. `make integration` locally now gives 115 passed and 9 visible reds (GCS emulator down, no Gemini/vision
  key); before, those were silent skips. `make offline` deselects `integration` instead of relying on those skips.
- common: `test_taxonomy`'s three config-mirror tests were vacuous (empty parametrize, `infra/config/` is flat
  clusters, not a tree): the two that test a tree that no longer exists are deleted; the third becomes
  `test_taxonomy_no_module_below_the_root_takes_settings`, a real assertion.
- Default runs: common 1416 passed and 0 skipped (5 red already on main: `ast-grep-cli` missing from `uv.lock`,
  `test_compose::test_full_stack` snapshot drift); api 170, cli 88, tui 179 passed; graph 770 passed + 21
  acceptance errors (no Chromium installed locally, an error and not a skip).
