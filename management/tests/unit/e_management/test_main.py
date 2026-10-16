"""tests/unit/e_management/__main__: the argparse surface — codes returned, reports rendered, nothing else."""

from typing import TYPE_CHECKING

from e_management.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path


def test_main_plan_prints_the_actions(tmp_path: Path, capsys) -> None:
    assert main(["plan", "api", "myapp"]) == 0
    out = capsys.readouterr().out
    assert '"actions"' in out
    assert '"src": "systems/api"' in out


def test_main_gen_creates_and_reports_next(tmp_path: Path, capsys) -> None:
    dest = tmp_path / "e-myapp"
    assert main(["gen", "api", "myapp", "--dest", str(dest)]) == 0
    assert "make install" in capsys.readouterr().out
    assert (dest / "src" / "e_myapp" / "main.py").is_file()


def test_main_drift_is_in_sync(capsys) -> None:
    assert main(["drift"]) == 0
    assert "api: in sync" in capsys.readouterr().out


def test_main_graph_and_checks_pass(tmp_path: Path, capsys, monkeypatch) -> None:
    assert main(["graph"]) == 0
    assert "wrote" in capsys.readouterr().out
    assert main(["graph-check"]) == 0
    assert "in sync" in capsys.readouterr().out
    assert main(["infra-check"]) == 0
    assert main(["stack"]) == 0
    assert main(["stack-check"]) == 0
    monkeypatch.setattr("e_management.__main__.webbrowser.open", lambda _uri: True)
    assert main(["map", "api"]) == 0


def test_main_plan_honours_the_switches(tmp_path: Path, capsys) -> None:
    assert main(["plan", "api", "xapp", "--off", "websockets", "--ci-off", "docs"]) == 0
    out = capsys.readouterr().out
    assert "systems/api" in out
