"""models.section: the closed DARTS taxonomy — the sections a pipeline is cut into, in fixed order.

The declaration order *is* the law: every loader, scheduler and graph that mounts sections walks
them as `ORDER` says. A system uses only the sections it needs; the minimum viable pipeline is
ingest → extract → transform → report. Cross-cutting concerns (logs, lineage, versioning, cache)
are never a section — the runtime does them in all of them.

`CUSTOM` holds what DARTS does not name: it has a prefix but no place in `ORDER` — the pipeline that
uses it wires it where it belongs. Every spec name opens with its section's `PREFIXES` entry
(`EXT-total-amount`): three letters, because one would collide (ingest, inference)."""

from enum import StrEnum, auto
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping


class Section(StrEnum):
    """One stage of the pipeline; the value is the folder name under `nodes/`."""

    INGEST = auto()
    NORMALIZE = auto()
    CLASSIFY = auto()
    EXTRACT = auto()
    VALIDATE = auto()
    ENRICH = auto()
    INFERENCE = auto()
    AUDIT = auto()
    TRANSFORM = auto()
    REPORT = auto()
    CUSTOM = auto()


ORDER: Final[tuple[Section, ...]] = tuple(section for section in Section if section is not Section.CUSTOM)
PREFIXES: Final[Mapping[Section, str]] = MappingProxyType(
    {
        Section.INGEST: "ING",
        Section.NORMALIZE: "NOR",
        Section.CLASSIFY: "CLS",
        Section.EXTRACT: "EXT",
        Section.VALIDATE: "VAL",
        Section.ENRICH: "ENR",
        Section.INFERENCE: "INF",
        Section.AUDIT: "AUD",
        Section.TRANSFORM: "TRF",
        Section.REPORT: "REP",
        Section.CUSTOM: "CUS",
    }
)
