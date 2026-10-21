# e-tui

Generic **e-stack** terminal-UI template: three orthogonal, declarative systems over Textual — a
config-driven **layout**, a graph-based **flow** engine, and a table-driven **interact**ive-object set —
with shared core materialized from `projects/python/core`.

* **Layout** — *frames are architecture, slots are content*. A layout is a tree of boxes (relative
  measures, base figures, static/dynamic kind) declared in code or a YAML/TOML/JSON file and compiled
  into responsive Textual containers. The app never arranges widgets; it fills named slots.
* **Flow** — the app is a sequential graph of **pages** with conditional edges and a reversible walk, the
  langgraph idiom. Pages are added in mount order through a `PagesBuilder` that validates each against the
  state its predecessors produce (`requires` / `produces` / `condition`), so a misplaced page dies at the
  add. A `Walker` navigates the built `Graph`; the shared `FlowState` (a core `State`) keeps the trail for
  the reverse, the committed answers and any domain data. The TUI (`WizardApp`) is a dumb viewer of a typed
  `Move`.
* **Interact** — each page shows one declarative `Spec` (toggle/choice/input/confirm/report); a frozen
  registry maps the spec type to its `ObjectPort` widget, and the answer always returns as a `Commit`.

```
src/e_tui/
  layout/           # the mini-framework (spec, render, frame, shape) — static/dynamic boxes
  flow/             # the graph engine (domain, no widgets): page, graph, pages, state, walk
    page.py         # a node: id, title, a Spec, requires/produces/condition, optional next / route / on_commit
    graph.py        # ordered pages; validation at build; next_of resolves the walk
    pages.py        # the PagesBuilder: adds pages in mount order, validating each against the shadow state
    state.py        # FlowState: shared bag (core State) — progress, reverse trail, answers; has()/seed() paths
    walk.py         # the navigation client: advance/back/reset, typed Move sum (OnPage/Declined/…)
  interact/         # the interactive objects (widgets, no graph): one file per kind
    ports.py        # ObjectPort protocol: built from a Spec + previous, answers a Commit
    registry.py     # the frozen Spec-type → Maker table; a gap raises InteractError
    toggle.py choice.py input.py confirm.py report.py
  templates/        # concrete layout derivations (standard)
  models/           # shared value objects: object.py (Specs/Commit/Field), error.py
  app.py            # LayoutApp (fills slots) and WizardApp (walks a graph, optional `result` seam)
  __main__.py       # `etui` — one line over `demo.build()`
  demo.py           # THE reusable fake app: folds the pages, walks them, emits an AppBlueprint
  pages/            # one module per page — the host's authoring layout (copy `demo.py` + `pages/` to start)
    system.py db.py modules.py confirm.py report.py
```

Layers (`tach`, high → low): `examples · app · templates · flow · interact · layout · adapters · core · ops ·
models`. `examples` (the fake app: `demo` + `pages/`) sits above the framework and is what a host copies — it
is never imported by the layers below it. `flow` imports no Textual; `interact` imports no `flow`. They meet
only on `ObjectPort` and `Commit`.

##### GEOMETRY LANGUAGE #####

Every `Box` is: a `kind` (static: only letters; dynamic: a fillable slot), a `shape` (`rect`, `ellipse`,
`circle`, `polygon` — regular or from normalized points), a `border` (`fine`, `thick`, `fill`, `none`),
an `axis` for its children (`row`, `column`, `overlay`) and two `Measure`s (`size` along the parent's
main axis, `cross` across it) in fractions of the parent with optional cell clamps on the *content*
area. `weight` shares leftover space between siblings. Everything is relative, so every tree is
responsive; nesting stops at three boxes on purpose. Three colors only, from `st.theme`
(`THEME_BACKGROUND`, `THEME_CORPORATE`, `THEME_INK`).

```python
class Wizard(LayoutApp):
    SPEC = StandardTemplate.SPEC          # or Box.load(Path("my-architecture.yml"))

wizard = Wizard()
wizard.fill("content", ListView(...))     # slots receive widgets before or after mount
```

##### FLOW #####

A `Page` is the node: it carries a `Spec` (what to show) and two kinds of edges. For **navigation**, a
`route` decides the next page from the live commit (langgraph's conditional edge), else `next`, else
declaration order. For **placement**, it declares `requires` / `produces` — the state paths it reads and
writes — plus an optional `condition` gate and an `on_commit` hook that derives domain data into the bag.

Pages are added **dynamically and in mount order** through `PagesBuilder`, which validates each against a
*shadow* `State` seeded with what the earlier pages produce: register the modules page before the system
page and the add dies with a `PageStructureError`, never mid-walk. `build` then emits the walk-safe `Graph`,
which the `Walker` navigates into typed `Move`s. `route` reads a live value at walk time; `condition` reads
declared presence at add time — the line that keeps structure errors out of the walk.

```python
graph = (PagesBuilder("wizard")
    .add(Page("system", "System", ChoiceSpec(fields=(...)), produces=frozenset({"system"})))
    .add(Page("modules", "Modules", ToggleSpec(fields=(...)),
              requires=frozenset({"system"}), route=needs_db))      # needs a system first; then forks
    .add(Page("db", "Configure DB", InputSpec(prompt="dsn?"), next="go"))
    .add(Page("go", "Confirm", ConfirmSpec(prompt="materialize?")))  # no → Declined
    .build())

app = WizardApp(graph)   # the viewer: page → content, trail → steps, keys → hint; navigate by keyboard
app.run()
```

`WizardApp` is the reference viewer: it mounts the page under the cursor through `interact.build`, paints
the walked trail into the `steps` band, and answers every `Move` by `match`. A host passes a `result` seam —
a `State → widgets` callable — so when the walk finishes the viewer mounts whatever the host wants to show
(never what the framework assumes). `etui` (`__main__.py`) is that host end to end: five kinds, one
conditional route, one condition, and a `result` view that emits the accumulated choices as a typed
`AppBlueprint` (formatted JSON). A real app keeps its pages under `pages/` and its own model behind `result`.

##### USAGE #####

```bash
make install    # materializes core/ops/adapters, syncs deps, git hooks
make run        # the reference wizard over the standard architecture (etui)
make check      # lint + type + arch + validate + drift + tests
make cov        # ... with the 100 % gate
```

##### SNAPSHOTS #####

`tests/acceptance/e_tui/test_gallery.py` renders every registered architecture at every viewport in the
matrix (`ops.snap.GallerySnap`) and diffs it against accepted SVGs — visual drift fails CI until a human
runs `uv run pytest --snapshot-update` and reviews the change.
