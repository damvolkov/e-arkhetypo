"""tests/unit/e_cli/cli: the command tables — every target resolves, the tree is lazy, `main` exits with the run's code."""

import importlib
import inspect
import subprocess
import sys

import pytest

from e_cli.cli import CARDS, GROUPS, main


@pytest.mark.parametrize("card", CARDS, ids=[card.path for card in CARDS])
def test_cli_card_target_is_a_coroutine_function(card) -> None:
    module, _, function = card.target.partition(":")
    assert inspect.iscoroutinefunction(getattr(importlib.import_module(module), function))


def test_cli_groups_precede_their_children() -> None:
    seen = {""}
    for group in GROUPS:
        assert group.parent in seen, f"{group.path} mounts before its parent"
        seen.add(group.path)
    assert {card.parent for card in CARDS} <= seen


def test_cli_build_imports_no_command_module() -> None:
    """Help and every group listing come from the cards: building the tree loads no command."""
    probe = (
        "import sys; from e_cli.cli import build; build(); "
        "sys.exit(len([m for m in sys.modules if m.startswith('e_cli.commands')]))"
    )
    assert subprocess.run([sys.executable, "-c", probe], check=False).returncode == 0  # noqa: S603 — fixed argv, own interpreter


def test_cli_main_exits_with_the_run_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["ecli", "history", "undo"])
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 4


@pytest.mark.parametrize("tokens", [(), ("project",), ("project", "env")], ids=["root", "group", "nested"])
def test_cli_bare_group_prints_its_help(ecli, tokens: tuple[str, ...]) -> None:
    code, out, _ = ecli(*tokens)
    assert code == 0
    assert "Usage: ecli" in out


def test_cli_help_lists_every_group_with_its_summary(ecli) -> None:
    _, out, _ = ecli("--help")
    assert all(group.help[:20] in out for group in GROUPS if not group.parent)
