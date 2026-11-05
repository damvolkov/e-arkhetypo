"""infra/config/ui: the canvas's tunables — toast lifetime, run pace and grid spacing."""

from datetime import timedelta

from pydantic import NonNegativeInt

from e_infra.infra.config.base import BaseSettings


##### SETTINGS #####
class UiSettings(BaseSettings):
    """The canvas: timedeltas are plain seconds in a config file or kwargs, `PT2.5S` in env."""

    ### how long a node toast stays.
    UI_TOAST: timedelta = timedelta(seconds=2.5)
    ### the per-node pause a demo run asks for, so a human can follow it.
    UI_PACE: timedelta = timedelta(seconds=0.35)
    ### canvas pixels between parallel lanes and sequential ranks.
    UI_LANE_GAP: NonNegativeInt = 240
    UI_RANK_GAP: NonNegativeInt = 140
