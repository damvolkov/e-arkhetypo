"""infra/config/theme: the house theme — background, corporate hue and ink.

Three colors, no more: the background the frames sit on, the corporate hue (frames, mastheads,
rules, emphasis — the same #0277bd `ops.tui.HeaderTui` paints with) and the ink for content text.
Any surface that wants color reads it from here; a literal hex outside this file is a drift bug."""

import re

from pydantic import field_validator

from e_infra.infra.config.base import BaseSettings

##### DEFAULTS #####
BACKGROUND: str = "#000000"
CORPORATE: str = "#0277bd"  # dark sky blue: letters and frame
INK: str = "#d8d9da"

_HEX_RE: re.Pattern[str] = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


class ThemeSettings(BaseSettings):
    """The only three colors a tui may use. Validated as #rgb or #rrggbb on load, never at runtime."""

    theme_background: str = BACKGROUND
    theme_corporate: str = CORPORATE
    theme_ink: str = INK

    @field_validator("theme_background", "theme_corporate", "theme_ink")
    @classmethod
    def _hex_only(cls, value: str) -> str:
        """Lowercased hex or a hard failure at load."""
        ### Lowercasing once here keeps every consumer's equality checks honest.
        if not _HEX_RE.fullmatch(value):
            bad = f"not a #rgb/#rrggbb hex color: {value!r}"
            raise ValueError(bad)
        return value.lower()
