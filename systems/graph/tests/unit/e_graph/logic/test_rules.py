"""tests/unit: logic.rules — every law breached on purpose, each breach named by rule and subject."""

from typing import TYPE_CHECKING, Any

import pytest

from core.struct import CheckedStruct
from e_graph.logic.errors import Rule
from e_graph.logic.models import SIGNATURES, DeterministicSpec, Draft, Function, Hook, SemanticSpec, Spec
from e_graph.logic.rules import judge_section, rule_merge, rule_tree
from e_graph.models.section import Section

if TYPE_CHECKING:
    from pathlib import Path

OUTPUT: dict[str, Any] = {"type": "object"}
NAME = Spec.named(Section.EXTRACT)


def spec(name: str, kind: str = "deterministic", **fields: Any) -> Spec[str]:
    extra = {"instructions": "Read it."} if kind == "semantic" else {}
    raw = {"kind": kind, "name": name, "description": "d", "output": OUTPUT, **extra, **fields}
    return CheckedStruct.convert(raw, DeterministicSpec[NAME] | SemanticSpec[NAME])


def hook(name: str, *, signature: str | None = None, doc: str = "Does it.") -> Function:
    contract = SIGNATURES[Hook(name)] if name in set(Hook) else f"async def {name}(state: RunState) -> None"
    return Function(name=name, signature=signature or contract, doc=doc, file=f"{name}.py")


def draft(
    *specs: Spec[str], functions: dict[str, tuple[Function, ...]] | None = None, wiki: frozenset[str] = frozenset()
) -> Draft:
    found = {item.name: item for item in specs}
    paired: dict[str, tuple[Function, ...]] = {
        item.name: (hook("run"),) for item in specs if isinstance(item, DeterministicSpec)
    }
    return Draft(
        pipeline="doc",
        section=Section.EXTRACT,
        specs=found,
        functions=paired if functions is None else functions,
        wiki=wiki,
    )


def breaches(target: Draft) -> set[tuple[Rule, str]]:
    return {(error.rule, error.subject) for error in judge_section(target)}


def test_a_coherent_section_breaks_nothing() -> None:
    target = draft(
        spec("EXT-a"),
        spec("EXT-b", depends=["EXT-a"], fallback="EXT-c", wiki=["net"]),
        spec("EXT-c"),
        spec("EXT-d", "semantic", depends=["EXT-b"]),
        functions={
            "EXT-a": (hook("run"), hook("check")),
            "EXT-b": (hook("run"),),
            "EXT-c": (hook("run"),),
            "EXT-d": (hook("pre_run"), hook("post_run"), hook("check")),
        },
        wiki=frozenset({"net"}),
    )
    assert breaches(target) == set()


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(
            Draft(
                pipeline="doc",
                section=Section.EXTRACT,
                specs={"EXT-file": spec("EXT-other")},
                functions={"EXT-file": (hook("run"),)},
                wiki=frozenset(),
            ),
            {(Rule.FILENAME, "EXT-file")},
            id="filename",
        ),
        pytest.param(draft(spec("EXT-a", depends=["EXT-ghost"])), {(Rule.DEPENDS, "EXT-a")}, id="depends-missing"),
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
        pytest.param(draft(spec("EXT-a"), functions={}), {(Rule.RUNNER, "EXT-a")}, id="runner-missing"),
        pytest.param(
            draft(spec("EXT-a"), functions={"EXT-a": (hook("check"),)}),
            {(Rule.RUNNER, "EXT-a")},
            id="runner-without-run",
        ),
        pytest.param(
            draft(spec("EXT-a"), functions={"EXT-a": (hook("run"),), "EXT-gone": (hook("run"),)}),
            {(Rule.ORPHAN, "EXT-gone")},
            id="orphan",
        ),
        pytest.param(
            draft(spec("EXT-a"), functions={"EXT-a": (hook("run"), hook("pre_run"))}),
            {(Rule.HOOK, "EXT-a.pre_run")},
            id="hook-foreign-to-kind",
        ),
        pytest.param(
            draft(spec("EXT-a", "semantic"), functions={"EXT-a": (hook("run"),)}),
            {(Rule.HOOK, "EXT-a.run")},
            id="hook-run-on-semantic",
        ),
        pytest.param(
            draft(spec("EXT-a"), functions={"EXT-a": (hook("run"), hook("helper"))}),
            {(Rule.HOOK, "EXT-a.helper")},
            id="hook-any-other-name",
        ),
        pytest.param(
            draft(
                spec("EXT-a"),
                functions={"EXT-a": (hook("run", signature="def run(state: RunState) -> dict[str, Any]"),)},
            ),
            {(Rule.SIGNATURE, "EXT-a.run")},
            id="signature-sync",
        ),
        pytest.param(
            draft(
                spec("EXT-a", "semantic"),
                functions={
                    "EXT-a": (hook("post_run", signature="async def post_run(state: RunState) -> dict[str, Any]"),)
                },
            ),
            {(Rule.SIGNATURE, "EXT-a.post_run")},
            id="signature-params",
        ),
        pytest.param(
            draft(
                spec("EXT-a"),
                functions={"EXT-a": (hook("run"), hook("check", signature="async def check(state: RunState) -> str"))},
            ),
            {(Rule.SIGNATURE, "EXT-a.check")},
            id="signature-return",
        ),
        pytest.param(
            draft(spec("EXT-a"), functions={"EXT-a": (hook("run", doc=""),)}),
            {(Rule.DOC, "EXT-a.run")},
            id="doc-missing",
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


def test_tree_holds_sections_and_their_files_only(tmp_path: Path) -> None:
    root = tmp_path / "specs" / "doc"
    (root / "extract" / "nested").mkdir(parents=True)
    (root / "wiki").mkdir()
    (root / "misc").mkdir()
    (root / "stray.yaml").write_text("")
    (root / "extract" / "EXT-a.yaml").write_text("")
    (root / "extract" / "EXT-b.yml").write_text("")
    (root / "extract" / ".gitkeep").write_text("")
    subjects = {error.subject.removeprefix(f"{root}/") for error in rule_tree(root, ".yaml")}
    assert subjects == {"misc", "stray.yaml", "extract/nested", "extract/EXT-b.yml"}
    assert list(rule_tree(tmp_path / "absent", ".yaml")) == []
