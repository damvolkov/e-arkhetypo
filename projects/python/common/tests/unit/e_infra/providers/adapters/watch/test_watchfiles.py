"""tests/unit/e_infra/providers/adapters/watch/watchfiles: a real folder's batches — added, a quiet tick, ignored."""

from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from e_infra.ports.watch import WatchChange, WatchPort
from e_infra.providers.adapters.watch.watchfiles import WatchfilesAdapter

if TYPE_CHECKING:
    from pathlib import Path

DEBOUNCE, QUIET = timedelta(milliseconds=50), timedelta(milliseconds=100)


async def test_watchfiles_meets_the_port_and_its_lifecycle() -> None:
    async with WatchfilesAdapter() as watch:
        assert (isinstance(watch, WatchPort), await watch.health()) == (True, True)


async def test_watchfiles_a_quiet_folder_yields_an_empty_batch(tmp_path: Path) -> None:
    with anyio.fail_after(10):
        stream = WatchfilesAdapter().changes(str(tmp_path), ignored=(), debounce=DEBOUNCE, quiet=QUIET, polling=True)
        assert await anext(stream) == set()
        await stream.aclose()


@pytest.mark.parametrize(("name", "seen"), [("note.md", True), ("note.tmp", False)], ids=["kept", "ignored"])
async def test_watchfiles_an_added_file_is_a_batch_unless_ignored(tmp_path: Path, name: str, seen: bool) -> None:
    """Polling, so the test sees what any filesystem shows; the caller's pattern adds to the defaults."""
    batches: list[set[tuple[WatchChange, str]]] = []
    with anyio.fail_after(10):
        stream = WatchfilesAdapter().changes(
            str(tmp_path), ignored=(r".*\.tmp$",), debounce=DEBOUNCE, quiet=QUIET, polling=True
        )
        assert await anext(stream) == set()
        (tmp_path / name).write_text("x")
        batches = [await anext(stream) for _ in range(3)]
        await stream.aclose()
    found = {change for batch in batches for change in batch}
    assert ((WatchChange.ADDED, str(tmp_path / name)) in found) is seen
