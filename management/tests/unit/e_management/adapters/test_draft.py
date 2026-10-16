"""tests/unit/e_management/adapters/draft: the session survives terminals — round-trip, TTL and corruption all answered."""

import time
from typing import TYPE_CHECKING

import msgspec

from e_management.adapters.draft import DEFAULT_TTL, DraftStore, Envelope
from e_management.core.session import Session

if TYPE_CHECKING:
    from pathlib import Path


def _write(store: DraftStore, session: Session, saved_at: float) -> None:
    store.path.write_bytes(msgspec.json.encode(Envelope(saved_at=saved_at, session=session)))


def test_draft_round_trips_a_walk(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    session = Session(
        template="api",
        name="myapp",
        ci_off=("docs",),
        at="tools-adapters",
        trail=("system", "name"),
        answers={"system": ("api",)},
    )
    store.save(session)
    assert store.load() == session


def test_draft_load_is_none_without_a_file(tmp_path: Path) -> None:
    assert DraftStore(tmp_path / "draft.json").load() is None


def test_draft_load_is_none_on_a_corrupt_file_and_clears_it(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    store.path.write_bytes(b"{not json")
    assert store.load() is None
    assert not store.path.exists()


def test_draft_load_is_none_when_expired(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    _write(store, Session(template="api"), saved_at=time.time() - DEFAULT_TTL - 1)
    assert store.load() is None
    assert not store.path.exists()


def test_draft_drop_is_idempotent(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    store.drop()
    store.save(Session())
    store.drop()
    assert store.load() is None
