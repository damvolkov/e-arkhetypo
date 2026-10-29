"""runners.agnostic.table/rows: the markdown table whose header holds the given words — its rows as records.

A pipe table is a run of consecutive lines opening with `|` inside one page: the first is the header, a
line of dashes separates it, the rest are data. The first table whose header row holds every word of
`header` (case aside) answers; each data row becomes a record, its cells named in order by `columns`.
Cells are stripped of padding and trailing footnote markers; a row of another width is dropped."""

import re
from itertools import groupby
from typing import Annotated, Any, Final

import msgspec

from e_graph.instrument.state import RunState
from e_graph.logic.models import Address, Call
from infra.struct import CheckedStruct

RULE: Final[re.Pattern[str]] = re.compile(r"[\s:|-]+")
MARKS: Final[re.Pattern[str]] = re.compile(r"[*†‡]+$")
BAR: Final[str] = "|"


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`source`: the output holding the pages; `header`: the words every one of which the header row must hold;
    `columns`: the names given to the row's cells, in order — a row of another width is dropped."""

    source: Address = "ingest/ING-document"
    header: Annotated[tuple[str, ...], msgspec.Meta(min_length=1)]
    columns: Annotated[tuple[str, ...], msgspec.Meta(min_length=1)]

    @staticmethod
    def cells(line: str) -> list[str]:
        """The cells of a bar line: split on the bars, stripped, trailing footnote markers gone."""
        return [MARKS.sub("", cell.strip()) for cell in line.strip().strip(BAR).split(BAR)]

    def tables(self, lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
        """Every pipe table of a page: header cells and data rows, per run of consecutive bar lines."""
        blocks = [[self.cells(line) for line in block] for bar, block in groupby(lines, self.is_bar) if bar]
        return [
            (block[0], [row for row in block[1:] if not RULE.fullmatch(BAR.join(row))])
            for block in blocks
            if len(block) > 1
        ]

    @staticmethod
    def is_bar(line: str) -> bool:
        """Whether a line belongs to a pipe table: it opens with a bar."""
        return line.lstrip().startswith(BAR)


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The rows of the first table whose header holds the words, each a record named by the columns."""
    section, _, spec = call.args.source.partition("/")
    pages = getattr(state.context, section)[spec]["pages"]
    tables = [table for page in pages for table in call.args.tables(page["markdown"].splitlines())]
    matched = [
        table for table in tables if all(word.lower() in BAR.join(table[0]).lower() for word in call.args.header)
    ]
    match matched:
        case [(_, body), *_]:
            return {
                "rows": [
                    dict(zip(call.args.columns, row, strict=True)) for row in body if len(row) == len(call.args.columns)
                ]
            }
    msg = f"no table header holds all of {list(call.args.header)}"
    raise ValueError(msg)
