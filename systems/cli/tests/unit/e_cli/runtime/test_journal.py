"""tests/unit/e_cli/runtime/journal: the StorePort decorator — first value kept, clean exits filed, depth bounded."""

import pytest

from adapters.ports import StorePort
from e_cli.models.error import JournalError
from e_cli.runtime.journal import PREFIX, StoreJournal


def test_journal_satisfies_the_store_port(store) -> None:
    assert isinstance(StoreJournal(store, command="x", depth=5), StorePort)


async def test_journal_undo_restores_the_value_before_the_first_write(store) -> None:
    store.data["k"] = b"orig"
    async with StoreJournal(store, command="edit", depth=5) as journal:
        await journal.set("k", b"one")
        await journal.set("k", b"two")
        await journal.set("new", b"x")
    entry = await StoreJournal(store, command="undo", depth=5).undo()
    assert entry.command == "edit"
    assert store.data == {"k": b"orig"}


async def test_journal_undo_of_a_delete_brings_the_key_back(store) -> None:
    store.data["k"] = b"orig"
    async with StoreJournal(store, command="rm", depth=5) as journal:
        await journal.delete("k")
    await StoreJournal(store, command="undo", depth=5).undo()
    assert store.data["k"] == b"orig"


async def test_journal_files_nothing_when_the_run_fails(store) -> None:
    journal = StoreJournal(store, command="boom", depth=5)
    await journal.set("k", b"v")
    await journal.__aexit__(RuntimeError, RuntimeError(), None)
    assert not [key async for key in store.keys(PREFIX)]


async def test_journal_files_nothing_for_a_read_only_run(store) -> None:
    async with StoreJournal(store, command="read", depth=5) as journal:
        await journal.get("k")
        assert [key async for key in journal.keys("any")] == []
    assert await StoreJournal(store, command="list", depth=5).entries() == []


async def test_journal_keeps_only_the_newest_depth_runs(store) -> None:
    for step in range(3):
        async with StoreJournal(store, command=f"run {step}", depth=2) as journal:
            await journal.set("k", str(step).encode())
    entries = await StoreJournal(store, command="list", depth=2).entries()
    assert [entry.command for entry in entries] == ["run 2", "run 1"]


async def test_journal_undo_on_empty_is_refused(store) -> None:
    with pytest.raises(JournalError, match="nothing to undo"):
        await StoreJournal(store, command="undo", depth=5).undo()
