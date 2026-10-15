"""tests/unit: cli — `e-graph darts check|plan` over the real pipelines: deterministic exit codes, table or JSON."""

import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from e_graph import cli
from e_graph.cli import LiveStream, app, keep_simulation, main, read_value, render_simulation
from e_graph.logic.errors import Rule, Severity
from e_graph.logic.models import AgentCall, Breach, Readout, Report, Signal, Simulation, Tier
from e_graph.models.section import Section

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from pytest_mock import MockerFixture

BROKEN = Report(
    pipelines=("doc",),
    sections=1,
    specs=2,
    breaches=(
        Breach(rule=Rule.ORPHAN, subject="owned/retired", detail="deprecated runner"),
        Breach(
            rule=Rule.IDLE, subject="agnostic/table/figure", detail="no spec plugs this tool", severity=Severity.WARNING
        ),
    ),
)


def invoke(*tokens: str) -> int:
    with pytest.raises(SystemExit) as exited:
        app(list(tokens))
    return int(exited.value.code or 0)


@pytest.fixture
def stub_agent(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A tier set that answers (or does not): the probe never touches the network in a unit test."""
    state: dict[str, Any] = {"down": set()}

    class Stub:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def __aenter__(self) -> Stub:
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

        async def run(self, instructions: str, prompt: str, output: Any, *, endpoint: Any = None, **_: Any) -> Any:
            match str(endpoint) in state["down"]:
                case True:
                    msg = "asleep"
                    raise ConnectionError(msg)
                case _:
                    return None

    monkeypatch.setattr(cli, "AgnosticAgent", Stub)
    return state


def test_the_live_stream_flushes_only_when_a_stderr_still_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """At interpreter teardown `sys.stderr` can already be gone: the finalizer must shrug, not raise.
    The patch lands inside the test body: pytest's own capture reinstalls the stream at fixture time."""
    monkeypatch.setattr(sys, "stderr", None, raising=False)
    cli.LiveStream().flush()


def test_contract_json_is_the_law_mirror(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("darts", "contract") == 0
    contract = json.loads(capfd.readouterr().out)
    assert len(contract["laws"]) == len(tuple(Rule))
    assert (contract["sections"]["extract"], contract["slots"]["pre"]) == ("EXT", "pre_run")


def test_contract_to_a_file_is_the_same_mirror(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "contract.json"
    assert invoke("darts", "contract", "--out", str(target)) == 0
    assert json.loads(target.read_text())["budget"]["darts_concurrency"] >= 1


def test_probe_times_every_answered_tier(stub_agent: dict[str, Any], capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("darts", "probe", "--json") == 0
    assert all(isinstance(ms, float) for ms in json.loads(capfd.readouterr().out).values())


def test_probe_fails_when_a_tier_is_asleep(stub_agent: dict[str, Any], capfd: pytest.CaptureFixture[str]) -> None:
    stub_agent["down"] = {"high"}
    assert invoke("darts", "probe") == 1
    lines = capfd.readouterr().out
    assert "high · asleep" in lines.replace("[red]", "").replace("[/]", "") or "ConnectionError" in lines
    assert invoke("darts", "probe", "--json") == 1
    assert json.loads(capfd.readouterr().out)["high"].startswith("ConnectionError")


def test_evaluate_refuses_what_no_graph_mounts(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("darts", "evaluate", "nope") == 1


@pytest.mark.parametrize(("kind", "expected"), [("", 0), ("spec", 1), ("infra", 2)])
def test_evaluate_exit_codes_come_from_the_readout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str, expected: int
) -> None:
    """0 green, 1 readout signals, 2 an unanswered tier: the loop's continue/stop decision, as an exit code."""
    signals = () if not kind else (Signal(kind=kind, where="extract/EXT-x", observed=kind),)

    @asynccontextmanager
    async def fake_system() -> AsyncIterator[Any]:
        yield SimpleNamespace(orchestrator=None, agent=None)

    class FakeOps:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def evaluate(self, *_: Any, **__: Any) -> Readout:
            return Readout(pipeline="doc", mode="live" if kind != "infra" else "infra", signals=signals)

    monkeypatch.setattr(cli, "system", fake_system)
    monkeypatch.setattr(cli, "DartsOps", FakeOps)
    assert invoke("darts", "evaluate", "doc", "--data", "document=invoice") == expected
    match expected:
        case 1:
            target = tmp_path / "signal.json"
            assert invoke("darts", "evaluate", "doc", "--data", "document=invoice", "--out", str(target)) == 1
            assert json.loads(target.read_text())["signals"][0]["kind"] == "spec"


def test_check_passes_the_real_system(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("darts", "check") == 0
    assert capfd.readouterr().out.strip() == "clean · 0 warnings · doc, filing, note · 16 sections · 60 specs"


def test_check_as_json_is_the_report(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("darts", "check", "--json", "--pipeline", "filing") == 0
    report: dict[str, Any] = json.loads(capfd.readouterr().out)
    assert (report["ok"], report["pipelines"], report["specs"], report["breaches"]) == (True, ["filing"], 7, [])


def test_check_fails_on_errors_never_on_warnings(capfd: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    mocker.patch("e_graph.logic.discover.SystemDiscover.check", return_value=BROKEN)
    assert invoke("darts", "check") == 1
    out = capfd.readouterr().out
    assert "owned/retired" in out
    assert "1 errors · 1 warnings · doc · 1 sections · 2 specs" in out
    mocker.patch(
        "e_graph.logic.discover.SystemDiscover.check",
        return_value=Report(pipelines=(), sections=0, specs=0, breaches=BROKEN.breaches[1:]),
    )
    assert invoke("darts", "check") == 0


def test_plan_draws_the_steps(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("darts", "plan", "filing", "extract") == 0
    assert "medium: EXT-balance, EXT-cover, EXT-income" in capfd.readouterr().out
    assert invoke("darts", "plan", "doc", "extract", "--json") == 0
    assert json.loads(capfd.readouterr().out)["steps"] == [{"index": 0, "deterministic": ["EXT-amount"], "fused": []}]


@pytest.mark.parametrize("json_flag", [(), ("--json",)], ids=["table", "json"])
def test_plan_of_an_unknown_pipeline_fails(capfd: pytest.CaptureFixture[str], json_flag: tuple[str, ...]) -> None:
    assert invoke("darts", "plan", "ghost", "extract", *json_flag) == 1
    assert "no graph mounts this pipeline" in capfd.readouterr().out


def test_main_reads_the_command_line(monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["e-graph", "darts", "plan", "doc", "report"])
    with pytest.raises(SystemExit) as exited:
        main()
    assert (exited.value.code, "REP-serial" in capfd.readouterr().out) == (0, True)


##### LAB #####
def test_lab_lists_every_mounted_section(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("lab", "list") == 0
    assert "filing    extract    3      1      1" in capfd.readouterr().out
    assert invoke("lab", "list", "--json") == 0
    sections = json.loads(capfd.readouterr().out)
    assert len(sections) == 16
    assert next(entry for entry in sections if entry["pipeline"] == "note" and entry["section"] == "extract") == {
        "pipeline": "note",
        "section": "extract",
        "specs": 22,
        "steps": 3,
        "calls": 5,
    }


def test_lab_draws_a_section_as_a_tree(capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke("lab", "graph", "filing", "extract") == 0
    out = capfd.readouterr().out
    assert "filing · extract — 3 specs, 1 steps" in out
    assert "post: agnostic/number/scale" in out
    assert "call-0 · medium · EXT-balance, EXT-cover, EXT-income" in out


def test_lab_draws_dot_and_svg(capfd: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert invoke("lab", "graph", "doc", "extract", "--draw", "dot") == 0
    assert capfd.readouterr().out.startswith("digraph {")
    assert invoke("lab", "graph", "doc", "--draw", "svg", "--out", str(tmp_path / "doc.svg")) == 0
    assert "<svg" in (tmp_path / "doc.svg").read_text()
    assert invoke("lab", "graph", "doc") == 0
    assert "the pipeline's graph" in capfd.readouterr().out


@pytest.mark.parametrize(
    ("tokens", "reason"),
    [
        (("lab", "graph", "ghost"), "no graph mounts this pipeline"),
        (("lab", "graph", "filing", "validate"), "filing mounts no validate"),
        (("lab", "simulate", "doc", "audit"), "doc mounts no audit"),
    ],
)
def test_lab_refuses_what_no_graph_mounts(
    capfd: pytest.CaptureFixture[str], tokens: tuple[str, ...], reason: str
) -> None:
    assert invoke(*tokens) == 1
    assert reason in capfd.readouterr().out


def test_lab_rehearses_a_section_and_keeps_its_payloads(capfd: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    case = tmp_path / "case.yaml"
    case.write_text("data:\n  document: invoice 5 total 9.75\n")
    out = tmp_path / "sim"
    assert (
        invoke("lab", "simulate", "doc", "report", "--case", str(case), "--data", "format=yaml", "--out", str(out)) == 0
    )
    printed = capfd.readouterr().out
    assert "doc · report rehearsed" in printed
    assert "kind: invoice" in printed
    assert json.loads((out / "simulation.json").read_text())["section"] == "report"
    assert invoke("lab", "simulate", "doc", "ingest", "--data", "document=receipt", "--json") == 0
    ### the JSON is the last line: a test process's logger was bound to stdout before the command ran.
    assert json.loads(capfd.readouterr().out.splitlines()[-1])["written"]["ING-document"]["text"] == "receipt"


def test_lab_keeps_every_call_part(tmp_path: Path) -> None:
    call = AgentCall(
        index=0,
        step=0,
        tier=Tier.MEDIUM,
        specs=("EXT-a",),
        instructions="Read.",
        prompt="page",
        schema={"type": "object"},
    )
    simulation = Simulation(
        pipeline="filing",
        section=Section.EXTRACT,
        live=False,
        runs=(),
        calls=(call,),
        routes={},
        written={},
        latency_ms=1.0,
    )
    keep_simulation(simulation, tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "call-0.instructions.md",
        "call-0.prompt.md",
        "call-0.schema.json",
        "simulation.json",
    ]
    assert (tmp_path / "call-0.prompt.md").read_text() == "page"
    render_simulation(simulation)


@pytest.mark.parametrize(("text", "value"), [("3", 3), ("true", True), ("[1]", [1]), ("plain", "plain")])
def test_a_command_line_value_reads_as_json_when_it_parses(text: str, value: object) -> None:
    assert read_value(text) == value


def test_live_stream_follows_the_stderr_of_the_moment(capfd: pytest.CaptureFixture[str]) -> None:
    """The proxy is a TextIO that is the live `sys.stderr`: the members beartype checks and what it writes."""
    stream = LiveStream()
    assert (stream.mode, stream.name, stream.writable(), stream.readable(), stream.seekable()) == (
        "w",
        "<stderr>",
        True,
        False,
        False,
    )
    assert hasattr(stream.buffer, "write")
    written = stream.write("live\n")
    stream.flush()
    out = capfd.readouterr()
    assert (written, out.err) == (5, "live\n")


def test_live_stream_writes_where_stderr_moved_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind once, follow forever: after the host swaps `sys.stderr`, the proxy writes to the new stream."""
    moved: list[str] = []

    class Sink:
        def write(self, text: str) -> int:
            moved.append(text)
            return len(text)

        def flush(self) -> None:
            pass

    monkeypatch.setattr("sys.stderr", Sink())
    stream = LiveStream()
    stream.write("followed")
    stream.flush()
    assert moved == ["followed"]
