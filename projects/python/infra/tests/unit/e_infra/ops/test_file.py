"""tests/unit: FileFinder — agnostic dispatch over installed packages (the settings composer's engine)."""

import re
import types
from typing import TYPE_CHECKING, Any, cast

import pytest

from e_infra.infra.settings import crypto as crypto_mod
from e_infra.infra.settings.base import BaseSettings
from e_infra.ops.file import FileError, FileFinder, Kind

if TYPE_CHECKING:
    from pathlib import Path

INFRA = FileFinder("e_infra.infra")
SETTINGS = FileFinder("e_infra.infra.settings")


def test_modules_skips_packages_and_declared_names() -> None:
    assert {"logger", "state"} <= set(INFRA.discover(Kind.MODULES))  # `settings` is a package: excluded
    assert "base" in SETTINGS.discover(Kind.MODULES)
    strict = FileFinder("e_infra.infra.settings", skip=frozenset({"base"}))
    assert "base" not in strict.discover(Kind.MODULES)


def test_classes_and_functions_are_own_symbols_only() -> None:
    assert "State" in INFRA.discover(Kind.CLASSES)
    assert "ELogger" in INFRA.discover(Kind.CLASSES)
    assert {"encode_json"} <= set(INFRA.discover(Kind.FUNCTIONS))  # `setup` lives on ELogger now, not in the module


def test_base_selects_subclasses_and_module_target_reads_one_file() -> None:
    assert {"CryptoSettings", "OAuthSettings"} <= set(SETTINGS.discover(BaseSettings))
    ### `base.py` is part of the sweep: the base itself is still never a result.
    assert "BaseSettings" not in SETTINGS.discover(BaseSettings)
    assert set(SETTINGS.discover(crypto_mod)) == {"CryptoSettings"}


def test_predicate_and_pattern_filter_rejects_unknown_target() -> None:
    found = SETTINGS.discover(lambda obj: isinstance(obj, type) and obj.__name__.endswith("Settings"))
    assert "CryptoSettings" in found
    assert "TokenAlg" not in found
    assert set(SETTINGS.discover(Kind.CLASSES, pattern=re.compile("^Crypto"))) == {"CryptoSettings"}
    with pytest.raises(FileError, match="Unsupported discover target"):
        SETTINGS.discover(cast("Any", 42))


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
    summary = FileFinder.summary(crypto_mod)
    assert (
        summary
        == "infra/settings/crypto: the configuration of the crypto engine (`ops/crypto`), loaded from CRYPTO__*."
    )
    assert "\n" not in summary


def test_summaries_answers_every_module_with_its_description() -> None:
    found = SETTINGS.summaries()
    assert set(found) == set(SETTINGS.discover(Kind.MODULES))
    assert all(desc.startswith(f"infra/settings/{name}: ") for name, desc in found.items())


async def test_asummaries_answers_like_summaries() -> None:
    assert await SETTINGS.asummaries() == SETTINGS.summaries()


def test_summary_survives_missing_and_blank_docstrings() -> None:
    assert FileFinder.summary(types.ModuleType("bare")) == ""
    blank = types.ModuleType("blank")
    blank.__doc__ = "   "
    assert FileFinder.summary(blank) == ""
