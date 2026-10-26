"""tests/unit/e_cli/runtime/lifespan: one run's scope — shared and session sealed in, diagnostics on stderr only."""

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from e_cli.models.session import Session
from e_cli.runtime.lifespan import SharedState, lifespan
from infra.state import State

if TYPE_CHECKING:
    from pathlib import Path


async def test_lifespan_seals_shared_and_session_into_the_graph() -> None:
    session = Session(command="project list")
    async with lifespan(session) as deps:
        graph = await deps.resolve(State)
        assert isinstance(graph.shared, SharedState)
        assert graph.session is session
        with pytest.raises(RuntimeError, match="Sealed"):
            graph.extra = 1


def test_lifespan_verbose_logs_to_stderr_never_stdout(workdir: Path) -> None:
    """A real process: the logger is a per-process singleton, so its routing is a property of one run."""
    probe = "import sys; from e_cli.cli import main; sys.argv = ['ecli', '--verbose', 'project', 'list']; main()"
    run = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=workdir, check=False)  # noqa: S603 — fixed argv, own interpreter
    assert run.returncode == 0
    assert "run start" in run.stderr
    assert "run start" not in run.stdout
    assert "no projects yet" in run.stdout
