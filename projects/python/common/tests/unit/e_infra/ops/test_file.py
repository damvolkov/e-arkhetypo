"""tests/unit: FileFinder — agnostic dispatch over installed packages (the settings composer's engine)."""

import re
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from e_infra.infra.config import infra as infra_mod
from e_infra.infra.config.base import BaseSettings
from e_infra.ops.file import FileDetector, FileError, FileFinder, FileLayer, Kind

if TYPE_CHECKING:
    from pathlib import Path

INFRA = FileFinder("e_infra.infra")
CONFIG = FileFinder("e_infra.infra.config")


def test_modules_skips_packages_and_declared_names() -> None:
    assert {"logger", "settings", "state"} <= set(INFRA.discover(Kind.MODULES))
    ### `config` is a package: excluded.
    assert "config" not in INFRA.discover(Kind.MODULES)
    assert "base" in CONFIG.discover(Kind.MODULES)
    strict = FileFinder("e_infra.infra.config", skip=frozenset({"base"}))
    assert "base" not in strict.discover(Kind.MODULES)


def test_classes_and_functions_are_own_symbols_only() -> None:
    assert "State" in INFRA.discover(Kind.CLASSES)
    assert "ELogger" in INFRA.discover(Kind.CLASSES)
    ### `setup` lives on ELogger now, not in the module.
    assert {"encode_json"} <= set(INFRA.discover(Kind.FUNCTIONS))


def test_base_selects_subclasses_and_module_target_reads_one_file() -> None:
    assert {"InfraSettings", "ProviderSettings"} <= set(CONFIG.discover(BaseSettings))
    ### `base.py` is part of the sweep: the base itself is still never a result.
    assert "BaseSettings" not in CONFIG.discover(BaseSettings)
    assert set(CONFIG.discover(infra_mod)) == {"Env", "InfraSettings"}


def test_predicate_and_pattern_filter_rejects_unknown_target() -> None:
    found = CONFIG.discover(lambda obj: isinstance(obj, type) and obj.__name__.endswith("Settings"))
    assert "InfraSettings" in found
    assert "Env" not in found
    assert set(CONFIG.discover(Kind.CLASSES, pattern=re.compile("^Infra"))) == {"InfraSettings"}
    with pytest.raises(FileError, match="Unsupported discover target"):
        CONFIG.discover(cast("Any", 42))


def test_private_modules_are_never_imported_nor_seen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "_hidden.py").write_text("class Hidden: ...")
    (tmp_path / "pkg" / "shown.py").write_text("class Shown: ...")
    monkeypatch.syspath_prepend(str(tmp_path))
    finder = FileFinder("pkg")
    assert set(finder.discover(Kind.MODULES)) == {"shown"}
    assert "Hidden" not in finder.discover(Kind.CLASSES)


async def test_adiscover_answers_like_discover() -> None:
    assert await INFRA.adiscover(Kind.MODULES) == INFRA.discover(Kind.MODULES)


def test_summary_reads_the_top_description_line() -> None:
    summary = FileFinder.summary(infra_mod)
    assert (
        summary == "infra/config/infra: the process — its environment, where it listens, and the crypto it signs with."
    )
    assert "\n" not in summary


def test_summaries_answers_every_module_with_its_description() -> None:
    found = CONFIG.summaries()
    assert set(found) == set(CONFIG.discover(Kind.MODULES))
    assert all(desc.startswith(f"infra/config/{name}: ") for name, desc in found.items())


async def test_asummaries_answers_like_summaries() -> None:
    assert await CONFIG.asummaries() == CONFIG.summaries()


def test_summary_survives_missing_and_blank_docstrings() -> None:
    assert FileFinder.summary(types.ModuleType("bare")) == ""
    blank = types.ModuleType("blank")
    blank.__doc__ = "   "
    assert FileFinder.summary(blank) == ""


##### DETECTOR #####
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("script", (None, "python", True, FileLayer.CONTENT)),
        ("paper", ("pdf", None, False, FileLayer.ANYTOMD)),
        ("cat.jpg", ("image", None, False, FileLayer.ANYTOMD)),
        ("report.docx", ("docx", None, False, FileLayer.ZIP)),
        ("main.py", ("code", "python", True, FileLayer.ANYTOMD)),
        ("lib.rs", ("code", "rust", True, FileLayer.ANYTOMD)),
        ("config.json", ("json", "json", True, FileLayer.ANYTOMD)),
        ("Dockerfile", (None, "dockerfile", True, FileLayer.PATH)),
        ("Makefile", (None, "make", True, FileLayer.PATH)),
        ("notes.md", ("txt", "markdown", True, FileLayer.ANYTOMD)),
        ("page.html", ("html", "html", True, FileLayer.ANYTOMD)),
        ("readme", ("txt", None, True, FileLayer.SNIFF)),
        ("noise.bin", (None, None, False, FileLayer.MIME)),
    ],
)
async def test_detector_detect(
    samples: Path, name: str, expected: tuple[str | None, str | None, bool, FileLayer]
) -> None:
    found = await FileDetector().detect(str(samples / name))
    assert (found.format, found.language, found.is_text, found.because) == expected


async def test_detector_detect_head_given(samples: Path) -> None:
    """A head handed in is the whole evidence: the path is only a name, never read."""
    found = await FileDetector().detect(str(samples / "absent.pdf"), head=b"%PDF-1.7\n")
    assert (found.format, found.mime) == ("pdf", "application/pdf")


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"\x00\x01\x02", (None, False, FileLayer.NONE)),
        (b"caf\xc3", ("txt", True, FileLayer.SNIFF)),
        (b"\xff\xfe\xfd", (None, False, FileLayer.NONE)),
        (b"", ("txt", True, FileLayer.SNIFF)),
    ],
    ids=["nul", "utf8-cut-at-the-edge", "not-utf8", "empty"],
)
def test_detector_classify(head: bytes, expected: tuple[str | None, bool, FileLayer]) -> None:
    found = FileDetector.classify("blob", head)
    assert (found.format, found.is_text, found.because) == expected


@pytest.mark.parametrize(
    ("head", "fmt"),
    [
        (b"<!DOCTYPE html><html><body>x</body></html>", "html"),
        (b"\xef\xbb\xbf  <!-- served -->\n<html lang='en'>", "html"),
        (b"Plain words about html.", "txt"),
    ],
    ids=["doctype", "bom-comment", "prose"],
)
def test_detector_page_without_extension(head: bytes, fmt: str) -> None:
    """A page served at an address with no extension is told by its head: HTML, read as such — prose stays text."""
    found = FileDetector.classify("https://12factor.net/config", head)
    assert (found.format, found.because) == (fmt, FileLayer.SNIFF)


def test_recursive_names_every_module_below_by_its_dotted_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tree" / "deep" / "_private").mkdir(parents=True)
    (tmp_path / "tree" / "top.py").write_text("class Top: ...")
    (tmp_path / "tree" / "deep" / "leaf.py").write_text("class Leaf: ...")
    (tmp_path / "tree" / "deep" / "_private" / "hid.py").write_text("class Hid: ...")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert sorted(FileFinder("tree", recursive=True).discover(Kind.MODULES)) == ["deep.leaf", "top"]
