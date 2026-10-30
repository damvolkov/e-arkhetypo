"""tests/unit/e_infra/infra/errors: one root for every error — none is defined elsewhere, and the tree says how it fails."""

import importlib
from pathlib import Path
from typing import Final

import pytest

from e_infra.infra import errors
from e_infra.infra.errors import (
    AdapterError,
    CacheError,
    ComposeError,
    CoreError,
    CryptoError,
    DatabaseError,
    DispatchError,
    DocumentError,
    DriverError,
    EngineError,
    FileError,
    HttpError,
    HttpTimeoutError,
    InputTooLargeError,
    LogoError,
    MDError,
    ModelError,
    OpsError,
    ParseError,
    ProcessorError,
    ProviderError,
    QueueError,
    RegistryError,
    ScheduleError,
    StoreError,
    TelemetryError,
    TokenError,
    TokenFailure,
    TruncatedError,
    UnknownWorkError,
    UnsupportedFormatError,
    ZipBombError,
)

PACKAGE: Final = Path(__file__).resolve().parents[4] / "src" / "e_infra"


def _exceptions() -> dict[str, type[BaseException]]:
    """Every exception class found in a module of the package, by qualified name, wherever it is defined."""
    modules = [
        importlib.import_module("e_infra." + path.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", "."))
        for path in sorted(PACKAGE.rglob("*.py"))
    ]
    return {
        f"{module.__name__}.{name}": cls
        for module in modules
        for name, cls in vars(module).items()
        if isinstance(cls, type) and issubclass(cls, BaseException) and cls.__module__ == module.__name__
    }


EXCEPTIONS: Final = _exceptions()


def test_errors_every_exception_is_defined_in_the_root() -> None:
    strays = sorted(name for name in EXCEPTIONS if not name.startswith("e_infra.infra.errors."))
    assert not strays, f"exceptions defined outside infra/errors: {strays}"


def test_errors_the_walk_finds_the_tree() -> None:
    assert {"e_infra.infra.errors.CoreError", "e_infra.infra.errors.TokenError"} <= EXCEPTIONS.keys()


@pytest.mark.parametrize("name", [name for name in vars(errors) if name.endswith("Error")])
def test_errors_everything_descends_from_core(name: str) -> None:
    assert issubclass(getattr(errors, name), CoreError)


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (DriverError, ProviderError),
        (AdapterError, ProviderError),
        (DatabaseError, DriverError),
        (StoreError, DriverError),
        (QueueError, DriverError),
        (HttpError, DriverError),
        (HttpTimeoutError, HttpError),
        (HttpTimeoutError, TimeoutError),
        (TelemetryError, DriverError),
        (ModelError, DriverError),
        (TruncatedError, ModelError),
        (ParseError, AdapterError),
        (CacheError, DriverError),
        (CacheError, AdapterError),
        (DocumentError, DriverError),
        (DocumentError, AdapterError),
        (DispatchError, EngineError),
        (ScheduleError, DispatchError),
        (ScheduleError, ValueError),
        (UnknownWorkError, DispatchError),
        (UnknownWorkError, LookupError),
        (MDError, ProcessorError),
        (MDError, RuntimeError),
        (UnsupportedFormatError, MDError),
        (InputTooLargeError, MDError),
        (ZipBombError, MDError),
        (ComposeError, OpsError),
        (ComposeError, ValueError),
        (RegistryError, OpsError),
        (FileError, TypeError),
        (LogoError, OpsError),
        (CryptoError, OpsError),
        (TokenError, CryptoError),
    ],
)
def test_errors_tree_holds(child: type[BaseException], parent: type[BaseException]) -> None:
    assert issubclass(child, parent)


@pytest.mark.parametrize(
    ("child", "stranger"),
    [
        (DatabaseError, AdapterError),
        (ParseError, DriverError),
        (DispatchError, ProviderError),
        (MDError, ProviderError),
        (CryptoError, ProviderError),
    ],
)
def test_errors_branches_stay_apart(child: type[BaseException], stranger: type[BaseException]) -> None:
    assert not issubclass(child, stranger)


def test_errors_message_and_status_ride_along() -> None:
    http = HttpError("down", 503)
    assert (http.message, http.status) == ("down", 503)


def test_errors_token_carries_its_failure() -> None:
    assert TokenError("bad", kind=TokenFailure.FORGED).kind is TokenFailure.FORGED
    assert TokenError("bad").kind is TokenFailure.MALFORMED
