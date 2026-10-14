"""runners.agnostic.text.match: a regex over the chosen pages of an ingested document — its named groups.

Deterministic extraction: identifiers, amounts, a registration number, read exactly as printed. The
pattern must name its groups; each becomes an output field. Pages are searched in page order: the first
match answers (`many` gathers every match into lists instead). A pattern that finds nothing fails the
spec — which is exactly when a semantic fallback has something to rescue."""

import re
from typing import Annotated, Any

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Address, Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`source`: the output holding the pages (`{"pages": [{"number", "markdown"}]}`); `pattern`: a regex with
    named groups, the fields to harvest; `pages`: the page numbers to search, none meaning every page;
    `many`: keep every match as a list per group, not just the first."""

    source: Address = "ingest/ING-document"
    pattern: Annotated[str, msgspec.Meta(min_length=1)]
    pages: tuple[int, ...] = ()
    many: bool = False

    def _check(self) -> None:
        ### `re.compile` caches by source text: validation at discovery, compilation reused at the run.
        ### NB: `case {}` would match ANY mapping — emptiness is a guard, not a pattern.
        match re.compile(self.pattern).groupindex:
            case dict() as groups if not groups:
                msg = "the pattern names no group: (?P<field>...) gives the output its fields"
                raise ValueError(msg)
            case _:
                pass

    @property
    def matcher(self) -> re.Pattern[str]:
        """The pattern, compiled (the stdlib's own cache does the memoising)."""
        return re.compile(self.pattern)


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The named groups of the pattern's match over the chosen pages; `many` lists every match."""
    section, _, spec = call.args.source.partition("/")
    pages = getattr(state.context, section)[spec]["pages"]
    chosen = [page for page in pages if not call.args.pages or page["number"] in set(call.args.pages)]
    groupdicts = [found.groupdict() for page in chosen for found in call.args.matcher.finditer(page["markdown"])]
    matches = [groups for groups in groupdicts if any(value is not None for value in groups.values())]
    match call.args.many, matches:
        case True, [first, *_]:
            return {name: [each[name] for each in matches if each[name] is not None] for name in first}
        case _, [first, *_]:
            return first
    msg = f"{call.args.pattern!r} matched nothing in {len(chosen)} pages"
    raise ValueError(msg)
