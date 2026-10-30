"""tests/unit/e_infra/infra/config: ThemeSettings — three colors, hex-validated at load, never at runtime."""

import pytest
from pydantic import ValidationError

from e_infra.infra.config.theme import CORPORATE, ThemeSettings


def test_theme_defaults_hold_the_house_trio() -> None:
    theme = ThemeSettings()
    assert theme.theme_background == "#000000"
    assert theme.theme_corporate == CORPORATE
    assert theme.theme_ink.startswith("#")


@pytest.mark.parametrize("value", ["#0A77BD", "#abc", "#123456"])
def test_theme_accepts_hex_and_lowercases(value: str) -> None:
    theme = ThemeSettings(theme_corporate=value)
    assert theme.theme_corporate == value.lower()


@pytest.mark.parametrize("value", ["blue", "0277bd", "#12", "#gggggg", "#1234567", ""])
def test_theme_rejects_non_hex_at_load(value: str) -> None:
    with pytest.raises(ValidationError):
        ThemeSettings(theme_corporate=value)
