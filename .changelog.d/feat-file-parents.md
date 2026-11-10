- common's gates gain `file-parents` (law 16, Damien 2026-11-10: "never relative from below"): no location derived
  from the module's own file — `Path(__file__).parent`, `.parents[n]`, resolved or not — in src/, scripts/, gates/; a
  path is absolute and given, or anchored once at `Path(sys.prefix).parent`. Evidence: the rule's cases pass
  `gates.engine test`; common has zero hits. Found in aivo's KANON hook (`parents[2]`), which the Triad's loader
  replaces with `CLAUDE_PROJECT_DIR`.
