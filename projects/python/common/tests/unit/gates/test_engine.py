"""The gates' engine on throwaway projects: each level finds what its rule forbids, and nothing else."""

import textwrap
from typing import TYPE_CHECKING, Final

import pytest

from gates.engine import (
    gate_cases,
    gate_check,
    gate_genealogy,
    gate_main,
    gate_parity,
    gate_shape,
    gate_syntax,
    gate_tree,
    gate_within,
)
from gates.models import (
    Classes,
    Constants,
    Functions,
    GateError,
    Gates,
    Genealogy,
    Parity,
    Shape,
    Syntax,
    Tree,
    Violation,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

IF: Final = Syntax(
    id="if-statement",
    law="5",
    message="m",
    files=("src/**/*.py",),
    rule={"kind": "if_statement"},
    valid=("x = a if b else c",),
    invalid=("if a:\n    x = 1\n",),
)
RULES: Final = """
roots: [src]
rules:
  - level: syntax
    id: private-function
    law: "1"
    message: m
    files: ["src/**/*.py"]
    rule: {kind: function_definition, has: {field: name, regex: '^_'}}
"""


def write(root: Path, files: dict[str, str]) -> Path:
    """A throwaway project: each relative path written with its dedented text."""
    _ = [
        (root / path).parent.mkdir(parents=True, exist_ok=True) or (root / path).write_text(textwrap.dedent(text))
        for path, text in files.items()
    ]
    return root


def places(violations: Iterable[Violation]) -> list[tuple[str, int]]:
    """Each violation as its path and line, in order."""
    return sorted((violation.path, violation.line) for violation in violations)


##### TREE #####


def test_tree_allow_names_every_stranger(tmp_path: Path) -> None:
    write(tmp_path, {"n/guard/node.py": "", "n/guard/patterns.py": "", "n/guard/sub/x.py": ""})
    rule = Tree(id="node", law="1", message="m", dirs=("n/*",), allow=("node.py",))
    assert places(gate_tree(rule, tmp_path)) == [("n/guard/patterns.py", 1), ("n/guard/sub", 1)]


def test_tree_require_names_the_directory(tmp_path: Path) -> None:
    write(tmp_path, {"n/guard/models.py": ""})
    rule = Tree(id="node", law="1", message="m", dirs=("n/*",), require=("node.py",))
    assert places(gate_tree(rule, tmp_path)) == [("n/guard", 1)]


def test_tree_skips_caches_and_ignores(tmp_path: Path) -> None:
    write(tmp_path, {"n/guard/__pycache__/node.pyc": "", "n/guard/node.py": "", "n/infra/base.py": ""})
    rule = Tree(id="node", law="1", message="m", dirs=("n/*",), ignores=("n/infra",), allow=("node.py",))
    assert list(gate_tree(rule, tmp_path)) == []


##### SHAPE #####

NODE: Final = Shape(
    id="node-shape",
    law="1",
    message="m",
    files=("n/*/node.py",),
    classes=Classes(count=1, name="{Dir}Node", bases="*Node"),
    functions=Functions(max=0),
    constants=Constants(max=1, annotation=r"^Final\[Mapping\[.+\]\]$", literals=False),
)


def test_shape_clean_node(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "n/ask_user/node.py": """
                REPLIES: Final[Mapping[Label, Text]] = MappingProxyType({Label.A: Text.A})
                class AskUserNode(GuardrailNode, ParaphrasedNode): ...
            """
        },
    )
    assert list(gate_shape(NODE, tmp_path)) == []


def test_shape_every_breach_of_a_node(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "n/guard/node.py": """
                INSTRUCTION: Final[str] = "Classify the message."
                REPLIES: Final[Mapping[Label, Text]] = MappingProxyType({Label.A: Text.A})
                def helper(): ...
                class GuardNode(Base): ...
                class Extra: ...
            """
        },
    )
    found = sorted(violation.message.removeprefix("m (").removesuffix(")") for violation in gate_shape(NODE, tmp_path))
    assert found == [
        "2 classes, 1 allowed",
        "a string literal in a constant",
        "annotation Final[str] is not ^Final\\[Mapping\\[.+\\]\\]$",
        "class Extra has no base named *Node",
        "class Extra is not named GuardNode",
        "class GuardNode has no base named *Node",
        "constant beyond the 1 allowed",
        "function helper beyond the 0 allowed",
    ]


def test_shape_functions_all_async(tmp_path: Path) -> None:
    write(tmp_path, {"ops/net.py": "async def net_fetch(): ...\ndef net_parse(): ...\n"})
    rule = Shape(id="async", law="14", message="m", files=("ops/*.py",), functions=Functions(asynchronous=True))
    assert [violation.message for violation in gate_shape(rule, tmp_path)] == ["m (function net_parse is not async)"]


##### SYNTAX #####


def test_syntax_reports_rule_line_and_law(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/a.py": "class A:\n    def run(self, x):\n        if x:\n            return 1\n",
            "other/b.py": "if a:\n    b\n",
        },
    )
    found = gate_syntax(tmp_path, Gates(roots=("src", "other"), rules=(IF,)))
    assert [(v.path, v.line, v.rule, v.law) for v in found] == [("src/a.py", 3, "if-statement", "5")]


def test_syntax_without_rules_or_roots_is_empty(tmp_path: Path) -> None:
    write(tmp_path, {"src/a.py": "if a:\n    b\n"})
    assert gate_syntax(tmp_path, Gates(roots=("src",), rules=())) == []
    assert gate_syntax(tmp_path, Gates(roots=("missing",), rules=(IF,))) == []


def test_syntax_broken_rule_raises(tmp_path: Path) -> None:
    write(tmp_path, {"src/a.py": "x = 1\n"})
    broken = Syntax(id="broken", law="1", message="m", files=("src/**",), rule={"kind": "no_such_kind"})
    with pytest.raises(GateError):
        gate_syntax(tmp_path, Gates(roots=("src",), rules=(broken,)))


def test_cases_pass_and_fail() -> None:
    assert list(gate_cases(Gates(roots=(), rules=(IF,)))) == []
    wrong = Syntax(
        id="if-statement",
        law="5",
        message="m",
        files=("src/**",),
        rule={"kind": "if_statement"},
        valid=("if a:\n    b\n",),
        invalid=("x = 1",),
    )
    assert sorted(violation.message.split(":")[0] for violation in gate_cases(Gates(roots=(), rules=(wrong,)))) == [
        "m (invalid case missed",
        "m (valid case caught",
    ]


##### GENEALOGY #####


def test_genealogy_orphans_order_and_contracts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(
        tmp_path,
        {
            "src/genealogy_case/framework.py": "class Framework:\n    def _hook(self): ...\n",
            "src/genealogy_case/mod.py": """
                from genealogy_case.framework import Framework

                class Kept(Framework):
                    def _run_fetch(self): ...
                    def _enter_pool(self): ...
                    def _common_log(self): ...
                    def _orphan(self): ...
                    async def __aenter__(self): ...
                    def run(self): ...
                    def _run_late(self): ...
                    def _hook(self): ...
            """,
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    rule = Genealogy(id="g", law="3", message="m", files=("src/genealogy_case/mod.py",), order=True)
    found = sorted(violation.message.split("(")[-1].rstrip(")") for violation in gate_genealogy(rule, tmp_path))
    assert found == ["Kept._orphan serves no public method", "Kept._run_late after a public method"]


def test_genealogy_a_broken_module_is_a_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, {"src/broken_case/mod.py": "from broken_case.missing import Port\n"})
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    rule = Genealogy(id="g", law="3", message="m", files=("src/broken_case/*.py",))
    assert [violation.message.split(":")[0] for violation in gate_genealogy(rule, tmp_path)] == ["m (does not import"]


##### PARITY #####


def test_parity_both_strangers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(
        tmp_path,
        {
            "src/parity_case/roster.py": "from enum import StrEnum\nclass Agent(StrEnum):\n    A = 'a'\n    B = 'b'\n",
            "agents/a.md": "",
            "agents/c.md": "",
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    rule = Parity(id="p", law="22", message="m", enum="parity_case.roster:Agent", files="agents/*.md")
    assert places(gate_parity(rule, tmp_path)) == [("agents/c.md", 1), ("parity_case.roster:Agent", 1)]


##### RUN #####


@pytest.mark.parametrize(
    ("at", "paths", "kept"),
    [
        ("src/a/b.py", (), True),
        ("src/a/b.py", ("src/a/b.py",), True),
        ("src/a/b.py", ("src",), True),
        ("src/a/sub", ("src/a/sub/x.py",), True),
        ("src/a/b.py", ("src/a/c.py",), False),
    ],
    ids=["no-paths", "same", "under-a-directory", "a-directory-above-the-file", "elsewhere"],
)
def test_within(at: str, paths: tuple[str, ...], kept: bool) -> None:
    assert gate_within(Violation(path=at, line=1, rule="r", law="1", message="m"), paths) is kept


def test_check_keeps_to_the_given_paths(tmp_path: Path) -> None:
    write(tmp_path, {"gates/rules.yml": RULES, "src/a.py": "def _helper(): ...\n", "src/b.py": "x = 1\n"})
    assert places(gate_check(tmp_path)) == [("src/a.py", 1)]
    assert gate_check(tmp_path, ("src/b.py",)) == []


def test_main_unknown_command_is_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_main(["lint"]) == 2
    assert "usage" in capsys.readouterr().err


def test_main_check_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, {"gates/rules.yml": RULES, "src/a.py": "x = 1\n"})
    monkeypatch.chdir(tmp_path)
    assert gate_main(["check"]) == 0
    write(tmp_path, {"src/b.py": "def _helper(): ...\n"})
    assert gate_main(["check"]) == 1
