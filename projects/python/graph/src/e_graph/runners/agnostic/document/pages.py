"""runners.agnostic.document.pages: the pages of an ingested document worth reading, as the prompt's material.

A page scores ten per title opening it and one per word it holds: a statement's page opens with its
title, while notes and indexes name it deeper down or hold few of its words — measured on two 10-Ks
(2026-10-14), the statement ranks first for the income statement and the balance sheet alike, where
counting every mention ranked notes first. The leading `first` pages always come, then the `most` best."""

import heapq
from typing import Annotated, Any, Final

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Address, Call

TITLE: Final[int] = 10


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`source`: the output holding the pages (`{"pages": [{"number", "markdown"}]}`); `titles`: what a page
    worth reading opens with, within its first `head` characters; `words`: what it holds, case aside;
    `first`: leading pages always kept; `most`: best pages kept."""

    source: Address = "ingest/ING-document"
    titles: tuple[str, ...] = ()
    words: tuple[str, ...] = ()
    first: Annotated[int, msgspec.Meta(ge=0)] = 0
    most: Annotated[int, msgspec.Meta(ge=0)] = 3
    head: Annotated[int, msgspec.Meta(ge=1)] = 300

    def score(self, page: dict[str, Any]) -> int:
        """How much a page says of what is sought: ten per title opening it, one per word it holds."""
        text = page["markdown"].lower()
        titles = sum(title.lower() in text[: self.head] for title in self.titles)
        return TITLE * titles + sum(word.lower() in text for word in self.words)


async def pre_run(state: RunState, call: Call) -> str:
    """The leading pages and the best-scoring ones, in page order, each headed by its number."""
    section, _, spec = call.args.source.partition("/")
    pages = getattr(state.context, section)[spec]["pages"]
    ### nlargest by key is stable: on a tie, the earlier page wins.
    best = {
        page["number"] for page in heapq.nlargest(call.args.most, pages, key=call.args.score) if call.args.score(page)
    }
    chosen = best | {page["number"] for page in pages[: call.args.first]}
    return "\n\n".join(f"## Page {page['number']}\n{page['markdown']}" for page in pages if page["number"] in chosen)
