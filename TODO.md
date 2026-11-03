# TODO — e-tui

## Estado (2026-10-05, verde: 174 tests, 100 % cov, tach/ty/ruff/check)

- `projects/python/tui` — template TUI: `layout/` (spec→frames responsive), `flow/` (grafo secuencial
  con route condicional + walker reversible sobre infra `State`), `interact/`
  (toggle/choice/input/confirm/report + registry frozen), `templates/standard` (dibujo original:
  cabecero pixel `Mast`, steps 1 línea, barra `keys`).
- **Sistema "pages"**: `flow/page.py` (`Step`→`Page`: `requires`/`produces` enpaths del state,
  `condition` gate de colocación, `on_commit` hook de dominio), `flow/pages.py` (`PagesBuilder`:
  adición dinámica en orden de montaje, valida cada page contra un *shadow* `State` sembrado por lo
  producido; un desorden muere en `add()` con `PageStructureError`, nunca mid-walk), `flow/state.py`
  (`has`/`seed` por item-access, sin auto-vivificar). `flow/walk.py`: `advance` dispara `on_commit`
  antes de `route`. Capas tach sin cambiar (todo dentro de `e_tui.flow`/`models`).
- **Viewer** (`app.py` `WizardApp(LayoutApp)`): page actual→`interact.build`→`content`, trail→`steps`
  (`Static`, `markup=False`), y barra `keys` = **pista de 1 fila** (no botones: miden 3 filas y se recortaban).
  Navegación **por teclado** vía `BINDINGS`: `enter` accept (priority), `backspace`/`escape` back, `ctrl+r`
  reset, `ctrl+q` quit → `Walker` + `Move` por `match-case`. Selección con flechas+`space` (o ratón).
  Seam `result: State→widgets` que el viewer monta al `Finished`.
- **Fixes de layout/interaction** (2026-10-05): (a) `[System]` y el JSON se comían como **markup Rich** →
  `markup=False`; (b) `fill("content")` hacía `remove_children()` y **borraba el sub-frame `steps`** → `fill`
  quirúrgico por clase `slot-content`; (c) botones en franja de 1 fila → teclas.
- **App fake reutilizable** (capa `examples` arriba del template): `demo.py` pliega `pages/` (un módulo por
  page: `system db modules confirm report`) en orden de montaje, camina y emite un `AppBlueprint` (JSON vía
  `eserde`) al terminar. `make run` / `etui` lo abre interactivo (radios `api/cli/tui` + barra). Copiable tal
  cual como host real; `e_tui.pages`/`demo`/`__main__` en capa `examples`, nunca al revés.
- `projects/python/common` — `infra/config/theme.py` (3 colores) y `ops/snap.py` (GallerySnap);
  cli/api/tui los excluyen al materializar. Snapshots SVG aceptados visualmente.
- Textual 8.2.8 · syrupy≥6.1 por override · PTS 1.1.0.

## Pendiente

1. **management renovado sobre el tui** (hecho 2026-10-16): `management` materializa `e_tui` (`make ui` /
   `ui-check`, ley igual que `ops`) y su wizard es un `WizardApp` con secciones `system · name · tools-<area> ·
   options · ci · dest · confirm`; respuestas en `FlowState.data`, draft = `Session` serializable con resume.
   `Group.INFRA`→`Group.STACK`. Pendiente fino: re-pinned del action `qwen-code` (flota en main), y página de
   `--drop` por dependencia de units al estilo `requires` del graph.
2. **`infra/` completada** (2026-10-16): mapa `features.yml` + jobs atómicos + setup por feature +
   ensamblado determinista en management + `make common-check` + contract test generado. Pendiente: usarlo en
   repos reales (e-taxis/e-voice migran de workflow propio a `ci.defaults.yml` cuando toque).

3. **Kinds que faltan** cuando la app lo pida: slider, list multi-selección, progress, `CompositeSpec`
   (varios objetos por page). Cada uno = un `Spec` + una fila en `registry` + un módulo en `interact`.
4. Menor: README raíz ya lista `infra/`; renombrar snapshots `.raw`→`.svg` si molesta.

## Reglas del juego

- Capas tach: app ▸ templates ▸ flow ▸ interact  layout ▸ … ▸ models. `flow` no ve Textual;
  `interact` no ve `flow`; se tocan solo en `Spec/Commit/ObjectPort`.
- Dispatch, no `if`. Tests espejan `src/`. Cov 100 %. La infra común solo se edita en `projects/python/common`.
- Comprobar: `make check` en `projects/python/tui` (y `infra`/`cli`/`api` si se toca `projects/python/common`).
