"""tests/unit: logic.rules — every law breached on purpose, each breach named by rule and subject."""

from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.errors import Rule
from e_graph.logic.models import ROLES, SIGNATURES, DeterministicSpec, Draft, Function, Module, Role, SemanticSpec, Spec
from e_graph.logic.rules import SECTIONS, judge_section, rule_merge, rule_tree
from e_graph.models.section import Section
from infra.struct import CheckedStruct

if TYPE_CHECKING:
    from pathlib import Path

OUTPUT: dict[str, Any] = {"type": "object"}
NAME = Spec.named(Section.EXTRACT)
ROLE_NAMES = frozenset(Role)


def spec(name: str, kind: str = "deterministic", **fields: Any) -> Spec[str]:
    defaults = {"instructions": "Read it."} if kind == "semantic" else {"runner": f"owned/{name[4:].replace('-', '')}"}
    raw = {"kind": kind, "name": name, "description": "d", "output": OUTPUT, **defaults, **fields}
    return CheckedStruct.convert(raw, DeterministicSpec[NAME] | SemanticSpec[NAME])


def fn(name: str, *, signature: str | None = None, doc: str = "Does it.") -> Function:
    contract = (
        SIGNATURES[Role(name)] if name in ROLE_NAMES else f"async def {name}(state: RunState, call: Call) -> None"
    )
    return Function(name=name, signature=signature or contract, doc=doc)


def module(ref: str, *functions: Function, exists: bool = True) -> Module:
    return Module(ref=ref, file=f"{ref}.py", exists=exists, functions=functions)


def draft(
    *specs: Spec[str],
    modules: dict[str, Module] | None = None,
    owned: frozenset[str] | None = None,
    wiki: frozenset[str] = frozenset(),
    broken: frozenset[str] = frozenset(),
) -> Draft:
    """A section whose plugged runners all exist and fit, unless `modules`/`owned` say otherwise."""
    fitting = {ref: module(ref, fn(ROLES[slot])) for item in specs for slot, ref in item.plugs.items()}
    plugged = frozenset(ref.partition("/")[2] for ref in fitting if ref.startswith("owned/"))
    return Draft(
        pipeline="doc",
        section=Section.EXTRACT,
        specs={item.name: item for item in specs},
        modules=fitting | (modules or {}),
        owned=plugged if owned is None else owned,
        wiki=wiki,
        broken=broken,
    )


def breaches(target: Draft) -> set[tuple[Rule, str]]:
    return {(error.rule, error.subject) for error in judge_section(target)}


def test_a_coherent_section_breaks_nothing() -> None:
    target = draft(
        spec("EXT-a", check="agnostic/context/present"),
        spec("EXT-b", depends=["EXT-a"], fallback="EXT-c", wiki=["net"]),
        spec("EXT-c"),
        spec(
            "EXT-d", "semantic", depends=["EXT-b"], pre="owned/dpre", post="agnostic/number/scale", check="owned/dcheck"
        ),
        wiki=frozenset({"net"}),
    )
    assert breaches(target) == set()
    assert target.plugged == {"a", "b", "c", "dpre", "dcheck"}


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(
            Draft(
                pipeline="doc",
                section=Section.EXTRACT,
                specs={"EXT-file": spec("EXT-other")},
                modules={"owned/other": module("owned/other", fn("run"))},
                owned=frozenset({"other"}),
                wiki=frozenset(),
            ),
            {(Rule.FILENAME, "EXT-file")},
            id="filename",
        ),
        pytest.param(draft(spec("EXT-a", depends=["EXT-ghost"])), {(Rule.DEPENDS, "EXT-a")}, id="depends-missing"),
        pytest.param(
            draft(spec("EXT-a", depends=["EXT-ghost"]), broken=frozenset({"EXT-ghost"})),
            set(),
            id="depends-on-a-broken-file",
        ),
        pytest.param(
            draft(spec("EXT-a", fallback="EXT-ghost"), spec("EXT-b", fallback="EXT-ghost")),
            {(Rule.FALLBACK, "EXT-a"), (Rule.FALLBACK, "EXT-b")},
            id="fallback-missing",
        ),
        pytest.param(
            draft(spec("EXT-a", fallback="EXT-b"), spec("EXT-b", fallback="EXT-c"), spec("EXT-c")),
            {(Rule.FALLBACK, "EXT-b")},
            id="fallback-chain",
        ),
        pytest.param(
            draft(spec("EXT-a", fallback="EXT-b"), spec("EXT-b", depends=["EXT-c"]), spec("EXT-c")),
            {(Rule.FALLBACK, "EXT-b")},
            id="fallback-depends",
        ),
        pytest.param(
            draft(spec("EXT-a", fallback="EXT-b"), spec("EXT-b"), spec("EXT-c", depends=["EXT-b"])),
            {(Rule.FALLBACK, "EXT-c")},
            id="fallback-depended",
        ),
        pytest.param(
            draft(spec("EXT-a", depends=["EXT-c"]), spec("EXT-b", depends=["EXT-a"]), spec("EXT-c", depends=["EXT-b"])),
            {(Rule.CYCLE, "extract")},
            id="cycle",
        ),
        pytest.param(
            draft(spec("EXT-a"), modules={"owned/a": module("owned/a", exists=False)}),
            {(Rule.RUNNER, "EXT-a.runner")},
            id="runner-missing",
        ),
        pytest.param(
            draft(
                spec("EXT-a", check="agnostic/context/present"),
                modules={"agnostic/context/present": module("agnostic/context/present", exists=False)},
            ),
            {(Rule.RUNNER, "EXT-a.check")},
            id="tool-missing",
        ),
        pytest.param(
            draft(spec("EXT-a"), modules={"owned/a": module("owned/a", fn("run"), fn("helper"))}),
            {(Rule.SHAPE, "owned/a")},
            id="shape-two-functions",
        ),
        pytest.param(
            draft(spec("EXT-a"), modules={"owned/a": module("owned/a")}),
            {(Rule.SHAPE, "owned/a")},
            id="shape-no-function",
        ),
        pytest.param(
            draft(spec("EXT-a", check="owned/acheck"), modules={"owned/acheck": module("owned/acheck", fn("run"))}),
            {(Rule.ROLE, "EXT-a.check")},
            id="role-run-in-check",
        ),
        pytest.param(
            draft(spec("EXT-a"), modules={"owned/a": module("owned/a", fn("pre_run"))}),
            {(Rule.ROLE, "EXT-a.runner")},
            id="role-pre-in-runner",
        ),
        pytest.param(
            draft(
                spec("EXT-a", "semantic", post="owned/apost"),
                modules={"owned/apost": module("owned/apost", fn("check"))},
            ),
            {(Rule.ROLE, "EXT-a.post")},
            id="role-check-in-post",
        ),
        pytest.param(
            draft(spec("EXT-a"), modules={"owned/a": module("owned/a", fn("helper"))}),
            {(Rule.ROLE, "EXT-a.runner")},
            id="role-any-other-name",
        ),
        pytest.param(
            draft(
                spec("EXT-a"),
                modules={
                    "owned/a": module(
                        "owned/a", fn("run", signature="def run(state: RunState, call: Call) -> dict[str, Any]")
                    )
                },
            ),
            {(Rule.SIGNATURE, "owned/a")},
            id="signature-sync",
        ),
        pytest.param(
            draft(
                spec("EXT-a", "semantic", post="owned/apost"),
                modules={
                    "owned/apost": module(
                        "owned/apost",
                        fn("post_run", signature="async def post_run(state: RunState, call: Call) -> dict[str, Any]"),
                    )
                },
            ),
            {(Rule.SIGNATURE, "owned/apost")},
            id="signature-params",
        ),
        pytest.param(
            draft(
                spec("EXT-a", check="owned/acheck"),
                modules={
                    "owned/acheck": module(
                        "owned/acheck", fn("check", signature="async def check(state: RunState, call: Call) -> str")
                    )
                },
            ),
            {(Rule.SIGNATURE, "owned/acheck")},
            id="signature-return",
        ),
        pytest.param(
            draft(spec("EXT-a"), modules={"owned/a": module("owned/a", fn("run", doc=""))}),
            {(Rule.DOC, "owned/a")},
            id="doc-missing",
        ),
        pytest.param(
            draft(spec("EXT-a"), owned=frozenset({"a", "gone"})),
            {(Rule.ORPHAN, "owned/gone")},
            id="orphan",
        ),
        pytest.param(
            draft(spec("EXT-a"), owned=frozenset({"a", "gone"}), broken=frozenset({"EXT-b"})),
            set(),
            id="orphan-waits-for-a-broken-file",
        ),
        pytest.param(draft(spec("EXT-a", wiki=["net"])), {(Rule.WIKI, "EXT-a")}, id="wiki-missing"),
    ],
)
def test_each_law_names_its_breach(target: Draft, expected: set[tuple[Rule, str]]) -> None:
    assert breaches(target) == expected


def test_cycle_named_edge_by_edge() -> None:
    target = draft(spec("EXT-a", depends=["EXT-b"]), spec("EXT-b", depends=["EXT-a"]))
    (error,) = judge_section(target)
    assert error.detail in {"dependency cycle EXT-a → EXT-b → EXT-a", "dependency cycle EXT-b → EXT-a → EXT-b"}
    assert str(error).startswith("[cycle] extract: ")


def test_merge_keys_refused_with_their_line(tmp_path: Path) -> None:
    file = tmp_path / "EXT-a.yaml"
    text = "base: &b {x: 1}\nother:\n  <<: *b\nlist:\n  - << : *b\n"
    assert [error.detail for error in rule_merge(file, text)] == [
        "line 3: merge keys (<<) are banned",
        "line 5: merge keys (<<) are banned",
    ]
    assert list(rule_merge(file, "anchor: &a 1\nalias: *a\nnote: 'a << b'\n")) == []


def test_tree_holds_admitted_folders_and_their_files_only(tmp_path: Path) -> None:
    root = tmp_path / "specs" / "doc"
    (root / "extract" / "nested").mkdir(parents=True)
    (root / "wiki").mkdir()
    (root / "misc").mkdir()
    (root / "stray.yaml").write_text("")
    (root / "wiki" / "net.md").write_text("")
    (root / "extract" / "EXT-a.yaml").write_text("")
    (root / "extract" / "EXT-b.yml").write_text("")
    (root / "extract" / ".gitkeep").write_text("")
    admitted = (SECTIONS | {"wiki"}).__contains__
    subjects = {
        error.subject.removeprefix(f"{root}/") for error in rule_tree(root, ".yaml", admitted, skip=frozenset({"wiki"}))
    }
    assert subjects == {"misc", "stray.yaml", "extract/nested", "extract/EXT-b.yml"}
    assert list(rule_tree(tmp_path / "absent", ".yaml", admitted)) == []


def test_tree_holds_runner_modules_named_in_one_word(tmp_path: Path) -> None:
    root = tmp_path / "runners" / "owned" / "doc"
    (root / "extract").mkdir(parents=True)
    (root / "extract" / "total.py").write_text("")
    (root / "extract" / "net_total.py").write_text("")
    (root / "extract" / "Total.py").write_text("")
    (root / "extract" / "__pycache__").mkdir()
    subjects = {error.subject.removeprefix(f"{root}/") for error in rule_tree(root, ".py", SECTIONS.__contains__)}
    assert subjects == {"extract/net_total.py", "extract/Total.py"}
