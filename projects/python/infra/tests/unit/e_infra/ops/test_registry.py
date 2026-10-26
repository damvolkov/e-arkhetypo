"""tests/unit: CodeRegistry — static ast parsing of a scope: hierarchy, paths, syntactic discovery."""

import re
from typing import TYPE_CHECKING, Any, cast

import pytest

from e_infra.ops.registry import CodeRegistry, Kind, RegistryError

if TYPE_CHECKING:
    from pathlib import Path

ENGINE_PATH = "projects/python/infra/src/e_infra"


@pytest.fixture(scope="session")
def registry(repo: Path) -> CodeRegistry:
    return CodeRegistry(repo / ENGINE_PATH, package="e_infra")


def test_every_level_of_the_hierarchy_is_registered_by_path(registry: CodeRegistry) -> None:
    assert registry["e_infra"].kind is Kind.PACKAGE
    assert registry["e_infra.ops.file"].kind is Kind.MODULE
    assert registry["e_infra.ops.file"].doc.startswith("ops/file: agnostic discovery")
    finder = registry["e_infra.ops.file.FileFinder"]
    assert finder.kind is Kind.CLASS
    assert finder.parent == "e_infra.ops.file"
    method = registry["e_infra.ops.file.FileFinder._modules"]
    assert method.kind is Kind.METHOD
    assert method.private
    assert registry["e_infra.ops.compose.COMPOSE_FILE"].value == "'compose.yml'"
    assert registry["e_infra.ops.crypto.TokenShape.JWS"].value == "2"


def test_module_facts_read_the_source_without_importing(registry: CodeRegistry) -> None:
    settings = registry["e_infra.infra.settings"]
    assert settings.kind is Kind.PACKAGE
    assert settings.doc.startswith("infra/settings: the dynamic composer")
    assert {"e_infra.infra.settings.base", "e_infra.ops.file", "e_infra.infra.proxy"} <= set(settings.imports)
    crypto = registry["e_infra.ops.crypto.Crypto.hash_password"]
    assert crypto.signature == "async def hash_password(self, password: str) -> str"
    assert registry["e_infra.ops.file.FileFinder.adiscover"].signature.startswith("async def adiscover(self, target")
    assert (
        registry["e_infra.infra.proxy.LazyProxy"].bases == ()
    )  ### PEP 695 generics: the parameters live in the name, not the bases.


def test_discover_sweeps_selects_and_filters(registry: CodeRegistry) -> None:
    assert {"e_infra.ops.file.FileFinder", "e_infra.ops.compose.StackCompose"} <= set(registry.discover(Kind.CLASS))
    found = registry.discover("BaseSettings")
    assert "e_infra.infra.settings.crypto.CryptoSettings" in found
    assert "e_infra.infra.state.State" not in found  ### syntactic bases only: State names nothing.
    async_defs = registry.discover(lambda sym: sym.signature.startswith("async def"))
    assert "e_infra.ops.file.FileFinder.adiscover" in async_defs
    assert set(registry.discover(Kind.MODULE, pattern=re.compile("^file$"))) == {"e_infra.ops.file"}
    with pytest.raises(RegistryError, match="Unsupported discover target"):
        registry.discover(cast("Any", 42))


def test_children_and_mapping_surface(registry: CodeRegistry) -> None:
    ops = registry.children("e_infra.ops")
    assert {"e_infra.ops.compose", "e_infra.ops.file", "e_infra.ops.registry"} <= set(ops)
    assert "e_infra.ops.file.FileFinder" not in ops  ### one level down, never deeper
    assert "e_infra.ops.registry" in registry
    assert len(registry) == len(registry.scan())
    assert set(iter(registry)) == set(registry.scan())


def test_snapshot_is_canonical_and_stable(registry: CodeRegistry, repo: Path) -> None:
    assert registry.snapshot() == CodeRegistry(repo / ENGINE_PATH, package="e_infra").snapshot()


async def test_ascan_answers_like_scan(registry: CodeRegistry) -> None:
    assert await registry.ascan() == registry.scan()


def test_broken_empty_and_hidden_scopes_fail_loudly_or_are_invisible(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""pkg: the fixture."""\n')
    (pkg / "ok.py").write_text("import json\n")
    (pkg / "bad.py").write_text("def (\n")
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "ghost.py").write_text("class Ghost: ...\n")
    with pytest.raises(RegistryError, match=r"syntax error in bad\.py"):
        CodeRegistry(pkg).scan()
    (pkg / "bad.py").unlink()
    registry = CodeRegistry(pkg)
    assert not any(sym.name == "Ghost" for sym in registry.scan().values())  ### pycache invisible
    assert registry["pkg"].doc == "pkg: the fixture."
    assert registry["pkg"].imports == ()
    assert registry["pkg.ok"].imports == ("json",)
    void = tmp_path / "void"
    void.mkdir()
    with pytest.raises(RegistryError, match="empty scope"):
        CodeRegistry(void).scan()


def test_pep695_underscored_relative_and_raw_facts(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "_hidden.py").write_text(
        '"""demo/_hidden: private module."""\ntype Alias = int | str\n\n\n@decor\nclass Widget(Base, metaclass=M):\n'
        "    LIMIT: int = 3\n\n"
        '    def shape(self, a, /, b: str = "x", *rest, flag: bool = True, **kw) -> None: ...\n'
    )
    (pkg / "main.py").write_text("from . import missing\nfrom ._hidden import Alias\n")
    (pkg / "data.json").write_text("{}")
    registry = CodeRegistry(pkg, package="demo")
    assert registry["demo._hidden"].kind is Kind.MODULE
    assert registry["demo._hidden"].private
    assert registry["demo._hidden.Alias"].kind is Kind.ALIAS
    assert registry["demo._hidden.Alias"].value == "int | str"
    widget = registry["demo._hidden.Widget"]
    assert widget.bases == ("Base",)
    assert widget.decorators == ("decor",)
    assert registry["demo._hidden.Widget.LIMIT"].value == "3"
    assert (
        registry["demo._hidden.Widget.shape"].signature
        == "def shape(self, a, /, b: str = 'x', *rest, flag: bool = True, **kw) -> None"
    )
    assert registry["demo.main"].imports == (
        "demo.missing",
        "demo._hidden",
    )  ### relative resolved at source level, nothing imported
    raw = registry["data.json"]
    assert raw.kind is Kind.FILE
    assert raw.parent == "demo"
