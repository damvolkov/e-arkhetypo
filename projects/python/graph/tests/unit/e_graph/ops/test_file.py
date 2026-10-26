"""tests/unit: FileFinder — agnostic dispatch over installed packages (the settings composer's engine)."""

import re
from typing import Any, cast

import pytest

from infra.settings import crypto as crypto_mod
from infra.settings.base import BaseSettings
from ops.file import FileFinder, Kind

INFRA = FileFinder("infra")
SETTINGS = FileFinder("infra.settings")


def test_modules_skips_packages_and_declared_names() -> None:
    ### `settings` is a package: excluded
    assert {"logger", "state"} <= set(INFRA.discover(Kind.MODULES))
    assert "base" in SETTINGS.discover(Kind.MODULES)
    strict = FileFinder("infra.settings", skip=frozenset({"base"}))
    assert "base" not in strict.discover(Kind.MODULES)


def test_classes_and_functions_are_own_symbols_only() -> None:
    assert "State" in INFRA.discover(Kind.CLASSES)
    assert "ELogger" in INFRA.discover(Kind.CLASSES)
    ### `setup` lives on ELogger now, not in the module namespace: only the plain function is discoverable.
    assert {"encode_json"} <= set(INFRA.discover(Kind.FUNCTIONS))


def test_base_selects_subclasses_and_module_target_reads_one_file() -> None:
    assert {"CryptoSettings", "OAuthSettings"} <= set(SETTINGS.discover(BaseSettings))
    assert set(SETTINGS.discover(crypto_mod)) == {"CryptoSettings"}


def test_predicate_and_pattern_filter_rejects_unknown_target() -> None:
    found = SETTINGS.discover(lambda obj: isinstance(obj, type) and obj.__name__.endswith("Settings"))
    assert "CryptoSettings" in found
    assert "TokenAlg" not in found
    assert set(SETTINGS.discover(Kind.CLASSES, pattern=re.compile("^Crypto"))) == {"CryptoSettings"}
    with pytest.raises(TypeError, match="Unsupported discover target"):
        SETTINGS.discover(cast("Any", 42))


async def test_adiscover_answers_like_discover() -> None:
    assert await INFRA.adiscover(Kind.MODULES) == INFRA.discover(Kind.MODULES)
