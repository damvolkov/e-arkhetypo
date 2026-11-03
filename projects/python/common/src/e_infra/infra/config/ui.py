"""infra/config/ui: the canvas's tunables — toast lifetime, run pace and grid spacing (UI_*)."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class UiSettings(BaseSettings):
    """UI_TOAST — how long a node toast stays; UI_PACE — the per-node pause a demo run asks for (so a
    human can follow it); UI_LANE_GAP / UI_RANK_GAP — canvas pixels between parallel lanes and sequential
    ranks. Timedeltas: plain seconds in a config file or kwargs, `PT2.5S` in env."""

    model_config = SettingsConfigDict(env_prefix="UI_")

    toast: timedelta = timedelta(seconds=2.5)
    pace: timedelta = timedelta(seconds=0.35)
    lane_gap: int = 240
    rank_gap: int = 140
