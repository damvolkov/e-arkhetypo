"""tests/unit/test_taxonomy: the dependency table of the taxonomy and the shape of every provider, checked on the tree.

Imports are read with `ast` (tach enforces the layers in CI too; this is the second, readable gate): a port imports
no provider, engine or processor; a provider reaches only ports, infra and ops; engines and processors never meet a
concrete provider nor each other. Every class that names itself a driver or an adapter declares its spec and the
lifecycle, and the folder it lives in agrees with its locality: `EMBEDDED` is an adapter, the rest are drivers. A
provider lives at `providers/<drivers|adapters>/<capability>/<name>.py`, where `<capability>` is the module of a port
and the provider meets that port; class names are unique, `<Name><Nature>`."""

import ast
import importlib
from collections import Counter
from pathlib import Path
from typing import Final, get_protocol_members

import pytest

from e_infra.ports.provider import Locality, Provider, ProviderSpec

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "e_infra"
FORBIDDEN: Final[dict[str, frozenset[str]]] = {
    "ports": frozenset({"providers", "engines", "processors"}),
    "providers/drivers": frozenset({"providers", "engines", "processors"}),
    "providers/adapters": frozenset({"providers", "engines", "processors"}),
    "engines": frozenset({"providers", "processors"}),
    "processors": frozenset({"providers", "engines"}),
    "infra": frozenset({"ports", "providers", "engines", "processors"}),
    "ops": frozenset({"ports", "providers", "engines", "processors"}),
}
LIFECYCLE: Final = ("__aenter__", "__aexit__", "health")


def _modules(folder: str) -> list[Path]:
    return sorted(path for path in (PACKAGE / folder).rglob("*.py") if "__pycache__" not in path.parts)


def _dotted(path: Path) -> str:
    return "e_infra." + path.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", ".")


def _imported(path: Path) -> set[str]:
    """The `e_infra` sub-packages a module imports, whatever the form."""
    nodes = list(ast.walk(ast.parse(path.read_text("utf-8"))))
    named = [node.module for node in nodes if isinstance(node, ast.ImportFrom) and node.module]
    named += [alias.name for node in nodes if isinstance(node, ast.Import) for alias in node.names]
    return {name.split(".")[1] for name in named if name.startswith("e_infra.")}


CASES: Final = [(folder, path) for folder in FORBIDDEN for path in _modules(folder)]


@pytest.mark.parametrize(
    ("folder", "path"), CASES, ids=[f"{folder}:{path.relative_to(PACKAGE)}" for folder, path in CASES]
)
def test_taxonomy_imports_obey_the_table(folder: str, path: Path) -> None:
    breaking = _imported(path) & FORBIDDEN[folder]
    assert not breaking, (
        f"{path.relative_to(PACKAGE)} imports {sorted(breaking)}, which the table forbids a {folder} module"
    )


def _providers() -> list[tuple[str, type]]:
    layout = (("providers/drivers", "Driver"), ("providers/adapters", "Adapter"))
    modules = [
        (folder, surname, importlib.import_module(_dotted(path)))
        for folder, surname in layout
        for path in _modules(folder)
    ]
    return [
        (folder, cls)
        for folder, surname, module in modules
        for name, cls in vars(module).items()
        if isinstance(cls, type) and name.endswith(surname) and cls.__module__ == module.__name__
    ]


PROVIDERS: Final = _providers()


def test_taxonomy_every_provider_module_holds_a_provider() -> None:
    held = {cls.__module__ for _, cls in PROVIDERS}
    expected = {_dotted(path) for folder in ("providers/drivers", "providers/adapters") for path in _modules(folder)}
    assert held == expected


@pytest.mark.parametrize(("folder", "cls"), PROVIDERS, ids=[cls.__name__ for _, cls in PROVIDERS])
def test_taxonomy_provider_declares_spec_and_lifecycle(folder: str, cls: type) -> None:
    spec = getattr(cls, "spec", None)
    assert isinstance(spec, ProviderSpec), f"{cls.__name__} declares no ProviderSpec"
    assert all(callable(getattr(cls, name, None)) for name in LIFECYCLE), f"{cls.__name__} lacks part of the lifecycle"
    assert (spec.locality is Locality.EMBEDDED) is (folder == "providers/adapters"), (
        f"{cls.__name__}: {spec.locality} does not belong in {folder}"
    )


##### THE PATH IS THE CAPABILITY #####
NATURES: Final = ("drivers", "adapters")
PORTS: Final = frozenset(path.stem for path in _modules("ports")) - {"provider"}
PROVIDER_PATHS: Final = [path for nature in NATURES for path in _modules(f"providers/{nature}")]


@pytest.mark.parametrize("path", PROVIDER_PATHS, ids=[str(path.relative_to(PACKAGE)) for path in PROVIDER_PATHS])
def test_taxonomy_provider_sits_at_nature_capability_name(path: Path) -> None:
    nature, capability, _ = path.relative_to(PACKAGE / "providers").parts
    assert nature in NATURES
    assert capability in PORTS, f"{path.relative_to(PACKAGE)}: {capability!r} is no module of ports/"


def _port_of(capability: str) -> type:
    """The capability's port: the one Protocol of its module that extends `Provider`."""
    module = importlib.import_module(f"e_infra.ports.{capability}")
    (port,) = (
        cls
        for cls in vars(module).values()
        if isinstance(cls, type)
        and cls.__module__ == module.__name__
        and Provider in cls.__mro__
        and cls is not Provider
    )
    return port


@pytest.mark.parametrize(("folder", "cls"), PROVIDERS, ids=[cls.__name__ for _, cls in PROVIDERS])
def test_taxonomy_provider_meets_the_port_of_its_folder(folder: str, cls: type) -> None:
    capability = cls.__module__.split(".")[-2]
    port = _port_of(capability)
    missing = sorted(member for member in get_protocol_members(port) if not hasattr(cls, member))
    assert not missing, f"{cls.__name__} does not meet {port.__name__}: lacks {missing}"


def test_taxonomy_provider_class_names_are_unique() -> None:
    names = Counter(cls.__name__ for _, cls in PROVIDERS)
    assert not [name for name, count in names.items() if count > 1]


@pytest.mark.parametrize(("folder", "cls"), PROVIDERS, ids=[cls.__name__ for _, cls in PROVIDERS])
def test_taxonomy_provider_class_carries_its_nature(folder: str, cls: type) -> None:
    assert cls.__name__.endswith(folder.removeprefix("providers/").title().removesuffix("s"))
