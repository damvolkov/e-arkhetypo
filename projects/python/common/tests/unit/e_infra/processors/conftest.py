"""tests/unit/e_infra/processors: the real fast pass, open, for the processor that reads pages.

`opened` is a liteparse adapter whose parser is already built — what the lifespan's `async with` leaves — so a
synchronous constructor can hand it to the processor under test."""

from e_infra.infra.config.providers.adapters.pages.liteparse import LiteparseSettings
from e_infra.providers.adapters.pages.liteparse import LiteparseAdapter


def opened() -> LiteparseAdapter:
    pages = LiteparseAdapter(LiteparseSettings())
    pages._parser = pages._enter_parser()
    return pages
