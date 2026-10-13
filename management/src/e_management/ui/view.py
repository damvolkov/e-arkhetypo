"""ui.view: pure renderers — a Plan or a step log becomes text the screens show, nothing else."""

from typing import TYPE_CHECKING

from rich.text import Text

from e_management.core.plan import Action, Copy, Materialize, PrunePaths, PruneTexts, Rename

if TYPE_CHECKING:
    from collections.abc import Sequence

    from e_management.core.plan import Plan
    from e_management.models.graph import Graph

##### DEFAULTS #####
TITLE: dict[str, str] = {
    "Copy": "copy template",
    "Materialize": "materialize",
    "PrunePaths": "remove paths",
    "PruneTexts": "rewrite files",
    "Rename": "rename",
}
TRAIL: dict[str, str] = {"done": "#4f6b9a", "here": "bold #e6eeff on #1d3a8a", "next": "#3a4458"}
STATE: dict[str, tuple[str, str]] = {
    "locked": ("●", "bold #8fb2ff"),
    "detachable": ("○", "#e3b341"),
    "optional": ("·", "dim"),
}


def _state(unit) -> str:
    return "locked" if unit.locked else "detachable" if unit.detachable else "optional"


def _nid(key: str) -> str:
    return key.replace("/", "_").replace("-", "_")


def _mermaid(system: str, graph: Graph) -> str:
    """One bottom-up Mermaid graph: a node per unit grouped by level, an edge per import, colored by state."""
    lines = ["graph BT", f"  subgraph SYS['{system.upper()} · {len(graph.units)} unidades']"]
    levels: dict[int, list] = {}
    for unit in graph.units:
        levels.setdefault(unit.level, []).append(unit)
    for level in sorted(levels):
        lines.append(f"    subgraph L{level}['Nivel {level}']")
        lines.extend(
            f'      {_nid(u.key)}["{u.key}<br/><i>{_state(u).upper()}</i>"]'
            for u in sorted(levels[level], key=lambda u: u.key)
        )
        lines.append("    end")
    lines.append("  end")
    lines.extend(f"  {_nid(u.key)} --> {_nid(d)}" for u in graph.units for d in u.deps)
    lines.extend(f"  class {_nid(u.key)} {_state(u)};" for u in graph.units)
    lines += [
        "  classDef locked fill:#1f6feb,stroke:#58a6ff,color:#fff;",
        "  classDef detachable fill:#d29922,stroke:#e3b341,color:#000;",
        "  classDef optional fill:#30363d,stroke:#484f58,color:#8b949e;",
    ]
    return "\n".join(lines)


def render_map_html(graphs: Sequence[tuple[str, Graph]]) -> str:
    """A self-contained HTML page rendering every system's dependency map via the Mermaid CDN."""
    diagrams = "\n".join(
        f'<h2>{system}</h2><div class="mermaid">{_mermaid(system, graph)}</div>' for system, graph in graphs
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>e-templates · dependency map</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>body{{font:14px system-ui;background:#0d1117;color:#c9d1d9;margin:2rem}}h1{{font-size:1.1rem}}h2{{color:#6f9bff}}
.legend span{{display:inline-block;padding:2px 10px;margin:0 8px 1rem 0;border-radius:6px}}
.mermaid{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:1rem;margin:1rem 0}}</style>
<script>mermaid.initialize({{startOnLoad:true,theme:'dark'}});</script></head><body>
<h1>e-templates · dependency map — AST + libcst, niveles graphlib, estado derivado de raíz</h1>
<div class="legend"><span style="background:#1f6feb;color:#fff">● mandatory</span><span style="background:#d29922;color:#000">○ detachable</span><span style="background:#30363d;color:#8b949e">· optional</span></div>
{diagrams}
</body></html>"""


def render_graph(graph: Graph | None) -> Text:
    """The leveled dependency map: one block per level, a colored node per unit with the edges it imports."""
    text = Text()
    if graph is None:
        text.append("no template chosen yet — pick one to inspect its dependency map", style="dim")
        return text
    levels: dict[int, list] = {}
    for unit in graph.units:
        levels.setdefault(unit.level, []).append(unit)
    text.append(f"{graph.system}  ·  {len(graph.units)} units  ·  {len(graph.areas)} areas\n", style="bold #6f9bff")
    text.append("A → B imports B   ·   ● mandatory  ○ detachable  · optional\n\n", style="dim")
    for level in sorted(levels):
        text.append(f"  level {level}\n", style="#56627a")
        for unit in sorted(levels[level], key=lambda u: u.key):
            mark, style = STATE[_state(unit)]
            imports = ", ".join(sorted(dep.rsplit("/", 1)[-1] for dep in unit.deps)) or "—"
            needed = ", ".join(sorted(user.rsplit("/", 1)[-1] for user in unit.dependents)) or "—"
            text.append(f"    {mark} {unit.key:<20}", style=style)
            text.append(f"  imports→ {imports:<22}", style="dim")
            text.append(f"  ← needed by {needed}\n", style="dim")
    return text


def render_plan(plan: Plan) -> str:
    """One line per action: what the engine will do when the user confirms."""
    lines = [f"project   {plan.brand}   ·   package {plan.package}", "", "the engine will, in order:"]
    lines += [f"  · {line}" for line in (_line(action) for action in plan.actions)]
    return "\n".join(lines)


def render_trail(steps: tuple[str, ...], seen: tuple[str, ...], here: str) -> Text:
    """The flow as one line: confirmed steps checked, the current one lit, the rest dim."""
    trail = Text(no_wrap=True, overflow="ellipsis")
    for index, step in enumerate(steps):
        state = "here" if step == here else "done" if step in seen else "next"
        mark = "✓ " if state == "done" else ""
        trail.append("  →  " if index else " ", style=TRAIL["next"])
        trail.append(f" {mark}{step.removeprefix('common-')} ", style=TRAIL[state])
    return trail


def _line(action: Action) -> str:
    match action:
        case Copy(src=src):
            return f"{TITLE['Copy']}  {src}"
        case Materialize(src=src, dst=dst):
            return f"{TITLE['Materialize']}  {src} → {dst}"
        case PrunePaths(paths=paths):
            return f"{TITLE['PrunePaths']}  {', '.join(paths)}"
        case PruneTexts(prunes=prunes):
            files = sorted({prune.file for prune in prunes})
            return f"{TITLE['PruneTexts']}  {len(prunes)} rules over {', '.join(files)}"
        case Rename(rules=rules):
            return f"{TITLE['Rename']}  " + ", ".join(f"{rule.frm} → {rule.to}" for rule in rules)
