"""tests/unit/e_management/adapters/draft: the session survives terminals — round-trip, TTL, legacy schema and corruption all answered."""

import time
from typing import TYPE_CHECKING

import msgspec

from e_management.adapters.draft import DEFAULT_TTL, DraftStore, Envelope
from e_management.core.session import Session, Step

if TYPE_CHECKING:
    from pathlib import Path


def _write(store: DraftStore, session: Session, saved_at: float) -> None:
    store.path.write_bytes(msgspec.json.encode(Envelope(saved_at=saved_at, session=session)))


def test_draft_round_trips_decisions(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    session = Session(template="api", name="myapp", off=("websockets",), seen=(Step.SYSTEM,))
    store.save(session)
    assert store.load() == session


def test_draft_load_is_none_without_a_file(tmp_path: Path) -> None:
    assert DraftStore(tmp_path / "draft.json").load() is None


def test_draft_load_is_none_on_a_corrupt_file(tmp_path: Path) -> None:
    broken = tmp_path / "draft.json"
    broken.write_text("[1,2]")
    assert DraftStore(broken).load() is None


def test_draft_expires_once_past_the_ttl(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    _write(store, Session(template="api"), time.time() - DEFAULT_TTL - 1)
    assert store.load() is None
    assert not store.path.exists(), "an expired draft must be cleaned up"


def test_draft_with_legacy_step_tokens_is_discarded(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    _write(store, Session(template="api", seen=("template", "name", "pieces")), time.time())
    assert store.load() is None


def test_draft_drop_is_idempotent(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "draft.json")
    store.save(Session())
    store.drop()
    store.drop()
    assert store.load() is None
