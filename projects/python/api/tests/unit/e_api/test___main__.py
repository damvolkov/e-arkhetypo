"""tests/unit/e_api/__main__: `python -m e_api` — the dev runner serves the app factory; `admin` prints the first key."""

import runpy
import sys
from importlib import import_module
from typing import TYPE_CHECKING, Any, Self

import granian

from e_api.api import admin
from e_api.main import create_app
from infra.auth.models import Issued, Role
from infra.settings import settings as st

if TYPE_CHECKING:
    import pytest


class FakeGranian:
    """Granian standing in for the server: records what it was built with, serves nothing."""

    built: list[dict[str, Any]] = []  # noqa: RUF012 — the recorder is the test's own, reset by `monkeypatch`

    def __init__(self, **kwargs: Any) -> None:
        self.built.append(kwargs)

    def serve(self) -> Self:
        return self


### sync on purpose: the runner under test calls `asyncio.run`, which a running loop refuses.
def test_main_admin_prints_the_key_and_serves_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def minted() -> Issued:
        return Issued(owner="o", name="admin", role=Role.ADMIN, token="the-one-time-key")

    monkeypatch.setattr(sys, "argv", ["e_api", "admin"])
    monkeypatch.setattr(admin, "mint", minted)
    monkeypatch.setattr(granian, "Granian", FakeGranian)
    monkeypatch.setattr(FakeGranian, "built", [])
    runpy.run_module("e_api", run_name="__main__")
    assert (capsys.readouterr().out, FakeGranian.built) == ("the-one-time-key\n", [])


def test_main_serves_the_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["e_api"])
    monkeypatch.setattr(granian, "Granian", FakeGranian)
    monkeypatch.setattr(FakeGranian, "built", [])
    runpy.run_module("e_api", run_name="__main__")
    (built,) = FakeGranian.built
    module, _, factory = built["target"].partition(":")
    assert getattr(import_module(module), factory) is create_app
    assert (built["factory"], built["port"], built["address"]) == (True, st.APP_PORT, st.APP_HOST)


def test_main_imported_serves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(granian, "Granian", FakeGranian)
    monkeypatch.setattr(FakeGranian, "built", [])
    runpy.run_module("e_api.__main__")
    assert FakeGranian.built == []
