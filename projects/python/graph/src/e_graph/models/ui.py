"""models.ui: the canvas tunables as the UI reads them over the API — milliseconds and pixels, nothing to parse."""

import msgspec


class UiView(msgspec.Struct, frozen=True, kw_only=True):
    """`toast_ms` how long a node toast stays; `pace` the per-node pause (seconds) a demo run asks for;
    `lane_gap` / `rank_gap` the pixels between parallel lanes and sequential ranks."""

    toast_ms: int
    pace: float
    lane_gap: int
    rank_gap: int
