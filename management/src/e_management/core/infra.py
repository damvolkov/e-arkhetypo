"""core.infra: the assembler — a loaded CI library plus one project's tokens become the files under ``.github/``.

Pure and deterministic: no filesystem, no clock. The same library, tokens and selection always emit the
same bytes, which is what lets ``make infra-check`` diff a system against the library and makes the
sandbox test meaningful. A selection is legal only when every chosen feature's ``requires`` is chosen,
every token its fragments demands arrives, and a replacing feature (the rust one) folds away what it
replaces. Tokens are `{{lower_case}}`; `${{ github.* }}` never matches and is left exactly as written.
"""

import msgspec

from e_management.core.errors import InfraError
from e_management.models.infra import Feature, FeatureMap

##### PATHS #####
WORKFLOWS = ".github/workflows"


class Library(msgspec.Struct, frozen=True, kw_only=True):
    """The library as bytes read: the map, and every fragment of it keyed by its path under ``infra/``."""

    map: FeatureMap
    fragments: dict[str, str]


##### TOKENS #####


def derive(package: str, brand: str) -> dict[str, str]:
    """The tokens that follow from the project's identity alone — never stored, never drifted."""
    return {
        "brand": brand,
        "package": package,
        "package_path": f"src/{package}",
        "pypi_project": brand,
        "smoke": f'.smoke/bin/python -c "import {package}"',
        "allowlist": f"src/{package}/|tests/|docs/|CHANGELOG\\.md$|README\\.md$",
    }


##### SELECTION #####


def resolve(library: Library, chosen: frozenset[str], on_choices: frozenset[str] = frozenset()) -> list[str]:
    """The chosen features in library order with the replaced ones folded away; an illegal set raises.

    A ``requires`` entry names a feature, or a ``group.choice`` of the project (``stack.docker``): a
    feature whose dependency is neither selected nor switched on is refused here, not in CI."""
    features = library.map.features
    if unknown := chosen - features.keys():
        msg = f"unknown CI feature(s): {', '.join(sorted(unknown))}; the library offers {', '.join(sorted(features))}"
        raise InfraError(msg)
    order = [key for key in features if key in chosen]
    satisfied = chosen | on_choices
    if broken := [
        (key, deps) for key in order if (deps := sorted(r for r in features[key].requires if r not in satisfied))
    ]:
        msg = "; ".join(f"{key!r} requires {', '.join(dep)}, which is not selected" for key, dep in broken)
        raise InfraError(msg)
    replaced = {name for key in order for name in features[key].replaces}
    return [key for key in order if key not in replaced]


##### ASSEMBLY #####


def assemble(
    library: Library, tokens: dict[str, str], chosen: frozenset[str], on_choices: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Every generated file keyed by project-relative path: workflows, vars manifest, map, install docs, contract test."""
    selected = resolve(library, chosen, on_choices)
    specs = [(key, library.map.features[key]) for key in selected]
    if gaps := {token for _, spec in specs for token in spec.tokens if token not in tokens}:
        msg = f"the selection demands tokens nothing provides: {', '.join(sorted(gaps))}"
        raise InfraError(msg)

    ci_jobs = _jobs(library, specs, "ci", tokens)
    release_jobs = _jobs(library, specs, "release", tokens)
    files = {
        f"{WORKFLOWS}/ci.yml": _shell(library, "workflows/ci.yml", tokens, ci_jobs=ci_jobs),
        f"{WORKFLOWS}/release.yml": _shell(
            library,
            "workflows/release.yml",
            tokens,
            release_trigger=_read(library, _trigger(specs), tokens),
            release_jobs=release_jobs,
        ),
        **{
            f"{WORKFLOWS}/{job}.yml": _read(library, f"jobs/workflow/{job}.yml", tokens)
            for _, spec in specs
            for job in spec.jobs.get("workflow", ())
        },
        **{_target(path): _read(library, f"files/{path}", tokens) for _, spec in specs for path in spec.files},
        ".github/ci.vars.example": _vars(specs),
        ".github/ci.map.yml": "features:\n" + "".join(f"  - {key}\n" for key in selected),
        ".github/INSTALL.md": _install(library, specs),
        "tests/unit/test_ci_contract.py": _read(library, "contract.py.j2", {}),
    }
    return {key: body for key, body in files.items() if body}


def _trigger(specs: list[tuple[str, Feature]]) -> str:
    """The release trigger the selection needs: a tag-driven feature (rust) takes the whole workflow."""
    return "triggers/tag.yml" if any(spec.tag_trigger for _, spec in specs) else "triggers/dispatch.yml"


def _target(path: str) -> str:
    """Where a library file lands: renovate stays in .github, the agent contract sits at the root, tools keep their folder."""
    match path:
        case "renovate.json":
            return ".github/renovate.json"
        case "qwen.md":
            return "QWEN.md"
        case _:
            return path


def _shell(library: Library, path: str, tokens: dict[str, str], **slots: str) -> str:
    """A workflow header with its slots filled — an empty job slot (a selection with no such workflow) yields no file."""
    body = _read(library, path, tokens, **slots)
    return "" if not any(value.strip() for key, value in slots.items() if key.endswith("jobs")) else body


def _read(library: Library, path: str, tokens: dict[str, str], **slots: str) -> str:
    """One library fragment, rendered: tokens first, then the slot contents, each stripped block ending with its newline."""
    try:
        text = library.fragments[path]
    except KeyError as error:
        msg = f"the CI library holds no fragment {path!r}"
        raise InfraError(msg) from error
    for key, value in tokens.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    for key, value in slots.items():
        text = text.replace(f"{{{{{key}}}}}", value.rstrip() + "\n")
    return text


def _jobs(library: Library, specs: list[tuple[str, Feature]], workflow: str, tokens: dict[str, str]) -> str:
    """The fragments of every feature that brings jobs to this workflow, in library order, each tagged with its feature."""
    blocks = [
        f"  # feature: {key}\n{_read(library, f'jobs/{workflow}/{job}.yml', tokens).rstrip()}"
        for key, spec in specs
        for job in spec.jobs.get(workflow, ())
    ]
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _vars(specs: list[tuple[str, Feature]]) -> str:
    """The manifest every generated contract test checks: one inert gate per feature that ships with one."""
    lines = [
        "# Optional CI/CD gates — GitHub Actions *variables* (Settings → Secrets and variables → Actions → Variables).",
        "# Generated from infra/ by management — every gate ships inert: a repo enables only what it is.",
        "# Enable:  gh variable set NAME --body true      Disable: gh variable delete NAME",
        "#",
        "# Always-on (not gates, the CI baseline): ruff · ty · tach · validate-pyproject · zizmor · pytest+coverage.",
        "",
    ]
    gates: dict[str, str] = {}
    for key, spec in specs:
        if spec.gate:
            gates.setdefault(spec.gate, f"from feature {key}: {spec.label.lower()}")
    return "\n".join([*lines, *(f"{gate}=false  # {why}" for gate, why in sorted(gates.items()))]) + "\n"


def _install(library: Library, specs: list[tuple[str, Feature]]) -> str:
    """The one-time setup instructions of the selection: what the repo must do to arm each feature it carries."""
    parts = [f"## {key}\n\n{body}" for key, spec in specs if (body := _body(library, spec.setup))]
    return (
        "\n".join(
            [
                "# Installing this project's CI",
                "",
                "Generated from `infra/` — one section per feature installed, in pipeline order.",
                "Gates ship inert: until a variable is set, the job exists and does nothing.",
                "",
                *parts,
            ]
        )
        + "\n"
    )


def _body(library: Library, name: str) -> str:
    """A setup document without its own title: the section heading belongs to the assembler."""
    text = library.fragments.get(f"setup/{name}", "") if name else ""
    return "\n".join(line for line in text.splitlines() if not line.startswith("# ")).strip()
