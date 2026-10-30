"""tests/unit/e_infra/processors: the real fast pass, open, for the processor that reads pages.

`opened` is a liteparse adapter whose parser is already built — what the lifespan's `async with` leaves — so a
synchronous constructor can hand it to the processor under test."""

from typing import TYPE_CHECKING

from e_infra.providers.adapters.liteparse import LiteparseAdapter

if TYPE_CHECKING:
    from e_infra.infra.config.doc import DocSettings


def opened(settings: DocSettings) -> LiteparseAdapter:
    pages = LiteparseAdapter(settings)
    pages._parser = pages._enter_parser()
    return pages
