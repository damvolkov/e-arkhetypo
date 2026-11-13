"""infra/config/theme: the house theme — background, corporate hue and ink.

Three colors, no more: the background the frames sit on, the corporate hue (frames, mastheads, rules, emphasis — the
same #0277bd `ops.tui.HeaderTui` paints with) and the ink for content text. Any surface that wants color reads it from
here; a literal hex outside this file is a drift bug."""

import re
from typing import Final

from pydantic import field_validator

from e_infra.infra.config.base import BaseSettings

##### DEFAULTS #####
HEX: Final[re.Pattern[str]] = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


##### SETTINGS #####
class ThemeSettings(BaseSettings):
    """The only three colors a tui may use. Validated as #rgb or #rrggbb on load, never at runtime."""

    THEME_BACKGROUND: str = "#000000"
    ### dark sky blue: letters and frame.
    THEME_CORPORATE: str = "#0277bd"
    THEME_INK: str = "#d8d9da"

    @field_validator("THEME_BACKGROUND", "THEME_CORPORATE", "THEME_INK")
    @classmethod
    def _common_theme_hex(cls, value: str) -> str:
        ### lowercasing once here keeps every consumer's equality checks honest.
        match HEX.fullmatch(value):
            case None:
                msg = f"not a #rgb/#rrggbb hex color: {value!r}"
                raise ValueError(msg)
            case _:
                return value.lower()
