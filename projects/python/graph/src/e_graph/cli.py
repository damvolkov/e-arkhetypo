"""e-graph cli: the DARTS static checks, deterministic — and the lab to see what the orchestrator mounts.

    e-graph darts check [--pipeline doc] [--json]       every law of every pipeline: exit 0 clean, 1 broken
    e-graph darts plan <pipeline> <section> [--json]    how a section would run, without running it
    e-graph lab list                                    every mounted section: specs, steps, planned calls
    e-graph lab graph <pipeline> [<section>]            the pipeline's graph, or a section's spec-graph
              [--draw tree|dot|svg] [--out file]        tree in the terminal; dot and svg via rustworkx
    e-graph lab simulate <pipeline> <section>           the pipeline rehearsed up to the section
              [--data key=value ...] [--case file]      the run's data (values read as JSON when they parse)
              [--live] [--out dir] [--json]             live calls the model; --out keeps every payload

`check` mounts every pipeline's graph (the registry's sweep), then judges the whole tree with
`SystemDiscover`: specs, runners, wiki, nodes. Errors fail it; warnings (an idle tool) are reported and
let through. `--json` prints the `Report` as one JSON document, for a machine to read. `lab` draws and
rehearses through `SectionLab`, the same object the API's `/api/specs` routes serve."""

import io
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum, auto
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import anyio
import eserde
import msgspec
from cyclopts import App
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from adapters.docling import DoclingAdapter
from core.logger import ELogger
from core.settings import settings as st
from core.settings.darts import DartsSettings
from e_graph.instrument.state import InfraState, ProcessorsState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.dartsops import DartsOps
from e_graph.logic.discover import SpecDiscover, SystemDiscover
from e_graph.logic.errors import CatalogError, Rule, RuleError, Severity
from e_graph.logic.models import AgentCall, Breach, Report, SectionMap, SectionPlan, Simulation
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.orchestrator.lab import SectionLab
from e_graph.logic.orchestrator.plan import DagPlan
from e_graph.models.section import Section
from e_graph.pipelines.base import PipelineRegistry
from processors.doc import DocProcessor

CONSOLE: Final[Console] = Console(soft_wrap=True)
EXIT: Final[dict[bool, int]] = {True: 0, False: 1}
COLORS: Final[dict[Severity, str]] = {Severity.ERROR: "red", Severity.WARNING: "yellow"}

app = App(name="e-graph", help="e-graph: LangGraph pipelines run by DARTS.", version=version("e-graph"))
darts = App(name="darts", help="DARTS static checks: specs, runners and nodes, judged without running anything.")
lab = App(
    name="lab", help="The orchestrator's lab: list sections, draw graphs, rehearse a section and read its agent calls."
)
app.command(darts)
app.command(lab)


class Drawing(StrEnum):
    """How `lab graph` draws: a tree in the terminal, DOT text, or SVG."""

    TREE = auto()
    DOT = auto()
    SVG = auto()


##### RENDERING #####
def render_breaches(breaches: tuple[Breach, ...]) -> Table:
    """Every breach as one row: severity, law, subject, what is wrong."""
    table = Table("severity", "rule", "subject", "detail", box=None, pad_edge=False)
    _ = [table.add_row(f"[{COLORS[b.severity]}]{b.severity}[/]", str(b.rule), b.subject, b.detail) for b in breaches]
    return table


def render_plan(plan: SectionPlan) -> Table:
    """Each step as one row: what runs alone, what is fused into which call."""
    table = Table("step", "deterministic", "fused calls", box=None, pad_edge=False)
    _ = [
        table.add_row(
            str(step.index),
            ", ".join(step.deterministic) or "-",
            " · ".join(f"{call.tier}: {', '.join(call.specs)}" for call in step.fused) or "-",
        )
        for step in plan.steps
    ]
    return table


def render_json(document: Any) -> None:
    CONSOLE.out(msgspec.json.encode(document).decode(), highlight=False)


def render_map(mapped: SectionMap) -> Tree:
    """A section's spec-graph as a tree: steps, then each spec with its kind, call, dependencies and runners."""
    tree = Tree(f"[bold]{mapped.pipeline} · {mapped.section}[/] — {len(mapped.nodes)} specs, {mapped.ranks} steps")
    depends = {point.id: [link.source for link in mapped.edges if link.target == point.id] for point in mapped.nodes}
    steps = {rank: tree.add(f"step {rank}") for rank in range(mapped.ranks)}
    specs = {
        point.id: steps[point.rank].add(
            f"[cyan]{point.id}[/] {point.kind}"
            + (f" · {point.tier} · call-{point.call}" if point.call >= 0 else "")
            + (f" · [yellow]fallback of {point.rescues}[/]" if point.rescues else "")
            + (f" · reads {', '.join(depends[point.id])}" if depends[point.id] and not point.rescues else "")
        )
        for point in mapped.nodes
    }
    _ = [specs[point.id].add(f"{slot}: {ref}") for point in mapped.nodes for slot, ref in point.runners.items()]
    _ = [
        tree.add(
            f"[magenta]call-{group.index}[/] · {group.tier} · {', '.join(group.specs)} · ~{group.weight}/{group.budget} tokens"
        )
        for group in mapped.calls
    ]
    return tree


def render_call(call: AgentCall, route: str) -> Panel:
    """One agent call as a panel: where it goes, what each spec weighs, the instructions and the prompt's head."""
    weights = " · ".join(f"{name} ~{weight}" for name, weight in call.weights.items())
    head = "\n".join(call.prompt.splitlines()[:12])
    body = (
        f"[bold]specs[/] {weights} of {call.budget}\n[bold]route[/] {route}\n\n{call.instructions}\n\n[dim]{head}\n…[/]"
    )
    title = f"call-{call.index} · step {call.step} · {call.tier} · prompt {len(call.prompt)} chars"
    return Panel(body, title=title, title_align="left", border_style="magenta")


def render_simulation(simulation: Simulation) -> None:
    """Every section's run, the target's agent calls, what the target wrote."""
    mode = "live" if simulation.live else "rehearsed"
    CONSOLE.print(f"[bold]{simulation.pipeline} · {simulation.section}[/] {mode} in {simulation.latency_ms:.0f} ms")
    _ = [CONSOLE.print(f"  {run.section}: {run.summary}") for run in simulation.runs]
    routes = {
        tier: route.error or f"{route.provider}/{route.model} {route.api_base}"
        for tier, route in simulation.routes.items()
    }
    _ = [CONSOLE.print(render_call(call, routes.get(str(call.tier), "unresolved"))) for call in simulation.calls]
    CONSOLE.print_json(msgspec.json.encode(simulation.written).decode())


def keep_simulation(simulation: Simulation, out: Path) -> None:
    """Every payload whole, one file per part: what the agent was sent, exactly."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "simulation.json").write_bytes(msgspec.json.format(msgspec.json.encode(simulation)))
    _ = [
        (out / f"call-{call.index}.{part}").write_text(text)
        for call in simulation.calls
        for part, text in (
            ("instructions.md", call.instructions),
            ("prompt.md", call.prompt),
            ("schema.json", msgspec.json.format(msgspec.json.encode(call.schema)).decode()),
        )
    ]


def read_data(data: tuple[str, ...], case: Path | None) -> dict[str, Any]:
    """The run's data: a case file's `data` (or the whole file), then each `key=value`, values read as JSON when they parse."""
    loaded = eserde.load(case) if case is not None else {}
    seeded = loaded.get("data", loaded) if isinstance(loaded, dict) else {}
    pairs = dict(pair.partition("=")[::2] for pair in data)
    return {**seeded, **{key: read_value(value) for key, value in pairs.items()}}


def read_value(text: str) -> Any:
    """A command-line value as JSON when it parses (`3`, `true`, `[1]`), else as the text it is."""
    try:
        return msgspec.json.decode(text)
    except msgspec.DecodeError:
        return text


class LiveStream(io.TextIOBase):
    """A text stream that is whomever `sys.stderr` is at write time: the CLI binds the logger once, a host
    embedding it (or a test capturing its fds) may swap the real stream afterwards, and no write is ever
    made to a file the CLI does not own."""

    mode = "w"
    name = "<stderr>"
    encoding = "utf-8"
    errors = "strict"
    line_buffering = True
    write_through = False
    newlines = None

    @property
    def buffer(self) -> Any:
        """The protocol's view of the stream underneath: whatever `sys.stderr` wraps, live."""
        return sys.stderr.buffer

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        """Flush whoever holds the error now — a finalizer may run while the host is already tearing down."""
        match getattr(sys, "stderr", None):
            case None:
                return
            case stream:
                stream.flush()


@asynccontextmanager
async def system() -> AsyncIterator[InfraState]:
    """The engines a rehearsal runs on, as the app assembles them: docling, the hybrid processor, the agent.
    Their logs go to stderr: stdout is the command's answer, JSON included."""
    ### typeshed's TextIO is io.TextIOBase by alias: it checks nothing, while beartype demands the full
    ### protocol member by member — this class is built for the latter and cannot name it to the former.
    ELogger.setup(env=st.app.app_env, stream=LiveStream())  # ty: ignore[invalid-argument-type]
    graphs = await PipelineRegistry().build()
    async with DoclingAdapter() as docling, AgnosticAgent() as agent:
        yield InfraState(
            adapters=None,  # ty: ignore[invalid-argument-type] — no runner reaches an adapter but through a processor
            processors=ProcessorsState(doc=DocProcessor(docling)),
            agent=agent,
            orchestrator=OrchestratorCore(),
            telemetry=InstrumentTelemetry(),
            graphs=MappingProxyType(dict(graphs)),
        )


async def mounted(pipeline: str, section: Section | None) -> tuple[SectionLab, str]:
    """The lab over every pipeline, and why the pipeline or section asked for cannot be drawn (empty when it can)."""
    graphs = await PipelineRegistry().build()
    known = graphs.get(pipeline)
    reason = (
        f"no graph mounts this pipeline: {sorted(graphs)}"
        if known is None
        else f"{pipeline} mounts no {section}: {sorted(map(str, known.sections))}"
        if section is not None and section not in known.sections
        else ""
    )
    return SectionLab(OrchestratorCore(), graphs), reason


##### COMMANDS #####
@darts.command
async def check(*, pipeline: tuple[str, ...] = (), json: bool = False) -> int:
    """Judge every pipeline (or each `--pipeline`) against every DARTS law: exit 0 clean, 1 on any error.

    Parameters
    ----------
    pipeline
        Audit only these pipelines; the system's own laws are judged anyway.
    json
        Print the report as JSON instead of a table.
    """
    report: Report = await SystemDiscover(await PipelineRegistry().mounts()).check(frozenset(pipeline))
    verdict = "[green]clean[/]" if report.ok else f"[red]{len(report.errors)} errors[/]"
    line = (
        f"{verdict} · {len(report.warnings)} warnings · {', '.join(report.pipelines) or 'no pipelines'}"
        f" · {report.sections} sections · {report.specs} specs"
    )
    match (json, report.breaches):
        case (True, _):
            render_json({"ok": report.ok, **msgspec.to_builtins(report)})
        case (_, ()):
            CONSOLE.print(line)
        case _:
            CONSOLE.print(render_breaches(report.breaches), line, sep="\n")
    return EXIT[report.ok]


@darts.command
async def plan(pipeline: str, section: Section, *, json: bool = False) -> int:
    """Show how a pipeline's section would run — steps and fused calls — without running it.

    Parameters
    ----------
    pipeline
        The pipeline, as its folder under `pipelines/` names it.
    section
        The section to plan.
    json
        Print the plan as JSON instead of a table.
    """
    mounts = await PipelineRegistry().mounts()
    try:
        match pipeline in mounts:
            case True:
                planned = DagPlan.build(await SpecDiscover(pipeline).catalog(section), DartsSettings())
            case _:
                unknown = RuleError(Rule.PIPELINE, pipeline, f"no graph mounts this pipeline: {sorted(mounts)}")
                raise CatalogError(pipeline, [unknown])
    except CatalogError as broken:
        breaches = tuple(
            Breach(rule=e.rule, subject=e.subject, detail=e.detail, severity=e.severity) for e in broken.breaches
        )
        match json:
            case True:
                render_json({"ok": False, "breaches": msgspec.to_builtins(breaches)})
            case _:
                CONSOLE.print(render_breaches(breaches))
        return EXIT[False]
    match json:
        case True:
            render_json(planned)
        case _:
            CONSOLE.print(render_plan(planned))
    return EXIT[True]


@lab.command(name="list")
async def listing(*, json: bool = False) -> int:
    """Every mounted section of every pipeline: how many specs, steps and planned agent calls.

    Parameters
    ----------
    json
        Print the sections as JSON instead of a table.
    """
    sections = await SectionLab(OrchestratorCore(), await PipelineRegistry().build()).sections()
    table = Table("pipeline", "section", "specs", "steps", "calls", box=None, pad_edge=False)
    _ = [table.add_row(i.pipeline, str(i.section), str(i.specs), str(i.steps), str(i.calls)) for i in sections]
    match json:
        case True:
            render_json(sections)
        case _:
            CONSOLE.print(table)
    return EXIT[True]


@lab.command
async def graph(
    pipeline: str, section: Section | None = None, *, draw: Drawing = Drawing.TREE, out: Path | None = None
) -> int:
    """Draw a pipeline's LangGraph graph, or one section's spec-graph as the orchestrator will run it.

    Parameters
    ----------
    pipeline
        The pipeline, as its folder under `pipelines/` names it.
    section
        The section whose spec-graph to draw; the pipeline's own graph without one.
    draw
        tree in the terminal, dot (rustworkx), or svg (Graphviz on wasmtime).
    out
        Write the drawing to this file instead of the terminal.
    """
    found, reason = await mounted(pipeline, section)
    match (reason, section):
        case ("", None):
            dot = found.pipeline_dot((await PipelineRegistry().build())[pipeline])
            tree = Tree(f"[bold]{pipeline}[/] — the pipeline's graph: draw it with --format dot|svg")
        case ("", Section() as chosen):
            mapped = await found.map(pipeline, chosen)
            dot, tree = found.dot(mapped), render_map(mapped)
        case _:
            CONSOLE.print(f"[red]{reason}[/]")
            return EXIT[False]
    drawings = {Drawing.TREE: lambda: tree, Drawing.DOT: lambda: dot, Drawing.SVG: lambda: SectionLab.svg(dot)}
    drawn = drawings[draw]()
    match (out, draw):
        case (None, Drawing.TREE):
            CONSOLE.print(drawn)
        case (None, _):
            CONSOLE.out(str(drawn), highlight=False)
        case _:
            await anyio.Path(str(out)).write_text(str(drawn))
            CONSOLE.print(f"drawn into {out}")
    return EXIT[True]


@darts.command
def contract(*, out: Path | None = None) -> int:
    """The whole DARTS grammar and every law, as one JSON contract: what a coder reads before touching specs.

    Parameters
    ----------
    out
        Write the contract to this file instead of the terminal.
    """
    contract_: dict[str, Any] = DartsOps(OrchestratorCore()).contract()
    contract_json = msgspec.json.format(msgspec.json.encode(contract_), indent=2).decode()
    match out:
        case None:
            render_json(contract_)
        case _:
            out.write_text(contract_json)
            CONSOLE.print(f"contract written to {out}")
    return EXIT[True]


@darts.command
async def probe(*, json: bool = False) -> int:
    """Ask every tier the trivially structured question, timed: an unreachable tier is an infra signal.

    Parameters
    ----------
    json
        Print {tier: ms-or-error} as JSON instead of a table.
    """
    async with AgnosticAgent() as agent:
        probes = await DartsOps(OrchestratorCore()).probe(agent)
    match json:
        case True:
            render_json(probes)
        case _:
            for tier, answer in probes.items():
                match answer:
                    case float() as ms:
                        CONSOLE.print(f"[green]{tier}[/] · {ms:.0f} ms")
                    case _:
                        CONSOLE.print(f"[red]{tier}[/] · {answer}")
    return EXIT[all(isinstance(answer, float) for answer in probes.values())]


@darts.command
async def evaluate(
    pipeline: str,
    *,
    data: tuple[str, ...] = (),
    case: Path | None = None,
    expect: tuple[str, ...] = (),
    out: Path | None = None,
) -> int:
    """Run the pipeline's sections over the data and print the signals the reading left: exit 0 green, 1 readout, 2 infra.

    Parameters
    ----------
    pipeline
        The pipeline, as its folder under `pipelines/` names it.
    data
        Run data as `key=value` (JSON when it parses): the seed the first sections read.
    case
        A YAML/JSON file of run data, merged under the pairs given.
    expect
        Pinned readings to hold: `<section>/<spec>.<dotted.path>==<json>`, one per flag.
    out
        Also write the full Readout as JSON here.
    """
    _, reason = await mounted(pipeline, None)
    match reason:
        case "":
            pass
        case _:
            CONSOLE.print(f"[red]{reason}[/]")
            return EXIT[False]
    run_data = read_data(data, case)
    async with system() as infra:
        readout = await DartsOps(infra.orchestrator).evaluate(
            pipeline, run_data, infra, infra.agent, expectations=expect
        )
    match out:
        case None:
            pass
        case _:
            await anyio.Path(str(out)).write_text(msgspec.json.format(msgspec.json.encode(readout), indent=2).decode())
    for signal in readout.signals:
        CONSOLE.print(
            f"[red]{signal.kind}[/] {signal.where} · {signal.observed}"
            + (f" ≠ {signal.expected}" if signal.expected else f" · {signal.detail}")
        )
    match any(signal.kind == "infra" for signal in readout.signals):
        case True:
            CONSOLE.print("[yellow]infra[/] · a tier did not answer: no reading is to blame, nothing to patch")
            return 2
        case _:
            CONSOLE.print(
                f"[green]readout[/] · {pipeline} · {len(readout.summaries)} sections · no signals"
                if readout.ok
                else f"[red]readout[/] · {len(readout.signals)} signals"
            )
    return EXIT[readout.ok]


@lab.command
async def simulate(
    pipeline: str,
    section: Section,
    *,
    data: tuple[str, ...] = (),
    case: Path | None = None,
    live: bool = False,
    out: Path | None = None,
    json: bool = False,
) -> int:
    """Rehearse the pipeline up to a section and read every agent call the section issues, whole.

    Parameters
    ----------
    pipeline
        The pipeline, as its folder under `pipelines/` names it.
    section
        The section to rehearse; every earlier section of the graph runs first, once.
    data
        The run's data as key=value pairs (`source=tests/resources/documents/filings/aapl-10k-2025.pdf`).
    case
        A YAML or JSON case file whose `data` (or whole content) seeds the run.
    live
        Call the real model instead of answering each spec from its example or its schema.
    out
        Keep every payload in this folder: simulation.json and each call's instructions, prompt and schema.
    json
        Print the simulation as JSON.
    """
    _, reason = await mounted(pipeline, section)
    match reason:
        case "":
            pass
        case _:
            CONSOLE.print(f"[red]{reason}[/]")
            return EXIT[False]
    async with system() as infra:
        found = SectionLab(infra.orchestrator, infra.graphs)
        simulation = await found.simulate(pipeline, section, read_data(data, case), infra=infra, live=live)
    match out:
        case Path():
            keep_simulation(simulation, out)
        case _:
            pass
    match json:
        case True:
            render_json(simulation)
        case _:
            render_simulation(simulation)
    return EXIT[True]


def main() -> None:
    """The `e-graph` script: the command line, tokens taken explicitly."""
    app(sys.argv[1:])
